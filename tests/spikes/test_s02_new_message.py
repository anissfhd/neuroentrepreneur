"""S-02 : nouveau message pendant une confirmation en attente.

Observation : envoyer une nouvelle entree sur un fil interrompu ABANDONNE silencieusement
l'interruption et relance le graphe depuis START. L'action en attente en base n'est alors
ni confirmee ni annulee. Contournement retenu (ARCHITECTURE 5.2, point 7) : annuler l'action,
reprendre le graphe avec cette issue, puis seulement envoyer le nouveau message.
"""

from __future__ import annotations

import pytest
from langgraph.types import Command

from neurocoach.domain.models import ActionStatus
from spikes.spike_support import (
    Counters,
    SpikeContext,
    build_spike_graph,
    open_saver,
    pending_interrupts,
)


@pytest.fixture
def setup(app, alice, tmp_path):
    project = app.coach.create_project(alice, "Projet spike")
    counters = Counters()
    graph = build_spike_graph(app, open_saver(tmp_path / "checkpoints.sqlite"), counters)
    config = {"configurable": {"thread_id": "thr_s02"}}
    return graph, config, SpikeContext(alice, project.id), counters


def test_raw_new_input_silently_drops_the_interrupt(app, setup):
    graph, config, context, counters = setup
    first = graph.invoke({"request": "plan"}, config, context=context)
    first_action = first["__interrupt__"][0].value["pending_action_id"]
    graph.invoke({"request": "lire"}, config, context=context)
    # Le graphe a oublie l'interruption...
    assert graph.get_state(config).next == ()
    assert pending_interrupts(graph, config) == []
    assert counters.calls["await_after"] == 0
    # ... mais l'action reste en attente en base : c'est l'incoherence a eviter.
    assert app.actions.get_action(context.user_id, first_action).status is ActionStatus.PENDING


def test_raw_new_proposal_starts_over_and_supersedes(app, setup):
    graph, config, context, counters = setup
    first = graph.invoke({"request": "plan"}, config, context=context)
    first_action = first["__interrupt__"][0].value["pending_action_id"]
    second = graph.invoke({"request": "plan"}, config, context=context)
    second_action = second["__interrupt__"][0].value["pending_action_id"]
    assert counters.calls["propose"] == 2
    assert app.actions.get_action(context.user_id, first_action).status is ActionStatus.SUPERSEDED
    assert pending_interrupts(graph, config) == [{"pending_action_id": second_action}]


def test_cancel_then_resume_then_send_keeps_everything_consistent(app, setup):
    graph, config, context, _ = setup
    first = graph.invoke({"request": "plan"}, config, context=context)
    action_id = first["__interrupt__"][0].value["pending_action_id"]
    # 1. annuler en base ; 2. clore l'execution interrompue ; 3. envoyer le nouveau message.
    app.actions.cancel(context.user_id, action_id)
    closed = graph.invoke(Command(resume={"decision": "nouveau_message"}), config, context=context)
    assert closed["outcome"] == "cancelled"
    result = graph.invoke({"request": "lire"}, config, context=context)
    assert result["seen_titles"] == []
    assert graph.get_state(config).next == ()
    assert app.actions.get_pending(context.user_id, context.project_id) is None
    assert app.actions.get_action(context.user_id, action_id).status is ActionStatus.CANCELLED
    assert app.coach.list_tasks(context.user_id, context.project_id) == []
