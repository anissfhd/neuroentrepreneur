"""Mesure de la latence d'un tour de conversation (D-78), sans rien inventer.

Usage (PowerShell, depuis le dossier du projet) :
  .\\.venv\\Scripts\\python.exe scripts\\measure_latency.py            # hors ligne, faux modele
  .\\.venv\\Scripts\\python.exe scripts\\measure_latency.py --real-api # PAYANT : vrai modele

Hors ligne : le temps ajoute par le code (SQLite, construction du contexte, graphe LangGraph,
rendu serveur de l'interface) est mesure avec le faux modele, dont les appels sont instantanes.
En reel : la conversation de la recette manuelle du 11/11/2026 est rejouee sur une base
temporaire ; chaque appel au modele est chronometre, ainsi que le temps jusqu'au premier
fragment visible de la reponse et jusqu'a la reponse complete. Aucune recherche web n'est
lancee (aucun clic d'approbation). Le pire cas affiche borne la depense.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import statistics
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from neurocoach.bootstrap import build_coach_runtime  # noqa: E402
from neurocoach.config import Settings  # noqa: E402
from neurocoach.domain.errors import DomainError, ErrorCode  # noqa: E402

MESSAGES = [
    "Bonjour, j'aimerais créer mon propre business, mais je ne sais pas par où commencer. "
    "Pouvez-vous m'aider ?",
    "J'aimerais vendre des bougies artisanales parfumées, mais je n'ai aucune expérience.",
    "Mon projet est de fabriquer et vendre des bougies artisanales parfumées. Je connais donc "
    "déjà mon idée. Je suis débutant et j'ai besoin que vous me guidiez concrètement, étape par "
    "étape. Que me conseillez-vous de faire en premier ?",
]
# Pire cas par appel : 4 000 jetons de sortie a 2 $ / M et 8 000 jetons d'entree a 0,25 $ / M.
WORST_PER_CALL_USD = 4000 * 2.0 / 1e6 + 8000 * 0.25 / 1e6
# D-79 : un appel par message ordinaire (reponse, fiche et decision), plus la preparation du
# plan quand ses preconditions sont reunies.
CALLS_PER_MESSAGE = 2


def _turns(runtime, user: str, project: str) -> list[dict]:
    rows = []
    for text in MESSAGES:
        started = time.monotonic()
        first: list[float] = []
        streamed: list[str] = [""]

        def on_delta(partial: str, first=first, started=started, streamed=streamed) -> None:
            if not first:
                first.append(time.monotonic() - started)
            streamed[0] = partial  # texte diffuse du coach (meme si un plan suit)

        before = len(runtime.agent.history(user, project))
        turn = runtime.agent.send_message(user, project, text, stream=on_delta)
        new = runtime.agent.history(user, project)[before:]
        rows.append(
            {
                "message": text[:48],
                "total": turn.timings["total"],
                "first_visible": first[0] if first else None,
                "reply_complete": turn.timings.get("reply_complete"),
                "after_reply": turn.timings.get("after_reply"),
                "decision": turn.timings.get("decision"),
                "calls": turn.timings["calls"],
                "error": turn.error,
                "reply": turn.reply or "",
                "coach": [m["content"] for m in new if m["role"] == "assistant"],
                "plan": bool(turn.pending and turn.pending.get("kind") == "plan"),
            }
        )
    return rows


def offline() -> None:
    os.environ["NEUROCOACH_LLM_PROVIDER"] = "fake"
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(data_dir=Path(tmp))
        t0 = time.monotonic()
        runtime = build_coach_runtime(settings)
        build = time.monotonic() - t0
        try:
            user = runtime.app.coach.register_user("Mesure", "Hors Ligne", "mesure.offline").id
            project = runtime.app.coach.start_project(user).id
            runtime.agent.greet(user, project)
            reads = []
            for _ in range(20):
                t = time.monotonic()
                runtime.app.coach.get_snapshot(user, project)
                runtime.app.coach.get_progress(user, project)
                runtime.app.coach.get_next_actions(user, project)
                reads.append(time.monotonic() - t)
            rows = _turns(runtime, user, project)
        finally:
            runtime.checkpointer.conn.close()
    print("Hors ligne (faux modele, appels instantanes) :")
    print(f"- construction de l'application (demarrage) : {build * 1000:.0f} ms")
    print(f"- lectures SQLite d'un tour (fiche, progression, prochaine action) : "
          f"{statistics.median(reads) * 1000:.1f} ms (mediane de 20)")  # fmt: skip
    for row in rows:
        calls = ", ".join(c["task"] for c in row["calls"])
        print(f"- tour « {row['message']}… » : {row['total'] * 1000:.0f} ms au total "
              "(code : contexte, graphe LangGraph, points de sauvegarde) ; "
              f"appels : {calls}")  # fmt: skip
    _streamlit_render()


def _streamlit_render() -> None:
    """Rendu serveur de l'interface (AppTest) : premiere ouverture puis actualisation."""
    with contextlib.suppress(ImportError), tempfile.TemporaryDirectory() as tmp:
        from streamlit.testing.v1 import AppTest

        os.environ["NEUROCOACH_DATA_DIR"] = tmp
        app = AppTest.from_file(str(ROOT / "ui" / "app.py"), default_timeout=60)
        t = time.monotonic()
        app.run()
        cold = time.monotonic() - t
        t = time.monotonic()
        app.run()
        warm = time.monotonic() - t
        print(f"- interface (rendu serveur, sans navigateur) : premiere ouverture "
              f"{cold * 1000:.0f} ms, actualisation {warm * 1000:.0f} ms")  # fmt: skip
        import streamlit as st

        st.cache_resource.clear()


PRICE_INPUT, PRICE_OUTPUT = 0.25 / 1e6, 2.0 / 1e6  # gpt-5-mini, catalogue du 10/11/2026
MAX_OUTPUT_TOKENS = 8000  # plafond le plus haut configure (analyses) : pire cas prudent


class BudgetGuard:
    """Plafond strict : avant chaque appel, le pire cas est reserve ; apres l'appel, le cout
    reel (jetons comptes par OpenAI) remplace la reservation. Un appel qui pourrait depasser
    le plafond est refuse AVANT d'etre envoye (erreur explicite, aucune reponse inventee)."""

    def __init__(self, inner, limit_usd: float) -> None:
        self.inner, self.limit = inner, limit_usd
        self.spent = self.reserved = 0.0
        self.lock = threading.Lock()
        self.log: list[dict] = []

    def _worst(self, messages) -> float:
        chars = sum(len(m["content"]) for m in messages)
        return (chars / 2.5) * PRICE_INPUT + MAX_OUTPUT_TOKENS * PRICE_OUTPUT

    def _call(self, task, messages, run):
        from langchain_core.callbacks import get_usage_metadata_callback

        worst = self._worst(messages)
        with self.lock:
            if self.spent + self.reserved + worst > self.limit:
                self.log.append({"task": task, "refused": True})
                raise DomainError(ErrorCode.LLM_UNAVAILABLE, "plafond de la mesure atteint")
            self.reserved += worst
        cost, models = worst, []
        try:
            with get_usage_metadata_callback() as usage:
                result = run()
            tokens_in = sum(u.get("input_tokens", 0) for u in usage.usage_metadata.values())
            tokens_out = sum(u.get("output_tokens", 0) for u in usage.usage_metadata.values())
            models = list(usage.usage_metadata)
            if tokens_in or tokens_out:
                cost = tokens_in * PRICE_INPUT + tokens_out * PRICE_OUTPUT
            self.log.append({"task": task, "models": models, "input_tokens": tokens_in,
                             "output_tokens": tokens_out, "cost_usd": round(cost, 6)})  # fmt: skip
            return result
        finally:
            with self.lock:
                self.reserved -= worst
                self.spent += cost  # pire cas compte si l'appel echoue sans compte de jetons

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
        return self._call(task, messages, lambda: stream(task, messages, on_delta))

    def stream_structured(self, task, messages, schema, on_partial):
        stream = getattr(self.inner, "stream_structured", None)
        if stream is None:
            return self.generate_structured(task, messages, schema)
        return self._call(task, messages, lambda: stream(task, messages, schema, on_partial))


def real(budget_usd: float) -> None:
    from neurocoach.agent.llm import build_role_providers
    from neurocoach.infra.clock import SystemClock

    settings = Settings.from_env()
    if settings.llm_provider == "fake":
        sys.exit("Fournisseur fake configuré : rien à mesurer en réel.")
    print(f"Modèle configuré : {settings.llm_model} ; plafond strict : {budget_usd:.3f} $")
    today = SystemClock().now().date()
    guard = BudgetGuard(build_role_providers(settings, today=today), budget_usd)
    with tempfile.TemporaryDirectory() as tmp:
        runtime = build_coach_runtime(
            settings.model_copy(update={"data_dir": Path(tmp)}), llm=guard
        )
        try:
            user = runtime.app.coach.register_user("Mesure", "Reelle", "mesure.reelle").id
            project = runtime.app.coach.start_project(user).id
            runtime.agent.greet(user, project)
            rows = _turns(runtime, user, project)
        finally:
            runtime.checkpointer.conn.close()
    print(
        "\n| Message | Premier fragment visible | Réponse du coach complète | Traitements après "
        "la réponse | Total perçu | Décision (choisie → appliquée) | Appels (durée) |"
    )
    print("|---|---|---|---|---|---|---|")

    def sec(value):
        return f"{value:.1f} s" if value is not None else "—"

    for row in rows:
        calls = ", ".join(f"{c['task']} {c['seconds']:.1f} s" for c in row["calls"])
        decision = row["decision"] or {}
        choice = f"{decision.get('chosen', '—')} → {decision.get('applied', '—')}"
        print(f"| {row['message']}… | {sec(row['first_visible'])} "
              f"| {sec(row['reply_complete'])} | {sec(row['after_reply'])} "
              f"| {row['total']:.1f} s | {choice} | {calls} |")  # fmt: skip
    for index, row in enumerate(rows, 1):
        status = f"ERREUR {row['error']['code']}" if row["error"] else "ok"
        plan = " ; proposition de plan en attente de confirmation" if row["plan"] else ""
        print(f"\n=== Message {index} ({status}{plan}) : messages du coach dans le fil ===")
        for text in row["coach"]:
            print(f"---\n{text}")
    print("\nAppels facturés (jetons comptés par OpenAI) :")
    for entry in guard.log:
        print(f"- {json.dumps(entry, ensure_ascii=False)}")
    print(f"Coût réel total : {guard.spent:.4f} $ sur {budget_usd:.3f} $ autorisés")
    ledger = ROOT / "data" / "evaluations" / "latence-2026-11-11.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "at": datetime.now(UTC).isoformat(timespec="seconds"), "budget_usd": budget_usd,
            "spent_usd": round(guard.spent, 6), "calls": guard.log,
            "turns": [{k: v for k, v in r.items() if k not in ("reply", "coach")} for r in rows],
        }, ensure_ascii=False) + "\n")  # fmt: skip
    print(f"Registre : {ledger.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--real-api", action="store_true", help="appels réels PAYANTS")
    parser.add_argument("--budget-usd", type=float, help="plafond strict, obligatoire en réel")
    args = parser.parse_args()
    with contextlib.suppress(AttributeError, ValueError):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    if args.real_api and not args.budget_usd:
        parser.error("--budget-usd est obligatoire avec --real-api")
    real(args.budget_usd) if args.real_api else offline()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
