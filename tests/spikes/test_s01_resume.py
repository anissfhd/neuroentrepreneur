"""S-01 : reprise d'un graphe interrompu sans duplication."""

from __future__ import annotations

import pytest
from langgraph.types import Command

from neurocoach.domain.errors import DomainError, ErrorCode
from spikes.spike_support import Counters, SpikeContext, build_spike_graph, open_saver


@pytest.fixture
def setup(app, alice, tmp_path):
    project = app.coach.create_project(alice, "Projet spike")
    counters = Counters()
    saver = open_saver(tmp_path / "checkpoints.sqlite")
    graph = build_spike_graph(app, saver, counters)
    config = {"configurable": {"thread_id": "thr_s01"}}
    return graph, config, SpikeContext(alice, project.id), counters, project, saver


def _task_count(app, context):
    return len(app.coach.list_tasks(context.user_id, context.project_id))


def test_interrupt_pauses_before_any_business_write(app, setup):
    graph, config, context, counters, _, _ = setup
    result = graph.invoke({"request": "plan"}, config, context=context)
    assert "__interrupt__" in result
    assert graph.get_state(config).next == ("await_decision",)
    assert counters.calls == {"propose": 1, "await": 1, "await_after": 0, "read": 0}
    assert _task_count(app, context) == 0


def test_resume_reexecutes_only_the_interrupted_node(app, setup):
    graph, config, context, counters, _, _ = setup
    result = graph.invoke({"request": "plan"}, config, context=context)
    action_id = result["__interrupt__"][0].value["pending_action_id"]
    app.actions.confirm(context.user_id, action_id)
    final = graph.invoke(Command(resume={"decision": "confirm"}), config, context=context)
    assert final["outcome"] == "applied"
    # Observe : le noeud interrompu est reexecute depuis son debut ; le noeud precedent non.
    assert counters.calls["propose"] == 1
    assert counters.calls["await"] == 2
    assert counters.calls["await_after"] == 1
    assert graph.get_state(config).next == ()
    assert _task_count(app, context) == 3


def test_double_click_writes_once(app, setup):
    graph, config, context, counters, _, _ = setup
    result = graph.invoke({"request": "plan"}, config, context=context)
    action_id = result["__interrupt__"][0].value["pending_action_id"]
    app.actions.confirm(context.user_id, action_id)
    graph.invoke(Command(resume={"decision": "confirm"}), config, context=context)
    # Second clic : refuse par le service, puis reprise d'un fil deja termine.
    with pytest.raises(DomainError) as error:
        app.actions.confirm(context.user_id, action_id)
    assert error.value.code is ErrorCode.ACTION_ALREADY_DECIDED
    again = graph.invoke(Command(resume={"decision": "confirm"}), config, context=context)
    # Observe : reprendre un fil termine n'execute aucun noeud.
    assert again["outcome"] == "applied"
    assert counters.calls == {"propose": 1, "await": 2, "await_after": 1, "read": 0}
    assert _task_count(app, context) == 3


def test_resume_after_restart_with_a_new_saver(app, setup, tmp_path):
    graph, config, context, _, _, saver = setup
    result = graph.invoke({"request": "plan"}, config, context=context)
    action_id = result["__interrupt__"][0].value["pending_action_id"]
    saver.conn.close()
    # Redemarrage simule : nouvelle connexion, nouveau graphe, meme fichier de checkpoints.
    counters = Counters()
    reopened = build_spike_graph(app, open_saver(tmp_path / "checkpoints.sqlite"), counters)
    assert reopened.get_state(config).next == ("await_decision",)
    app.actions.cancel(context.user_id, action_id)
    final = reopened.invoke(Command(resume={"decision": "cancel"}), config, context=context)
    assert final["outcome"] == "cancelled"
    assert counters.calls["propose"] == 0
    assert _task_count(app, context) == 0
