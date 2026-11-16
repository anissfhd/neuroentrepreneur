"""Evaluation de l'accompagnement (D-81) : conversations completes, tour par tour.

Usage (PowerShell, depuis le dossier du projet) :
  .\\.venv\\Scripts\\python.exe scripts\\evaluate_discovery.py                    # faux modele
  .\\.venv\\Scripts\\python.exe scripts\\evaluate_discovery.py --real-api --budget-usd 0.15

Six profils (aucune idee, interets decouverts peu a peu, echec passe, idee precise,
informations donnees d'un coup, conseil immediat). Pour chaque tour, des controles qui ne
dependent pas du modele : une seule question, aucune liste pendant la decouverte, aucune
question repetee, aucune question sur un element deja connu, aucun plan premature, aucun
titre avant une idee, diagnostic qui progresse. La pertinence des questions et la qualite
des conseils se jugent a la LECTURE de la transcription produite (Markdown) ; en mode faux
modele, seule la logique du code est verifiee.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from neurocoach.agent.nodes import (  # noqa: E402
    LIST_MARKERS,
    SAVE_CLAIM,
    discovery_status,
)
from neurocoach.agent.schemas import ProjectBrief  # noqa: E402
from neurocoach.bootstrap import build_coach_runtime  # noqa: E402
from neurocoach.config import Settings  # noqa: E402
from neurocoach.domain.project_profile import extract_known  # noqa: E402


@dataclass(frozen=True)
class Scenario:
    key: str
    label: str
    messages: tuple[str, ...]
    # Etape attendue par tour (None : libre). Le premier tour est le plus contraint.
    stages: tuple[str | None, ...] = ()


SCENARIOS = (
    Scenario(
        "aucune_idee",
        "Aucune idée de départ",
        (
            "Bonjour, j'aimerais créer mon propre business, mais je ne sais pas par où "
            "commencer. Pouvez-vous m'aider ?",
            "Je ne sais vraiment pas, je n'ai aucune idée de domaine.",
            "J'aime bien cuisiner et recevoir des amis le week-end.",
            "Je travaille comme assistante administrative depuis cinq ans.",
            "Je voudrais un complément de revenu sans quitter mon emploi.",
        ),
        ("decouverte", "decouverte", "decouverte"),
    ),
    Scenario(
        "interets_progressifs",
        "Intérêts découverts peu à peu",
        (
            "Je voudrais me lancer mais je ne sais pas dans quoi.",
            "J'adore la photo et je fais beaucoup de randonnée.",
            "Je sais retoucher des images et je gère un compte de photos de paysages.",
            "Mon objectif serait d'en vivre à mi-temps d'ici deux ans.",
            "J'ai environ 10 heures par semaine et 500 € de côté.",
        ),
        ("decouverte", "decouverte"),
    ),
    Scenario(
        "echec_passe",
        "Un projet déjà tenté sans succès",
        (
            "J'ai déjà essayé de créer une boutique de vêtements en ligne il y a deux ans, ça "
            "n'a pas marché. Je voudrais retenter quelque chose, mais je ne sais pas quoi.",
            "Je n'avais presque pas de clients ; je crois que je n'avais pas vérifié la demande.",
            "Je suis plutôt bon en vente et en relation client.",
        ),
        ("decouverte",),
    ),
    Scenario(
        "idee_precise",
        "Une idée déjà précise",
        (
            "Je veux ouvrir un food truck de crêpes à Nantes l'été prochain. Par quoi dois-je "
            "commencer pour les autorisations ?",
            "J'ai 15 000 € d'économies et je peux y consacrer tout mon temps.",
        ),
        ("idee_precise",),
    ),
    Scenario(
        "infos_spontanees",
        "Plusieurs informations d'un coup",
        (
            "Je suis développeur web depuis huit ans, j'aime transmettre ce que je sais, j'ai "
            "six heures par semaine et 300 € de budget. Je veux un revenu complémentaire, mais "
            "je n'ai pas encore d'idée précise.",
            "Plutôt en ligne : je n'aime pas me déplacer.",
        ),
    ),
    Scenario(
        "conseil_immediat",
        "Conseil immédiat demandé",
        (
            "Je n'ai pas le temps pour un long questionnaire : donnez-moi directement un "
            "conseil pour démarrer une activité à côté de mon travail.",
        ),
        ("conseil_immediat",),
    ),
)

# Element deja connu -> mots d'une question qui le redemanderait (controle approximatif ;
# la lecture de la transcription reste la reference).
REASK = {
    "son temps disponible": re.compile(r"\b(temps|heures?|minutes?|disponib\w*)\b", re.I),
    "son budget": re.compile(r"\b(budget|€|euros?|investir)\b", re.I),
    "ses centres d'intérêt": re.compile(r"\b(passionne\w*|int[ée]resse\w*)\b", re.I),
    "ce qu'elle sait faire (compétences)": re.compile(r"\bcomp[ée]tences?\b", re.I),
    "ses essais passés de projet et ce qu'elle en a appris": re.compile(
        r"\b(d[ée]j[àa] (essay|tent)\w*)\b", re.I
    ),
}


# D-82 : meta-discours a eviter (recette du 12/11/2026 : « je n'émettrai aucun conseil »).
META = re.compile(
    r"(ne (donne|délivre|propose|fais) pas encore|n'[ée]mettrai aucun|je continue (le|mon) "
    r"diagnostic|pour l'instant je ne)",
    re.I,
)


@dataclass
class TurnReport:
    message: str
    stage: str | None
    reply: str
    question: str
    known: dict[str, Any]
    plan_proposed: bool
    calls: list[str]
    idea: str | None = None
    checks: dict[str, bool] = field(default_factory=dict)


# D-84 : un simple « Parfait. » ou « Merci, c'est utile. » ne tire rien de la reponse
# (simulations validees : une phrase qui dit ce que la reponse change pour la suite).
GENERIC_ONLY = re.compile(
    r"^\W*(?:parfait|merci|super|tr[eè]s bien|bien not[ée]|c'est not[ée]|d'accord)\b"
    r"[^.!?…]{0,45}[.!…]?\s*$",
    re.IGNORECASE,
)


def _norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def _similar(question: str, previous: list[str]) -> bool:
    """Question deja posee, meme reformulee (mots porteurs communs a 60 % ou plus)."""
    words = {w for w in _norm(question).split() if len(w) > 3}
    for other in previous:
        others = {w for w in other.split() if len(w) > 3}
        if words and others and len(words & others) / len(words | others) >= 0.6:
            return True
    return False


def play(runtime, scenario: Scenario) -> list[TurnReport]:
    agent = runtime.agent
    user = runtime.app.coach.register_user("Evaluation", "Decouverte", f"eval.{scenario.key}").id
    project = runtime.app.coach.start_project(user).id
    agent.greet(user, project)
    reports: list[TurnReport] = []
    asked: list[str] = []
    for index, text in enumerate(scenario.messages):
        config, _ = agent._session(user, project)
        before = agent.graph.get_state(config).values
        texts = [m["content"] for m in agent.history(user, project) if m["role"] == "user"]
        known_before = discovery_status(
            ProjectBrief(**(before.get("brief_draft") or {})), extract_known([*texts, text])
        )["deja_connu"]
        turn = agent.send_message(user, project, text)
        decision = turn.timings.get("decision") or {}
        after = agent.graph.get_state(config).values
        known = discovery_status(
            ProjectBrief(**(after.get("brief_draft") or {})), extract_known([*texts, text])
        )
        question = str(decision.get("question") or "")
        stage = decision.get("stage")
        reply = turn.reply or ""
        body = reply[: -len(question)].strip() if question and reply.endswith(question) else reply
        report = TurnReport(
            message=text, stage=stage, reply=reply, question=question,
            known=known["deja_connu"], plan_proposed=bool(turn.pending),
            calls=[c["task"] for c in turn.timings.get("calls", [])],
            idea=(after.get("brief_draft") or {}).get("idea_summary"),
        )  # fmt: skip
        expected = scenario.stages[index] if index < len(scenario.stages) else None
        reasked = [
            label for label, rx in REASK.items() if label in known_before and rx.search(question)
        ]
        report.checks = {
            "une_seule_question": reply.count("?") <= 1,
            "aucune_liste_en_decouverte": stage != "decouverte" or not LIST_MARKERS.search(body),
            "aucune_question_repetee": not question or not _similar(question, asked),
            "rien_de_deja_connu_redemande": not reasked,
            "aucun_plan_premature": not report.plan_proposed and "draft_plan" not in report.calls,
            "aucun_titre_sans_idee": known["idee_retenue"]
            or agent.title_suggestion(user, project) is None,
            # « idee precise » et « conseil immediat » sont deux aides directes.
            "etape_attendue": expected is None
            or stage == expected
            or {stage, expected} == {"idee_precise", "conseil_immediat"},
            # D-82 : une phrase au plus avant la question en decouverte, aucun meta-discours,
            # aucune annonce d'enregistrement, aucune piste avant un diagnostic complet.
            "reponse_courte_en_decouverte": stage != "decouverte"
            or len(re.findall(r"[.!…](\s|$)", body)) <= 1,
            "aucun_meta_discours": not META.search(reply),
            "aucune_fausse_sauvegarde": not SAVE_CLAIM.search(reply),
            "pistes_apres_diagnostic": "pistes_avant_diagnostic_complet"
            not in (decision.get("contract") or []),
            "reponse_du_modele": not turn.error,
            # D-84 (dossier V1) : comportement brut du modele, avant les corrections du code.
            "une_seule_intention_par_question": "question_double_coupee"
            not in (decision.get("contract") or []),
            "aucun_plan_non_demande": not (
                decision.get("chosen") == "preparer_plan"
                and decision.get("applied") != "preparer_plan"
            ),
            "transition_utile_en_decouverte": stage != "decouverte" or not GENERIC_ONLY.match(body),
        }
        if question:
            asked.append(_norm(question))
        reports.append(report)
    return reports


def transcript(results: dict[str, list[TurnReport]], mode: str) -> str:
    lines = [f"# Évaluation de l'accompagnement ({mode})", ""]
    for scenario in SCENARIOS:
        if scenario.key not in results:
            continue
        lines += [f"## {scenario.label}", ""]
        for n, turn in enumerate(results[scenario.key], 1):
            failed = [k for k, ok in turn.checks.items() if not ok]
            lines += [
                f"**Tour {n} — Utilisateur :** {turn.message}",
                "",
                f"**Coach ({turn.stage}) :** {turn.reply}",
                "",
                f"- Connu après ce tour : {', '.join(turn.known) or 'rien'}",
                f"- Idée retenue : {turn.idea or 'aucune'}",
                "- Contrôles : "
                + ("tous respectés" if not failed else "ÉCHEC " + ", ".join(failed)),
                "",
            ]
    return "\n".join(lines)


def run(runtime, only: tuple[str, ...] = ()) -> dict[str, list[TurnReport]]:
    return {s.key: play(runtime, s) for s in SCENARIOS if not only or s.key in only}


def summary(results: dict[str, list[TurnReport]]) -> tuple[int, int]:
    checks = [ok for turns in results.values() for t in turns for ok in t.checks.values()]
    return sum(checks), len(checks)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--real-api", action="store_true", help="appels réels PAYANTS")
    parser.add_argument("--budget-usd", type=float, help="plafond strict, obligatoire en réel")
    # D-86 : rejouer seulement les profils a reverifier (budget de campagne).
    parser.add_argument("--seulement", nargs="*", default=[], help="cles des profils a rejouer")
    args = parser.parse_args()
    with contextlib.suppress(AttributeError, ValueError):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    if args.real_api and not args.budget_usd:
        parser.error("--budget-usd est obligatoire avec --real-api")
    guard = None
    with tempfile.TemporaryDirectory() as tmp:
        if args.real_api:
            from neurocoach.agent.llm import build_role_providers
            from neurocoach.infra.clock import SystemClock

            settings = Settings.from_env()
            if settings.llm_provider == "fake":
                sys.exit("Fournisseur fake configuré : rien à évaluer en réel.")
            from neurocoach.agent.spending import SpendingCap

            # D-83 : meme registre que l'application (un seul budget pour toute la campagne).
            ledger = Path(os.environ.get("NEUROCOACH_SPENDING_LEDGER")
                          or ROOT / "data" / "evaluations" / "depenses.jsonl")  # fmt: skip
            guard = SpendingCap(
                build_role_providers(settings, today=SystemClock().now().date()),
                args.budget_usd,
                ledger,
            )
            print(f"Déjà dépensé dans ce registre : {guard.spent():.4f} $")
            runtime = build_coach_runtime(
                settings.model_copy(update={"data_dir": Path(tmp)}), llm=guard
            )
            mode = f"réel, {settings.llm_model}"
        else:
            runtime = build_coach_runtime(
                Settings(data_dir=Path(tmp), llm_provider="fake", research_simulation=True)
            )
            mode = "faux modèle : logique du code seulement, aucune qualité réelle"
        try:
            results = run(runtime, tuple(args.seulement))
        finally:
            runtime.checkpointer.conn.close()
    passed, total = summary(results)
    text = transcript(results, mode)
    out = ROOT / "data" / "evaluations"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = out / f"decouverte-{stamp}.md"
    path.write_text(text, encoding="utf-8")
    print(text)
    print(f"\nContrôles respectés : {passed}/{total}")
    if guard is not None:
        print(f"Total dépensé (registre) : {guard.spent():.4f} $ sur {args.budget_usd:.3f} $")
    print(f"Transcription : {path.relative_to(ROOT)}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
