"""Fixtures communes : base SQLite temporaire, horloge fixe, utilisateurs fictifs."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from factories import ALICE, BRUNO, NOW, RecordingConversationStore, sample_plan
from neurocoach.bootstrap import Application, build_application
from neurocoach.config import Settings
from neurocoach.domain.models import Project, Task
from neurocoach.infra.clock import FixedClock


@pytest.fixture(autouse=True)
def _never_a_paid_provider(request, monkeypatch):
    """Un .env local configure pour un vrai fournisseur ne doit jamais rendre un test payant :
    hors du marqueur ``real_llm``, le faux fournisseur est impose (environnement prioritaire)."""
    if request.node.get_closest_marker("real_llm") is None:
        monkeypatch.setenv("NEUROCOACH_LLM_PROVIDER", "fake")
        # Ceinture et bretelles : meme une configuration reelle ne construit aucun client.
        monkeypatch.setenv("NEUROCOACH_FORBID_REAL_LLM", "1")
    # R2 (D-69) : aucune recherche web reelle en test, meme si .env contient des cles.
    monkeypatch.setenv("NEUROCOACH_FORBID_REAL_RESEARCH", "1")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("EXA_API_KEY", raising=False)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def settings(tmp_path) -> Settings:
    # Simulation demandee explicitement : les tests du parcours de recherche sont hors ligne.
    return Settings(data_dir=tmp_path / "data", research_simulation=True)


@pytest.fixture
def conversations() -> RecordingConversationStore:
    return RecordingConversationStore()


@pytest.fixture
def app(settings, clock, conversations) -> Application:
    return build_application(settings, clock=clock, conversations=conversations)


@pytest.fixture
def alice(app) -> str:
    app.coach.ensure_user(ALICE, "Alice (test)")
    return ALICE


@pytest.fixture
def bruno(app) -> str:
    app.coach.ensure_user(BRUNO, "Bruno (test)")
    return BRUNO


@dataclass
class PlannedProject:
    user_id: str
    project: Project
    tasks: list[Task]


def create_planned_project(app: Application, user_id: str, title: str) -> PlannedProject:
    project = app.coach.create_project(user_id, title)
    action = app.actions.request_plan(user_id, project.id, sample_plan())
    app.actions.confirm(user_id, action.id)
    return PlannedProject(
        user_id,
        app.coach.get_project(user_id, project.id),
        app.coach.list_tasks(user_id, project.id),
    )


@pytest.fixture
def fake_llm():
    from neurocoach.agent.llm import FakeLLM

    return FakeLLM()


@pytest.fixture
def coach(settings, clock, fake_llm):
    """Application complete (services + checkpointer + graphe) avec le faux LLM."""
    from neurocoach.bootstrap import build_coach_runtime

    runtime = build_coach_runtime(settings, clock=clock, llm=fake_llm)
    runtime.app.coach.ensure_user(ALICE, "Alice (test)")
    runtime.app.coach.ensure_user(BRUNO, "Bruno (test)")
    yield runtime
    runtime.checkpointer.conn.close()


@pytest.fixture
def make_planned(app):
    def factory(user_id: str, title: str) -> PlannedProject:
        return create_planned_project(app, user_id, title)

    return factory


@pytest.fixture
def alice_project(app, alice) -> PlannedProject:
    return create_planned_project(app, alice, "Bougies artisanales")


@pytest.fixture
def bruno_project(app, bruno) -> PlannedProject:
    return create_planned_project(app, bruno, "Atelier vélo")
