"""Finalisation (11/11/2026) : execution parallele sure, progression et budget.

Doublures LENTES simulees (attente fixe) : les durees mesurees ici montrent le gain du
parallelisme a latence egale ; elles ne pretendent pas mesurer les temps reels.
"""

from __future__ import annotations

import importlib.util
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

from factories import ALICE
from neurocoach.application.research_service import MissionRequest, ResearchService
from neurocoach.domain.analysis import ComparisonDraft, IdeaAnalysisDraft
from neurocoach.domain.research import ResearchCategory
from neurocoach.domain.solutions import SolutionsDraft
from neurocoach.infra.search_providers import build_research_registry
from neurocoach.research.fake import FakeResearchProvider
from neurocoach.research.ports import SearchResponse

C = ResearchCategory
ROOT = Path(__file__).resolve().parents[2]
DELAY = 0.2
IDEAS = ["Des bougies parfumées", "Un food truck de galettes", "Des cours de yoga",
         "Une application de covoiturage"]  # fmt: skip


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("connexion reseau tentee")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


class SlowProvider(FakeResearchProvider):
    """Fournisseur simule avec latence fixe ; compte les appels simultanes."""

    def __init__(self) -> None:
        super().__init__()
        self.active = 0
        self.peak = 0
        self.lock = threading.Lock()

    def search(self, *args, **kwargs) -> SearchResponse:
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(DELAY)
        try:
            return super().search(*args, **kwargs)
        finally:
            with self.lock:
                self.active -= 1


class SlowAnalyst:
    def __init__(self) -> None:
        self.calls: list[tuple[str, float]] = []
        self.lock = threading.Lock()

    def _wait(self, name: str) -> None:
        time.sleep(DELAY)
        with self.lock:
            self.calls.append((name, time.monotonic()))

    def analyze_idea(self, payload):
        self._wait(payload["idee"])
        return IdeaAnalysisDraft(summary=f"Analyse de {payload['idee']}.")

    def compare(self, payload):
        self._wait("comparaison")
        return ComparisonDraft(reasoning="Comparaison prudente.", confidence="faible")

    def propose_solutions(self, payload):
        self._wait(payload["probleme"]["label"])
        return SolutionsDraft(confidence="faible")


def service(app, parallelism: int, provider=None) -> ResearchService:
    provider = provider or SlowProvider()
    registry = build_research_registry(simulation=True, extra={"fake": provider})
    return ResearchService(app.database, app.clock, registry=registry, parallelism=parallelism)


def ready_mission(svc, project, **request):
    mission = svc.propose_mission(ALICE, MissionRequest(project_ids=[project.id], **request))
    svc.approve_mission(ALICE, mission.id, mission.scope_hash)
    return mission


@pytest.fixture
def project(app, alice):
    return app.coach.create_project(alice, "Choisir", "Vendre à Lyon")


# --- recherches web ---------------------------------------------------------------------------


def test_searches_run_in_parallel_with_the_same_results(app, project):
    sequential = service(app, 1)
    mission = ready_mission(sequential, project, ideas=IDEAS, categories=[C.PRICES, C.REVIEWS])
    start = time.monotonic()
    report_seq = sequential.run_mission(ALICE, mission.id)
    seq_time = time.monotonic() - start

    other = app.coach.create_project(ALICE, "Choisir bis", "Vendre à Lyon")
    provider = SlowProvider()
    parallel = service(app, 4, provider)
    mission2 = ready_mission(parallel, other, ideas=IDEAS, categories=[C.PRICES, C.REVIEWS])
    start = time.monotonic()
    report_par = parallel.run_mission(ALICE, mission2.id)
    par_time = time.monotonic() - start

    assert len(report_seq.queries) == len(report_par.queries) == 8
    assert sorted(q.text for q in report_seq.queries) == sorted(q.text for q in report_par.queries)
    assert len(report_seq.sources) == len(report_par.sources)
    assert provider.peak > 1  # appels reellement simultanes
    assert par_time < seq_time * 0.6, (seq_time, par_time)
    assert parallel.last_timings["recherches_web"] > 0


def test_parallel_searches_never_exceed_the_mission_budget(app, project):
    svc = service(app, 4)
    # 8 recherches prevues a 0,008 $ ; budget de 5 recherches exactement.
    mission = ready_mission(svc, project, ideas=IDEAS, categories=[C.PRICES, C.REVIEWS],
                            max_budget_usd=0.064)  # fmt: skip
    with app.database.transaction(write=True) as conn:
        conn.execute(
            "UPDATE research_missions SET scope_json = json_set(scope_json, "
            "'$.max_budget_usd', 0.04) WHERE id = ?",
            (mission.id,),
        )
    report = svc.run_mission(ALICE, mission.id)
    assert report.mission.queries_used == 5
    assert report.mission.spent_usd <= 0.04 + 1e-9
    assert report.not_run == 3


def test_first_query_of_each_provider_runs_alone(app, project):
    """Un quota epuise est detecte par la premiere requete avant d'envoyer les autres."""
    order: list[tuple[str, int]] = []

    class Probe(SlowProvider):
        def search(self, *args, **kwargs):
            order.append(("debut", self.active))
            return super().search(*args, **kwargs)

    provider = Probe()
    svc = service(app, 4, provider)
    mission = ready_mission(svc, project, ideas=IDEAS[:2], categories=[C.PRICES, C.REVIEWS])
    svc.run_mission(ALICE, mission.id)
    assert order[0] == ("debut", 0)
    assert order[1] == ("debut", 0)  # la sonde est terminee avant le lancement des autres


def test_progress_is_reported_from_the_calling_thread(app, project):
    svc = service(app, 4)
    mission = ready_mission(svc, project, ideas=IDEAS[:2], categories=[C.PRICES, C.REVIEWS])
    seen: list[tuple[bool, str]] = []
    svc.run_mission(ALICE, mission.id,
                    progress=lambda m: seen.append((threading.current_thread() is
                                                    threading.main_thread(), m)))  # fmt: skip
    assert [m for _, m in seen] == [f"Recherches web : {n}/4" for n in range(1, 5)]
    assert all(main for main, _ in seen)


# --- analyses et solutions ----------------------------------------------------------------


def test_ideas_are_analysed_in_parallel_and_kept_in_order(app, project):
    svc = service(app, 4)
    mission = ready_mission(svc, project, ideas=IDEAS, categories=[C.PRICES])
    svc.run_mission(ALICE, mission.id)
    analyst = SlowAnalyst()
    messages: list[str] = []
    start = time.monotonic()
    analysis = svc.analyze_mission(ALICE, mission.id, analyst, progress=messages.append)
    elapsed = time.monotonic() - start
    assert [i.idea for i in analysis.ideas] == IDEAS  # ordre conserve
    # 4 analyses en parallele puis la comparaison : environ 2 delais, pas 5.
    assert elapsed < DELAY * 3.5, elapsed
    assert analyst.calls[-1][0] == "comparaison"  # toujours apres toutes les analyses
    assert messages[0] == "Analyse de 4 idée(s) en cours"
    assert messages[-1] == "Synthèse et recommandation en cours"
    assert set(svc.last_timings) == {"analyses_idees", "synthese"}


def test_sequential_setting_keeps_the_original_behaviour(app, project):
    svc = service(app, 1)
    mission = ready_mission(svc, project, ideas=IDEAS[:2], categories=[C.PRICES])
    svc.run_mission(ALICE, mission.id)
    start = time.monotonic()
    svc.analyze_mission(ALICE, mission.id, SlowAnalyst())
    assert time.monotonic() - start >= DELAY * 3  # 2 analyses + 1 comparaison, a la suite


def test_problems_are_solved_in_parallel(coach):
    coach.app.research.registry = build_research_registry(
        simulation=True, extra={"fake": FakeResearchProvider()}
    )
    project = coach.app.coach.create_project(ALICE, "Galettes", "Vendre des galettes maison à Lyon")
    say = coach.agent.send_message
    say(ALICE, project.id, "Que disent les clients sur les forums et dans les avis ?")
    mission = coach.agent.research_pending(ALICE, project.id)
    coach.agent.approve_research(ALICE, project.id, mission.id, mission.scope_hash)
    say(ALICE, project.id, "analyse")
    say(ALICE, project.id, "Cherche des solutions")
    solutions = coach.agent.research_pending(ALICE, project.id)
    coach.app.research.approve_mission(ALICE, solutions.id, solutions.scope_hash)
    coach.app.research.run_mission(ALICE, solutions.id)
    analyst = SlowAnalyst()
    start = time.monotonic()
    plan = coach.app.research.solve_mission(ALICE, solutions.id, analyst)
    elapsed = time.monotonic() - start
    assert len(plan.problems) == len(solutions.scope.problems) == 3
    assert [p.problem.label for p in plan.problems] == [p.label for p in solutions.scope.problems]
    assert elapsed < DELAY * 2, elapsed  # 3 problemes en parallele


def test_an_error_stops_the_remaining_work(app, project):
    svc = service(app, 2)
    mission = ready_mission(svc, project, ideas=IDEAS, categories=[C.PRICES])
    svc.run_mission(ALICE, mission.id)

    class Stop(BaseException):
        pass

    class Failing(SlowAnalyst):
        def analyze_idea(self, payload):
            if payload["idee"] == IDEAS[0]:
                raise Stop()
            return super().analyze_idea(payload)

    analyst = Failing()
    with pytest.raises(Stop):
        svc.analyze_mission(ALICE, mission.id, analyst)
    assert len(analyst.calls) < len(IDEAS)  # appels non commences annules
    assert svc.latest_analysis(ALICE, mission.id) is None  # rien d'incomplet enregistre


# --- registre de depense des harnais sous concurrence --------------------------------------


def _evaluate():
    spec = importlib.util.spec_from_file_location(
        "evaluate_llm", ROOT / "scripts" / "evaluate_llm.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["evaluate_llm"] = module
    spec.loader.exec_module(module)
    return module


def test_concurrent_calls_never_exceed_the_budget():
    evaluate = _evaluate()

    class Inner:
        def generate_text(self, task, messages):
            time.sleep(0.05)
            return "ok"

    budget = evaluate.Budget(0.05, 0.25, 2.0, 4000, 100)  # pire cas ~0,008 $ par appel
    recorder = evaluate.RecordingProvider(Inner(), budget)
    stops: list[str] = []

    def call():
        try:
            recorder.generate_text("coach_reply", [{"role": "user", "content": "x"}])
        except evaluate.BudgetStop as stop:
            stops.append(str(stop))

    threads = [threading.Thread(target=call) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    # Sans releve d'usage, chaque appel est compte au pire cas : au plus 6 appels passent.
    assert budget.calls <= 6 and stops
    assert budget.spent_usd <= budget.limit_usd + 1e-9
    assert budget.in_flight_usd == pytest.approx(0.0)
