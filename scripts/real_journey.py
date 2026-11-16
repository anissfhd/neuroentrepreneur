"""Recette reelle du parcours R1 a R6 sur un projet FICTIF (recherches et modele reels).

Etapes : question de marche et d'avis -> proposition de mission -> « oui » ecrit (sans effet)
-> approbation -> analyse -> question de suivi -> recherche de solutions -> approbation ->
question de suivi -> proposition de taches -> confirmation -> memoire du projet.

Securite : les appels au modele passent par le registre de depense des harnais (reservation
au pire cas, plafond de campagne) ; les recherches passent par les gardes de l'application
(mission approuvee, budget de mission, plafonds mensuels gratuits). Donnees dans un dossier
temporaire ; compte rendu local (data/evaluations, non versionne) ; aucune cle affichee.

Usage (payant, sur accord explicite seulement) :
  python scripts/real_journey.py --real-api --model gpt-5-mini --budget-usd 0.08 \\
      --campaign-cap-usd 0.16 --ledger data/evaluations/recette-2026-11-10.jsonl
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT_DIR = ROOT / "data" / "evaluations"

from neurocoach.agent.llm import build_llm_provider  # noqa: E402
from neurocoach.agent.research_dialogue import RESEARCH_WITH_BUTTON  # noqa: E402
from neurocoach.application.formatting import OUT_OF_SCOPE_MESSAGE  # noqa: E402
from neurocoach.bootstrap import build_coach_runtime  # noqa: E402
from neurocoach.config import Settings  # noqa: E402

USER = "usr_" + "f" * 32
IDEA = (
    "Je veux vendre des bougies artisanales parfumées à Lyon, sur les marchés et en ligne. "
    "J'ai un budget de 500 € et environ 6 heures par semaine."
)


def _evaluator() -> Any:
    spec = importlib.util.spec_from_file_location(
        "evaluate_llm", ROOT / "scripts" / "evaluate_llm.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["evaluate_llm"] = module
    spec.loader.exec_module(module)
    return module


class Journey:
    def __init__(self, runtime: Any, recorder: Any) -> None:
        self.rt = runtime
        self.recorder = recorder
        self.project = runtime.app.coach.create_project(USER, "Bougies artisanales (test)", IDEA)
        self.lines: list[str] = []
        self.checks: list[tuple[str, bool, str]] = []
        self.timings: list[tuple[str, float]] = []  # (etape, secondes) mesurees

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append((name, bool(ok), detail))
        return bool(ok)

    def log(self, who: str, text: str | None) -> None:
        self.lines += [f"**{who}** :", "", (text or "(aucune réponse)").strip(), ""]

    def _progress(self, start: float, steps: list[str]) -> Any:
        def record(message: str) -> None:
            steps.append(f"{time.monotonic() - start:5.1f} s — {message}")

        return record

    def say(self, text: str) -> Any:
        calls = len(self.recorder.calls)
        start = time.monotonic()
        steps: list[str] = []
        turn = self.rt.agent.send_message(
            USER, self.project.id, text, progress=self._progress(start, steps)
        )
        elapsed = time.monotonic() - start
        self.timings.append((f"Message « {text[:40]} »", elapsed))
        self.log("Utilisateur", text)
        self.log(f"Coach ({len(self.recorder.calls) - calls} appel(s) au modèle, "
                 f"{elapsed:.0f} s)", turn.reply or turn.notice)  # fmt: skip
        if steps:
            self.lines += ["Étapes mesurées :", "", *[f"- {s}" for s in steps], ""]
        return turn

    def approve(self) -> Any:
        mission = self.rt.agent.research_pending(USER, self.project.id)
        if mission is None:
            return None
        start = time.monotonic()
        steps: list[str] = []
        turn = self.rt.agent.approve_research(
            USER, self.project.id, mission.id, mission.scope_hash,
            progress=self._progress(start, steps),
        )  # fmt: skip
        elapsed = time.monotonic() - start
        self.timings.append((f"Clic « Approuver et lancer » ({mission.scope.purpose})", elapsed))
        self.log(f"Clic « Approuver et lancer » ({elapsed:.0f} s)", turn.reply)
        if steps:
            self.lines += ["Étapes mesurées :", "", *[f"- {s}" for s in steps], ""]
        return mission


def run(journey: Journey) -> None:
    app, agent, pid = journey.rt.app, journey.rt.agent, journey.project.id
    first = journey.say(
        "Que disent les clients des bougies artisanales dans les avis et sur les forums ? "
        "Et qui sont les concurrents ?"
    )
    pending = agent.research_pending(USER, pid)
    journey.check("R3 mission proposée", pending is not None and "Approuver et lancer" in
                  (first.reply or ""))  # fmt: skip
    if pending is None:
        return
    journey.check("R2 mission réelle (pas simulée)", not pending.simulated,
                  ", ".join(pending.scope.providers))  # fmt: skip
    yes = journey.say("oui")
    journey.check("Consentement : « oui » écrit sans effet", yes.notice == RESEARCH_WITH_BUTTON
                  and not app.research.mission_report(USER, pending.id).queries)  # fmt: skip
    journey.approve()
    report = app.research.mission_report(USER, pending.id)
    done = [q for q in report.queries if q.status == "done"]
    journey.check(
        "R1/R2 recherches réelles faites",
        len(done) == len(report.queries) > 0,
        f"{len(done)}/{len(report.queries)} ; {len(report.sources)} sources",
    )
    journey.check("R5 aucun site exclu stocké", not any(
        ("reddit" in s.domain or "trustpilot" in s.domain) for s in report.sources),
        f"{sum(q.blocked_count for q in report.queries)} résultat(s) écarté(s)")  # fmt: skip
    analysis_turn = journey.say("analyse")
    analysis = app.research.latest_analysis(USER, pending.id)
    journey.check("R4 analyse produite", analysis is not None and all(
        i.available for i in analysis.ideas), (analysis_turn.reply or "")[:80])  # fmt: skip
    if analysis is not None:
        journey.check("R4 retraits par le code (contrôle actif)", True,
                      f"{analysis.removed_count} retrait(s)")  # fmt: skip
        journey.check(
            "R5 voix des clients calculée",
            analysis.ideas[0].voice is not None
            and bool(analysis.ideas[0].voice.themes or analysis.ideas[0].voice.notes),
        )
    follow = journey.say(
        "Quelle est la principale frustration des clients, et est-ce une tendance ou un "
        "témoignage isolé ?"
    )
    journey.check(
        "Suivi : réponse appuyée sur l'analyse",
        bool(follow.reply) and OUT_OF_SCOPE_MESSAGE not in follow.reply,
    )
    solve_turn = journey.say("Cherche des solutions à ces problèmes")
    solutions_mission = agent.research_pending(USER, pid)
    journey.check(
        "R6 mission de solutions proposée",
        solutions_mission is not None and solutions_mission.scope.purpose == "solutions",
        (solve_turn.reply or "")[:80],
    )
    if solutions_mission is None:
        return
    journey.approve()
    plan = app.research.latest_solutions(USER, solutions_mission.id)
    journey.check("R6 solutions produites", plan is not None and any(
        p.options for p in plan.problems), "")  # fmt: skip
    before = len(app.coach.list_tasks(USER, pid))
    tasks_turn = journey.say("Transforme ces actions en tâches")
    proposal = tasks_turn.pending
    journey.check("Tâches proposées, rien écrit avant confirmation", proposal is not None and
                  len(app.coach.list_tasks(USER, pid)) == before)  # fmt: skip
    if proposal is not None:
        agent.decide(USER, pid, proposal["pending_action_id"], "confirm")
        journey.log("Clic « Confirmer »", f"{len(app.coach.list_tasks(USER, pid))} tâche(s)")
        journey.check("Tâches créées après confirmation",
                      len(app.coach.list_tasks(USER, pid)) > before)  # fmt: skip
    advice = journey.say("Laquelle de ces solutions me conseillez-vous, avec mon budget ?")
    # Recette du 11/11/2026 : un refus « hors périmètre » passait ce contrôle.
    journey.check(
        "Suivi : réponse appuyée sur les solutions",
        bool(advice.reply) and OUT_OF_SCOPE_MESSAGE not in advice.reply,
    )
    status = journey.say("Où en suis-je ?")
    journey.check("Mémoire : état du projet", "Prochaine" in (status.reply or "") or
                  "T1" in (status.reply or ""))  # fmt: skip


def main(argv: list[str]) -> int:
    ev = _evaluator()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ev.add_safety_arguments(parser)
    parser.add_argument("--max-calls", type=int, default=30)
    args = parser.parse_args(argv)
    if not args.real_api:
        parser.error("recette réelle uniquement : --real-api requis (sur accord explicite)")
    base = ev.select_settings(
        args, parser, Settings.from_env(), harness_role="coaching", roles_allowed=("coaching",)
    )
    budget = ev.make_budget(args, base.llm_max_output_tokens, args.max_calls)
    recorder = ev.RecordingProvider(
        build_llm_provider(base), budget, long_output_tokens=base.llm_max_output_tokens_analysis
    )
    with tempfile.TemporaryDirectory() as tmp:
        settings = base.model_copy(update={"data_dir": Path(tmp), "research_simulation": False})
        runtime = build_coach_runtime(settings, llm=recorder)
        runtime.app.coach.ensure_user(USER, "Personne fictive")
        journey = Journey(runtime, recorder)
        try:
            run(journey)
        except ev.BudgetStop as stop:
            journey.check("Budget respecté (arrêt avant dépassement)", True, str(stop))
        finally:
            ev.finish_run(budget)
        usage = runtime.app.research.availability()
        runtime.checkpointer.conn.close()
    passed = sum(ok for _, ok, _ in journey.checks)
    lines = [
        f"# Recette réelle R1 à R6 — {base.llm_model} — {datetime.now(UTC):%Y-%m-%d %H:%M} UTC",
        "",
        "Projet fictif ; recherches Tavily et Exa réelles ; modèle réel.",
        "",
        f"Vérifications réussies : {passed}/{len(journey.checks)}",
        "",
        *[f"- {'OK' if ok else 'ÉCHEC'} — {name}" + (f" ({detail})" if detail else "")
          for name, ok, detail in journey.checks],
        "",
        "## Temps mesurés",
        "",
        *[f"- {name} : {seconds:.0f} s" for name, seconds in journey.timings],
        "",
        *ev.provider_section(recorder),
        "## Recherches (compteur de l'application, ce processus)",
        "",
        *[f"- {s['label']} : {s['queries']} requête(s), {s['used_usd']:.3f} $ de quota gratuit"
          for s in usage["services"]],
        "",
        "## Conversation",
        "",
        *journey.lines,
    ]  # fmt: skip
    out = args.out_dir or OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"journey-{base.llm_model}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Vérifications réussies : {passed}/{len(journey.checks)}")
    for name, ok, detail in journey.checks:
        print(f"- {'OK' if ok else 'ÉCHEC'} — {name}" + (f" ({detail})" if detail else ""))
    for name, seconds in journey.timings:
        print(f"{seconds:6.0f} s — {name}")
    print("\n".join(ev.provider_section(recorder)))
    for s in usage["services"]:
        print(f"{s['label']} : {s['queries']} requête(s), {s['used_usd']:.3f} $ de quota gratuit")
    print(f"Compte rendu : {path.relative_to(ROOT)}")
    return 0 if passed == len(journey.checks) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
