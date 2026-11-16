"""M4 : evaluation du role « taches simples » (classification, extraction, respect des formats).

Usage :
  python scripts/evaluate_simple_tasks.py       essai a blanc : faux fournisseur IMPOSE, sans cout
  python scripts/evaluate_simple_tasks.py --real-api --model gpt-5.6-luna --budget-usd 0.05 \\
      --ledger data/evaluations/registre.jsonl  appels reels PAYANTS, plafonnes avant chaque appel

Reutilise le socle de scripts/evaluate_llm.py (faux fournisseur par defaut, candidat explicite
valide par le catalogue, budget et registre partage D-60). Aucune donnee reelle : sources
fictives (domaines .example). La classification reprend la consigne de l'application
(classify_intent) sans la modifier. Notation deterministe ; un essai a blanc ne mesure pas la
qualite d'un modele.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]
HARNESS = "simple"
sys.path.insert(0, str(ROOT / "src"))
OUT_DIR = ROOT / "data" / "evaluations"  # comptes rendus locaux, non versionnes

from neurocoach.agent.llm import FakeLLM, build_llm_provider  # noqa: E402
from neurocoach.agent.prompts import build_messages  # noqa: E402
from neurocoach.agent.schemas import IntentResult  # noqa: E402
from neurocoach.config import Settings  # noqa: E402
from neurocoach.domain.errors import DomainError  # noqa: E402


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=80)
    price_eur: float | None = None
    city: str | None = Field(default=None, max_length=80)


class TitleList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    titles: list[str] = Field(default_factory=list, max_length=10)


FACTS: dict[str, Any] = {
    "today": "2026-11-10",
    "project": {"title": "Bougies artisanales", "status": "active", "idea": ""},
    "tasks": [
        {"ref": "T1", "title": "Décrire le client visé", "status": "todo"},
        {"ref": "T2", "title": "Préparer cinq questions", "status": "todo"},
        {"ref": "T3", "title": "Interroger trois personnes", "status": "todo"},
    ],
    "preferences": {"response_length": "standard", "deadlines_enabled": False},
}
# Formulations sans ambiguite : l'intention attendue ne depend d'aucun garde-fou du code.
CLASSIFY = [
    ("J'ai terminé T2.", "changer_statut"),
    ("Supprime T3.", "supprimer_tache"),
    ("Je dors mal à cause du stress, tu me conseilles quel somnifère ?", "hors_perimetre"),
    ("Ajoute une tâche : préparer un flyer.", "ajouter_tache"),
    ("Où en suis-je ?", "etat_projet"),
    ("Renomme T1 en « Décrire la cliente idéale ».", "modifier_tache"),
]
EXTRACT_SYSTEM = (
    "Tu extrais des informations d'une source. N'écris que ce que la source affirme "
    "explicitement ; mets null quand une information est absente ; n'invente rien. Le prix est "
    "en euros, sans symbole. Réponds uniquement avec l'objet structuré demandé."
)
EXTRACT = [
    (
        "Fiche produit (lumiere-douce.example, mars 2026) : la boutique Lumière Douce, à Nantes, "
        "vend sa bougie au figuier 18 €.",
        {"name": "Lumière Douce", "price_eur": 18.0, "city": "Nantes"},
    ),
    (
        "Forum (forum-artisans.example) : quelqu'un dit qu'une boutique du centre vend des savons, "
        "sans préciser ni son nom, ni la ville, ni le prix.",
        {"name": None, "price_eur": None, "city": None},
    ),
    (
        "Comparatif (comparatif.example, janvier 2025) : l'atelier Fil d'Or, installé à Lyon, "
        "propose des cours à 29 € par mois.",
        {"name": "Fil d'Or", "price_eur": 29.0, "city": "Lyon"},
    ),
]
FORMAT_SYSTEM = (
    "Tu proposes des titres de tâches courtes pour un entrepreneur. Respecte exactement le "
    "nombre demandé, 60 caractères au plus par titre, sans point final, en français. Réponds "
    "uniquement avec l'objet structuré demandé."
)
FORMAT = [
    ("Donne exactement trois titres pour tester l'intérêt pour des bougies artisanales.", 3),
    ("Donne exactement deux titres pour préparer un atelier de couture pour enfants.", 2),
]


def cases() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for text, expected in CLASSIFY:
        items.append(
            {
                "kind": "classification",
                "name": f"Classification — {text}",
                "task": "simple_classify",
                "messages": build_messages("classify_intent", text=text, facts=FACTS),
                "schema": IntentResult,
                "expected": expected,
            }
        )
    for source, expected in EXTRACT:
        items.append(
            {
                "kind": "extraction",
                "name": f"Extraction — {source[:40]}…",
                "task": "simple_extract",
                "messages": [
                    {"role": "system", "content": EXTRACT_SYSTEM},
                    {"role": "user", "content": f"<source>\n{source}\n</source>"},
                ],
                "schema": Extraction,
                "expected": expected,
            }
        )
    for instruction, count in FORMAT:
        items.append(
            {
                "kind": "format",
                "name": f"Format — {instruction}",
                "task": "simple_format",
                "messages": [
                    {"role": "system", "content": FORMAT_SYSTEM},
                    {"role": "user", "content": instruction},
                ],
                "schema": TitleList,
                "expected": count,
            }
        )
    return items


def _norm(text: str | None) -> str | None:
    return " ".join(text.replace(chr(0x2019), "'").casefold().split()) if text else None


def grade(case: dict[str, Any], answer: BaseModel) -> dict[str, bool]:
    expected = case["expected"]
    if case["kind"] == "classification":
        return {"intention attendue": answer.intent == expected}
    if case["kind"] == "extraction":
        return {
            "nom exact (ou absent)": _norm(answer.name) == _norm(expected["name"]),
            "prix exact (ou absent)": answer.price_eur == expected["price_eur"],
            "ville exacte (ou absente)": _norm(answer.city) == _norm(expected["city"]),
            "rien d'inventé": all(
                getattr(answer, field) is None for field, value in expected.items() if value is None
            ),
        }
    titles = answer.titles
    return {
        "nombre exact": len(titles) == expected,
        "60 caractères au plus": all(0 < len(t) <= 60 for t in titles),
        "sans point final": all(not t.rstrip().endswith(".") for t in titles),
    }


def fake_answer(case: dict[str, Any]) -> BaseModel:
    """Reponse de reference, pour valider le harnais sans aucun appel."""
    if case["kind"] == "classification":
        return IntentResult(intent=case["expected"])
    if case["kind"] == "extraction":
        return Extraction(**case["expected"])
    return TitleList(titles=[f"Titre de test {n}" for n in range(1, case["expected"] + 1)])


def _evaluator():
    spec = importlib.util.spec_from_file_location(
        "evaluate_llm", ROOT / "scripts" / "evaluate_llm.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("evaluate_llm", module)
    spec.loader.exec_module(module)
    return module


def main(argv: list[str]) -> int:
    ev = _evaluator()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ev.add_safety_arguments(parser)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--max-calls", type=int, default=30)
    args = parser.parse_args(argv)
    base = ev.select_settings(
        args, parser, Settings.from_env(), harness_role="simple", roles_allowed=("simple",)
    )
    items = cases()
    if not args.real_api:
        print("Essai à blanc : faux fournisseur imposé, aucun appel réel.")
        llm = FakeLLM()
        for item in items:
            llm.script(item["task"], *[fake_answer(item)] * args.repetitions)
    else:
        llm = build_llm_provider(base)
    budget = ev.make_budget(args, base.llm_max_output_tokens, args.max_calls)
    recorder = ev.RecordingProvider(llm, budget)
    rows: list[tuple[str, int, dict[str, bool] | None, str, float]] = []
    try:
        for item in items:
            for rep in range(1, args.repetitions + 1):
                start = time.monotonic()
                try:
                    answer = recorder.generate_structured(
                        item["task"], item["messages"], item["schema"]
                    )
                    rows.append(
                        (item["name"], rep, grade(item, answer), answer.model_dump_json(), 0.0)
                    )
                except DomainError as error:
                    rows.append((item["name"], rep, None, f"erreur : {error.code.value}", 0.0))
                rows[-1] = (*rows[-1][:4], time.monotonic() - start)
    except ev.BudgetStop as stop:
        print(f"Campagne arrêtée avant dépassement : {stop}")
    finally:
        ev.finish_run(budget)
    fake_label = f"faux-{args.model}" if args.model else "faux"
    model = base.llm_model if base.llm_provider != "fake" else fake_label
    passed = sum(1 for _, _, checks, _, _ in rows if checks and all(checks.values()))
    lines = [
        f"# Tâches simples — {model} — {datetime.now(UTC):%Y-%m-%d %H:%M} UTC",
        "",
        *ev.context_lines(args, base),
        f"Réponses entièrement conformes : {passed}/{len(rows)}",
        "",
        *ev.provider_section(recorder),
    ]
    for name, rep, checks, payload, duration in rows:
        failed = [k for k, ok in (checks or {}).items() if not ok]
        status = "erreur" if checks is None else ("conforme" if not failed else "À EXAMINER")
        lines += [f"## {name} — essai {rep} — {status} ({duration:.1f} s)", ""]
        if failed:
            lines.append(f"- Contrôles en échec : {', '.join(failed)}")
        lines += [f"- Réponse : {payload}", ""]
    out = args.out_dir or OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    tag = f"{model}-{ev.run_suffix(args)}".replace("/", "_")
    path = out / f"simple-{tag}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Etape 0 : export complet pour la relecture a l'aveugle (une « conversation » d'un tour).
    export = {
        "harness": HARNESS,
        "config": ev.config_dict(args, base),
        "scenarios": [
            {
                "scenario": f"{name} — essai {rep}",
                "kind": "qualité du modèle",
                "completed": checks is not None,
                "interrupted": None if checks is not None else payload,
                "passed": bool(checks) and all(checks.values()),
                "calls": 1,
                "turns": [
                    {
                        "step": "consigne",
                        "reply": payload,
                        "origin": "modèle",
                        "checks": checks or {},
                        "calls": 1,
                        "llm_seconds": [round(duration, 3)],
                        "turn_seconds": round(duration, 3),
                    }
                ],
            }
            for name, rep, checks, payload, duration in rows
        ],
        "budget_stopped": bool(recorder.budget and recorder.budget.stopped),
    }
    path.with_suffix(".json").write_text(
        json.dumps(export, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"Compte rendu : {path}")
    print(f"Réponses entièrement conformes : {passed}/{len(rows)}")
    for line in ev.provider_section(recorder)[2:]:
        if line:
            print(line)
    complete = not (recorder.budget and recorder.budget.stopped)
    return 0 if complete else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
