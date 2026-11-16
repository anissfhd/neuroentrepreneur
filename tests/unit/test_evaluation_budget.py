"""Garde-fou budgetaire des dialogues reels : l'arret a lieu AVANT un appel qui pourrait
faire depasser le budget, jamais apres (verifie sans reseau)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from neurocoach.domain.errors import DomainError, ErrorCode

ROOT = Path(__file__).resolve().parents[2]


def _evaluate():
    spec = importlib.util.spec_from_file_location(
        "evaluate_llm", ROOT / "scripts" / "evaluate_llm.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["evaluate_llm"] = module
    spec.loader.exec_module(module)
    return module


class _Inner:
    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def generate_text(self, task, messages):
        self.calls += 1
        if self.fail:
            raise DomainError(ErrorCode.LLM_UNAVAILABLE) from TimeoutError()
        return "ok"


def _budget(evaluate, limit, max_calls=100):
    # 4 000 jetons de sortie a 2 $ par million : 0,008 $ de pire cas en sortie par appel.
    return evaluate.Budget(limit, 0.25, 2.0, 4000, max_calls)


def test_the_call_that_could_exceed_the_budget_is_never_sent():
    evaluate = _evaluate()
    inner = _Inner(fail=True)
    recorder = evaluate.RecordingProvider(inner, _budget(evaluate, 0.02))
    messages = [{"role": "user", "content": "x" * 1000}]
    for _ in range(2):  # sans releve d'usage, chaque appel est compte au pire cas
        with pytest.raises(DomainError):
            recorder.generate_text("respond", messages)
    with pytest.raises(evaluate.BudgetStop):
        recorder.generate_text("respond", messages)
    assert inner.calls == 2
    budget = recorder.budget
    assert budget.worst_case_charges == 2
    assert budget.spent_usd <= budget.limit_usd
    assert "budget" in budget.stopped


def test_call_ceiling_stops_the_campaign():
    evaluate = _evaluate()
    inner = _Inner()
    recorder = evaluate.RecordingProvider(inner, _budget(evaluate, 100, max_calls=3))
    for _ in range(3):
        recorder.generate_text("respond", [{"role": "user", "content": "x"}])
    with pytest.raises(evaluate.BudgetStop):
        recorder.generate_text("respond", [{"role": "user", "content": "x"}])
    assert inner.calls == 3
    assert recorder.budget.stopped == "plafond de 3 appels atteint"


def test_budget_stop_is_not_caught_by_generic_handlers():
    evaluate = _evaluate()
    assert not issubclass(evaluate.BudgetStop, Exception)


def test_cost_uses_the_given_prices():
    evaluate = _evaluate()
    budget = _budget(evaluate, 2)
    assert budget.cost(1_000_000, 0) == pytest.approx(0.25)
    assert budget.cost(0, 1_000_000) == pytest.approx(2.0)


def test_dry_run_scenarios_start_as_planned_and_pass(tmp_path):
    """Constat de la premiere campagne : un scenario « projet actif » avait demarre sans plan."""
    from neurocoach.agent.llm import FakeLLM
    from neurocoach.bootstrap import build_coach_runtime
    from neurocoach.config import Settings

    evaluate = _evaluate()
    runtime = build_coach_runtime(Settings(data_dir=tmp_path), llm=FakeLLM())
    runtime.app.coach.ensure_user(evaluate.USER, "Évaluation")
    try:
        results = [evaluate.run_scenario(runtime, *scenario) for scenario in evaluate.SCENARIOS]
    finally:
        runtime.checkpointer.conn.close()
    assert len(results) == len(evaluate.SCENARIOS) == 36
    setups = {name: setup for name, setup, _ in evaluate.SCENARIOS}
    for result in results:
        assert result.setup == evaluate.SETUPS[setups[result.name]]
        assert result.passed, (result.name, [t.checks for t in result.turns])
    # « oui » n'est ecrit qu'apres verification qu'une proposition attend (constat campagne 2).
    yes = next(r for r in results if r.name == "« Oui » écrit au lieu du bouton")
    check = next(t for t in yes.turns if t.step == "vérification")
    assert check.checks == {"proposition en attente avant la suite": True}
    # Les echeances activees pour un scenario sont retablies ensuite.
    assert runtime_prefs_restored(tmp_path, evaluate)


def test_a_scenario_starting_in_the_wrong_state_stops_the_campaign(tmp_path):
    from neurocoach.agent.llm import FakeLLM
    from neurocoach.bootstrap import build_coach_runtime
    from neurocoach.config import Settings

    evaluate = _evaluate()
    runtime = build_coach_runtime(Settings(data_dir=tmp_path), llm=FakeLLM())
    runtime.app.coach.ensure_user(evaluate.USER, "Évaluation")
    try:
        project = runtime.app.coach.create_project(evaluate.USER, "Vide")
        with pytest.raises(RuntimeError, match="non conforme"):
            evaluate.check_start(runtime.app, runtime.agent, project.id, "Vide", "plan")
    finally:
        runtime.checkpointer.conn.close()


def runtime_prefs_restored(tmp_path, evaluate) -> bool:
    from neurocoach.bootstrap import build_application
    from neurocoach.config import Settings

    app = build_application(Settings(data_dir=tmp_path))
    return app.coach.get_preferences(evaluate.USER).deadlines_enabled is False


def test_ensure_pending_is_marked_when_no_proposal_waits(tmp_path):
    """Si aucune proposition n'attend malgre la relance, le scenario est signale non probant."""
    from neurocoach.agent.llm import FakeLLM
    from neurocoach.agent.schemas import IntentResult
    from neurocoach.bootstrap import build_coach_runtime
    from neurocoach.config import Settings

    evaluate = _evaluate()
    llm = FakeLLM().script("classify_intent", IntentResult(intent="aide"))
    runtime = build_coach_runtime(Settings(data_dir=tmp_path), llm=llm)
    runtime.app.coach.ensure_user(evaluate.USER, "Évaluation")
    try:
        result = evaluate.run_scenario(runtime, "Essai", "vide", [("ensure_pending", "Bonjour.")])
    finally:
        runtime.checkpointer.conn.close()
    assert result.turns[-1].checks == {"proposition en attente avant la suite": False}
    assert not result.passed


def test_each_scenario_has_its_own_project_idea(tmp_path):
    """Constat de la campagne finale : l'idee du dialogue de reference etait reprise partout."""
    evaluate = _evaluate()
    garage = evaluate.PROJECTS["Formulation imprévue"]
    assert garage == ("Bougies du garage", "")
    assert all(idea == "" for _, idea in evaluate.PROJECTS.values())
    assert evaluate.PLANNED_PROJECT[1] == evaluate.VAGUE  # coherent avec le plan de reference


def test_saved_state_flags_a_stored_date_when_deadlines_are_disabled(tmp_path):
    from datetime import timedelta

    from neurocoach.bootstrap import build_application
    from neurocoach.config import Settings
    from neurocoach.domain.models import ActionType
    from neurocoach.domain.plans import ChangeCommand, TaskChanges, UpdateTask

    evaluate = _evaluate()
    app = build_application(Settings(data_dir=tmp_path))
    app.coach.ensure_user(evaluate.USER, "Évaluation")
    project = app.coach.create_project(evaluate.USER, "Bougies", evaluate.VAGUE)
    evaluate.prepare(app, project.id, "plan")
    assert all(evaluate.saved_state(app, project.id).checks.values())
    app.coach.update_preferences(evaluate.USER, deadlines_enabled=True)
    task = app.coach.list_tasks(evaluate.USER, project.id)[0]
    day = project.created_at.date() + timedelta(days=3)
    command = ChangeCommand(
        operations=[UpdateTask(task_id=task.id, changes=TaskChanges(due_date=day))]
    )
    action = app.actions.request_change(evaluate.USER, project.id, ActionType.TASK_UPDATE, command)
    app.actions.confirm(evaluate.USER, action.id)
    app.coach.update_preferences(evaluate.USER, deadlines_enabled=False)
    checks = evaluate.saved_state(app, project.id).checks
    assert checks["aucune échéance enregistrée (désactivées)"] is False


def test_long_tasks_reserve_their_own_higher_worst_case():
    """Recette du 10/11/2026 : les analyses ont un plafond de sortie plus eleve ; le pire cas
    reserve avant l'appel doit le refleter, sans changer celui des autres taches."""
    evaluate = _evaluate()
    inner = _Inner(fail=True)  # sans releve : chaque appel est compte a son pire cas
    recorder = evaluate.RecordingProvider(inner, _budget(evaluate, 1.0), long_output_tokens=8000)
    messages = [{"role": "user", "content": "x" * 1000}]
    with pytest.raises(DomainError):
        recorder.generate_text("coach_reply", messages)
    short = recorder.budget.spent_usd
    with pytest.raises(DomainError):
        recorder.generate_text("research_analysis", messages)
    long = recorder.budget.spent_usd - short
    assert long - short == pytest.approx(4000 * 2.0 / 1e6)  # 8 000 jetons au lieu de 4 000
    assert recorder.budget.max_output_tokens == 4000  # plafond habituel retabli


def test_a_long_task_is_refused_when_its_worst_case_exceeds_the_budget():
    evaluate = _evaluate()
    inner = _Inner()
    recorder = evaluate.RecordingProvider(inner, _budget(evaluate, 0.012), long_output_tokens=8000)
    messages = [{"role": "user", "content": "x" * 100}]
    with pytest.raises(evaluate.BudgetStop):
        recorder.generate_text("research_solutions", messages)
    assert inner.calls == 0
    # Le meme budget accepte une tache courte (pire cas 0,008 $ au lieu de 0,016 $).
    short = evaluate.RecordingProvider(inner, _budget(evaluate, 0.012), long_output_tokens=8000)
    assert short.generate_text("coach_reply", messages) == "ok"
