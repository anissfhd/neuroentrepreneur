"""Graphe minimal des tests techniques S-01 a S-04 (sans LLM, services reels de la phase 1)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from factories import sample_plan
from neurocoach.bootstrap import Application


class SpikeState(TypedDict, total=False):
    request: str
    pending_action_id: str | None
    outcome: str | None
    seen_titles: list[str]


@dataclass(frozen=True)
class SpikeContext:
    user_id: str
    project_id: str


@dataclass
class Counters:
    calls: dict[str, int] = field(
        default_factory=lambda: {"propose": 0, "await": 0, "await_after": 0, "read": 0}
    )


_OPEN: list[sqlite3.Connection] = []


def open_saver(path: Path) -> SqliteSaver:
    conn = sqlite3.connect(path, check_same_thread=False)
    _OPEN.append(conn)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


def close_savers() -> None:
    while _OPEN:
        _OPEN.pop().close()


def require_context(runtime: Runtime[SpikeContext]) -> SpikeContext:
    if runtime.context is None:
        raise PermissionError("contexte d'identite absent")
    return runtime.context


def build_spike_graph(app: Application, saver: SqliteSaver, counters: Counters):
    def route(state: SpikeState) -> str:
        return "read" if state.get("request") == "lire" else "propose"

    def propose(state: SpikeState, runtime: Runtime[SpikeContext]) -> dict:
        context = require_context(runtime)
        counters.calls["propose"] += 1
        action = app.actions.request_plan(context.user_id, context.project_id, sample_plan())
        return {"pending_action_id": action.id, "outcome": None}

    def await_decision(state: SpikeState, runtime: Runtime[SpikeContext]) -> dict:
        context = require_context(runtime)
        counters.calls["await"] += 1
        interrupt({"pending_action_id": state["pending_action_id"]})
        counters.calls["await_after"] += 1
        action = app.actions.get_action(context.user_id, state["pending_action_id"])
        return {"outcome": action.status.value}

    def read(state: SpikeState, runtime: Runtime[SpikeContext]) -> dict:
        context = require_context(runtime)
        counters.calls["read"] += 1
        tasks = app.coach.list_tasks(context.user_id, context.project_id)
        return {"seen_titles": [task.title for task in tasks]}

    graph = StateGraph(SpikeState, context_schema=SpikeContext)
    graph.add_node("propose", propose)
    graph.add_node("await_decision", await_decision)
    graph.add_node("read", read)
    graph.add_conditional_edges(START, route, {"propose": "propose", "read": "read"})
    graph.add_edge("propose", "await_decision")
    graph.add_edge("await_decision", END)
    graph.add_edge("read", END)
    return graph.compile(checkpointer=saver)


def pending_interrupts(graph, config) -> list[dict]:
    state = graph.get_state(config)
    return [item.value for task in state.tasks for item in task.interrupts]
