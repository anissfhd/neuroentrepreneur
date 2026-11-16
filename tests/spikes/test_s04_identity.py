"""S-04 : transmission securisee de l'identite au graphe.

Observations : le contexte d'execution n'est pas checkpointe ; il faut le fournir a chaque
appel, y compris a la reprise, et il vaut ``None`` s'il est omis. Une cle ``user_id`` glissee
dans l'entree est ignoree. Consequences : les noeuds refusent un contexte absent, et le
lanceur de l'application verifie que le fil appartient a l'utilisateur de la session.
"""

from __future__ import annotations

import pytest
from langgraph.types import Command

from neurocoach.domain.errors import DomainError, ErrorCode
from spikes.spike_support import Counters, SpikeContext, build_spike_graph, open_saver


@pytest.fixture
def setup(app, alice_project, bruno_project, tmp_path):
    graph = build_spike_graph(app, open_saver(tmp_path / "checkpoints.sqlite"), Counters())
    return graph, alice_project, bruno_project


def test_identity_is_not_stored_in_checkpointed_state(setup):
    graph, alice, _ = setup
    config = {"configurable": {"thread_id": "thr_alice"}}
    graph.invoke({"request": "lire"}, config, context=SpikeContext(alice.user_id, alice.project.id))
    values = graph.get_state(config).values
    assert "user_id" not in values
    assert alice.user_id not in repr(values)


def test_identity_in_user_input_is_ignored(setup):
    graph, alice, bruno = setup
    config = {"configurable": {"thread_id": "thr_alice"}}
    result = graph.invoke(
        {"request": "lire", "user_id": bruno.user_id, "project_id": bruno.project.id},
        config,
        context=SpikeContext(alice.user_id, alice.project.id),
    )
    assert result["seen_titles"] == [task.title for task in alice.tasks]
    assert "user_id" not in graph.get_state(config).values


def test_missing_context_is_refused(setup):
    graph, _, _ = setup
    with pytest.raises(PermissionError):
        graph.invoke({"request": "lire"}, {"configurable": {"thread_id": "thr_x"}})


def test_resume_uses_the_identity_given_at_resume(app, setup):
    graph, alice, bruno = setup
    project = app.coach.create_project(alice.user_id, "Second projet")
    config = {"configurable": {"thread_id": "thr_resume"}}
    first = graph.invoke(
        {"request": "plan"}, config, context=SpikeContext(alice.user_id, project.id)
    )
    action_id = first["__interrupt__"][0].value["pending_action_id"]
    # Reprise du fil d'Alice avec l'identite de Bruno : le service refuse l'acces.
    with pytest.raises(DomainError) as error:
        graph.invoke(
            Command(resume={"decision": "confirm"}),
            config,
            context=SpikeContext(bruno.user_id, bruno.project.id),
        )
    assert error.value.code is ErrorCode.NOT_FOUND
    assert app.actions.get_pending(alice.user_id, project.id).id == action_id
    assert len(app.coach.list_tasks(bruno.user_id, bruno.project.id)) == 3
