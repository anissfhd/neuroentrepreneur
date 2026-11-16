"""Plafond de depense des appels au modele, avec registre persistant (D-83).

Active seulement si ``NEUROCOACH_SPENDING_CAP_USD`` est defini dans l'environnement du
processus (jamais par defaut). Avant chaque appel, le pire cas est reserve ; apres l'appel,
le cout reel (jetons comptes par le fournisseur) est inscrit dans un registre JSON Lines
partage entre processus successifs (script d'evaluation, application Streamlit). Un appel qui
pourrait depasser le plafond est refuse AVANT d'etre envoye : erreur explicite, aucune
reponse inventee.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.llm_catalog import default_catalog

# Tarifs publics de gpt-5-mini (USD par jeton) : entree, sortie. Le cache d'entree n'est pas
# deduit : le cout compte est un majorant.
PRICE_INPUT, PRICE_OUTPUT = 0.25 / 1e6, 2.0 / 1e6
WORST_OUTPUT_TOKENS = 8000  # plafond de sortie le plus haut configure (analyses)


class SpendingCap:
    def __init__(
        self,
        inner: Any,
        limit_usd: float,
        ledger: Path,
        *,
        rates: tuple[float, float] | None = None,
        output_tokens: int = WORST_OUTPUT_TOKENS,
    ) -> None:
        self.inner, self.limit, self.ledger = inner, limit_usd, ledger
        self.lock = threading.Lock()
        self.reserved = 0.0
        self.input_rate, self.output_rate = rates or (PRICE_INPUT, PRICE_OUTPUT)
        self.output_tokens = output_tokens
        ledger.parent.mkdir(parents=True, exist_ok=True)

    def __getattr__(self, name: str) -> Any:  # autres attributs du fournisseur
        return getattr(self.inner, name)

    def spent(self) -> float:
        if not self.ledger.exists():
            return 0.0
        total = 0.0
        for line in self.ledger.read_text(encoding="utf-8").splitlines():
            if line.strip():
                total += float(json.loads(line).get("cost_usd", 0.0))
        return total

    def _worst(self, messages: list[dict[str, str]]) -> float:
        chars = sum(len(m["content"]) for m in messages)
        return chars * self.input_rate + self.output_tokens * self.output_rate

    def _call(
        self,
        task: str,
        messages: list[dict[str, str]],
        run: Callable[[], Any],
        first: dict[str, float] | None = None,
    ) -> Any:
        from langchain_core.callbacks import get_usage_metadata_callback

        worst = self._worst(messages)
        with self.lock:
            if self.spent() + self.reserved + worst > self.limit:
                raise DomainError(
                    ErrorCode.LLM_UNAVAILABLE, "Plafond de dépense de la session atteint."
                )
            self.reserved += worst
        started, entry = time.monotonic(), {"task": task}
        cost = worst
        try:
            with get_usage_metadata_callback() as usage:
                result = run()
            tokens_in = sum(u.get("input_tokens", 0) for u in usage.usage_metadata.values())
            tokens_out = sum(u.get("output_tokens", 0) for u in usage.usage_metadata.values())
            if tokens_in or tokens_out:
                cost = tokens_in * self.input_rate + tokens_out * self.output_rate
            entry.update(models=list(usage.usage_metadata), input_tokens=tokens_in,
                         output_tokens=tokens_out)  # fmt: skip
            return result
        except BaseException as exc:
            entry["error"] = type(exc).__name__
            raise
        finally:
            entry.update(
                at=datetime.now(UTC).isoformat(timespec="seconds"),
                seconds=round(time.monotonic() - started, 2),
                **(
                    {"first_reply_s": round(first["at"] - started, 2)}
                    if first and "at" in first
                    else {}
                ),
                cost_usd=round(cost, 6),  # pire cas compte si aucun jeton n'est rapporte
            )
            with self.lock:
                self.reserved -= worst
                with self.ledger.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def generate_structured(self, task, messages, schema):
        return self._call(
            task, messages, lambda: self.inner.generate_structured(task, messages, schema)
        )

    def generate_text(self, task, messages):
        return self._call(task, messages, lambda: self.inner.generate_text(task, messages))

    def stream_text(self, task, messages, on_delta):
        stream = getattr(self.inner, "stream_text", None)
        if stream is None:
            return self.generate_text(task, messages)
        first: dict[str, float] = {}

        def timed(partial: str) -> None:
            first.setdefault("at", time.monotonic())
            on_delta(partial)

        return self._call(task, messages, lambda: stream(task, messages, timed), first)

    def stream_structured(self, task, messages, schema, on_partial):
        stream = getattr(self.inner, "stream_structured", None)
        if stream is None:
            return self.generate_structured(task, messages, schema)
        first: dict[str, float] = {}

        def timed(buffer: str) -> None:
            # Debut du texte de la reponse dans le flux : ce que l'interface affiche en premier.
            marker = buffer.find('"reply":"')
            if "at" not in first and marker != -1 and len(buffer) > marker + 9:
                first["at"] = time.monotonic()
            on_partial(buffer)

        return self._call(task, messages, lambda: stream(task, messages, schema, timed), first)


def capped(
    llm: Any,
    environ: dict[str, str] | None = None,
    *,
    models: tuple[str, ...] = (),
    output_tokens: int = WORST_OUTPUT_TOKENS,
) -> Any:
    """Enveloppe le fournisseur si un plafond est defini pour ce processus."""
    env = os.environ if environ is None else environ
    raw = env.get("NEUROCOACH_SPENDING_CAP_USD")
    if not raw:
        return llm
    ledger = Path(env.get("NEUROCOACH_SPENDING_LEDGER") or "data/evaluations/depenses.jsonl")
    rates = []
    for model in set(models):
        spec = default_catalog().get(model)
        if spec is None or spec.price_input is None or spec.price_output is None:
            raise ValueError(f"Tarif manquant pour le modèle {model} soumis au plafond API.")
        rates.append((spec.price_input / 1e6, spec.price_output / 1e6))
    ceiling = (max(r[0] for r in rates), max(r[1] for r in rates)) if rates else None
    return SpendingCap(llm, float(raw), ledger, rates=ceiling, output_tokens=output_tokens)
