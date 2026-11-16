"""S-03 : suppression complete des checkpoints et des conversations."""

from __future__ import annotations

import pytest

from neurocoach.bootstrap import build_application
from neurocoach.infra.checkpoint import SqliteConversationStore
from spikes.spike_support import Counters, SpikeContext, build_spike_graph, open_saver


def _rows(saver, thread_id: str) -> dict[str, int]:
    return {
        table: saver.conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE thread_id = ?", (thread_id,)
        ).fetchone()[0]
        for table in ("checkpoints", "writes")
    }


def test_delete_thread_removes_only_that_thread(app, alice, tmp_path):
    project = app.coach.create_project(alice, "Projet spike")
    saver = open_saver(tmp_path / "checkpoints.sqlite")
    graph = build_spike_graph(app, saver, Counters())
    context = SpikeContext(alice, project.id)
    for thread in ("thr_a", "thr_b"):
        graph.invoke({"request": "lire"}, {"configurable": {"thread_id": thread}}, context=context)
    assert _rows(saver, "thr_a")["checkpoints"] > 0
    kept = _rows(saver, "thr_b")
    saver.delete_thread("thr_a")
    assert _rows(saver, "thr_a") == {"checkpoints": 0, "writes": 0}
    assert _rows(saver, "thr_b") == kept
    assert graph.get_state({"configurable": {"thread_id": "thr_a"}}).values == {}


@pytest.fixture
def wired(settings, clock, tmp_path):
    saver = open_saver(tmp_path / "checkpoints.sqlite")
    store = SqliteConversationStore(saver)
    application = build_application(settings, clock=clock, conversations=store)
    return application, saver, store


def test_user_data_deletion_erases_checkpoints(wired):
    application, saver, _ = wired
    alice = application.coach.ensure_user("usr_" + "a" * 32, "Alice").id
    bruno = application.coach.ensure_user("usr_" + "b" * 32, "Bruno").id
    graph = build_spike_graph(application, saver, Counters())
    threads = {}
    for user in (alice, bruno):
        project = application.coach.create_project(user, "Projet")
        thread = application.coach.get_conversation_thread(user, project.id)
        graph.invoke(
            {"request": "lire"},
            {"configurable": {"thread_id": thread.id}},
            context=SpikeContext(user, project.id),
        )
        threads[user] = thread.id
    assert _rows(saver, threads[alice])["checkpoints"] > 0
    action = application.actions.request_user_data_deletion(alice)
    application.actions.confirm(alice, action.id)
    assert _rows(saver, threads[alice]) == {"checkpoints": 0, "writes": 0}
    assert _rows(saver, threads[bruno])["checkpoints"] > 0


def test_store_exports_messages_of_a_thread(wired):
    from langchain_core.messages import AIMessage, HumanMessage
    from langgraph.graph import END, START, MessagesState, StateGraph

    _, saver, store = wired

    def reply(state: MessagesState) -> dict:
        return {"messages": [AIMessage(content="Réponse")]}

    graph = StateGraph(MessagesState)
    graph.add_node("reply", reply)
    graph.add_edge(START, "reply")
    graph.add_edge("reply", END)
    compiled = graph.compile(checkpointer=saver)
    compiled.invoke(
        {"messages": [HumanMessage(content="Bonjour")]}, {"configurable": {"thread_id": "thr_m"}}
    )
    assert store.export_messages("thr_m") == [
        {"role": "user", "content": "Bonjour"},
        {"role": "assistant", "content": "Réponse"},
    ]
    assert store.export_messages("thr_inconnu") == []
    store.delete_threads(["thr_m"])
    assert store.export_messages("thr_m") == []
