"""Construction du graphe unique (ARCHITECTURE 4.3)."""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from neurocoach.agent.context import AgentContext
from neurocoach.agent.llm import LLMProvider
from neurocoach.agent.nodes import CoachNodes
from neurocoach.agent.routing import (
    after_await,
    after_clarify,
    after_draft,
    after_followup,
    after_propose,
    after_respond,
    after_understand,
)
from neurocoach.agent.state import CoachState
from neurocoach.bootstrap import Application


def build_coach_graph(app: Application, llm: LLMProvider, checkpointer: BaseCheckpointSaver):
    nodes = CoachNodes(app, llm)
    graph = StateGraph(CoachState, context_schema=AgentContext)
    for name in (
        "load_context",
        "understand",
        "clarify",
        "draft_plan",
        "draft_change",
        "propose",
        "await_decision",
        "answer_status",
        "apply_status",
        "pause",
        "out_of_scope",
        "research",
        "analyze",
        "solutions",
        "solution_tasks",
        "respond",
        "followup",
    ):
        graph.add_node(name, getattr(nodes, name))

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "understand")
    graph.add_conditional_edges(
        "understand",
        after_understand,
        [
            "respond",
            "clarify",
            "answer_status",
            "apply_status",
            "pause",
            "draft_change",
            "out_of_scope",
            "research",
            "analyze",
            "solutions",
            "solution_tasks",
        ],
    )
    graph.add_conditional_edges(
        "clarify", after_clarify, ["draft_plan", "respond", "research", "understand"]
    )
    graph.add_conditional_edges("draft_plan", after_draft, ["propose", "respond"])
    graph.add_conditional_edges("draft_change", after_draft, ["propose", "respond"])
    # R6 : actions des solutions -> meme proposition, meme confirmation que pour un plan.
    graph.add_conditional_edges("solution_tasks", after_draft, ["propose", "respond"])
    # D-85 : taches terminees ensemble, pause et reprise -> meme carte de confirmation.
    graph.add_conditional_edges("apply_status", after_draft, ["propose", "respond"])
    graph.add_conditional_edges("pause", after_draft, ["propose", "respond"])
    graph.add_conditional_edges("propose", after_propose, ["await_decision", "respond"])
    graph.add_conditional_edges("await_decision", after_await, ["await_decision", "respond"])
    for name in (
        "answer_status",
        "out_of_scope",
        "research",
        "analyze",
        "solutions",
    ):
        graph.add_edge(name, "respond")
    # D-87 : seconde demande du meme message, apres la reponse a la premiere.
    graph.add_conditional_edges("respond", after_respond, {"followup": "followup", "end": END})
    graph.add_conditional_edges(
        "followup",
        after_followup,
        {"draft_change": "draft_change", "respond": "respond", "end": END},
    )
    return graph.compile(checkpointer=checkpointer)
