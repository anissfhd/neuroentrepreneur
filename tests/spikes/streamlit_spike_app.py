"""Application Streamlit minimale du test technique S-05 (pilotee par AppTest)."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st
from langgraph.types import Command

from neurocoach.bootstrap import build_application
from neurocoach.config import Settings
from neurocoach.domain.errors import DomainError
from spikes.spike_support import Counters, SpikeContext, build_spike_graph, open_saver

if "runtime" not in st.session_state:
    data_dir = Path(os.environ["NEUROCOACH_DATA_DIR"])
    app = build_application(Settings(data_dir=data_dir))
    user_id = app.coach.ensure_user("usr_" + "a" * 32, "Alice (test)").id
    project = app.coach.create_project(user_id, "Projet Streamlit")
    counters = Counters()
    graph = build_spike_graph(app, open_saver(data_dir / "checkpoints.sqlite"), counters)
    st.session_state.runtime = {
        "app": app,
        "graph": graph,
        "counters": counters,
        "context": SpikeContext(user_id, project.id),
        "config": {"configurable": {"thread_id": "thr_streamlit"}},
    }

runtime = st.session_state.runtime
app, graph, context, config = (
    runtime["app"],
    runtime["graph"],
    runtime["context"],
    runtime["config"],
)

if st.button("Demander un plan", key="ask"):
    result = graph.invoke({"request": "plan"}, config, context=context)
    if "__interrupt__" in result:
        st.session_state.pending = result["__interrupt__"][0].value["pending_action_id"]

pending = st.session_state.get("pending")
if pending:
    st.subheader("Proposition en attente")
    left, right = st.columns(2)
    confirm = left.button("Confirmer", key="confirm")
    cancel = right.button("Annuler", key="cancel")
    if confirm or cancel:
        try:
            if confirm:
                app.actions.confirm(context.user_id, pending)
            else:
                app.actions.cancel(context.user_id, pending)
        except DomainError as error:
            st.session_state.notice = error.user_message
        # Reprise uniquement si le graphe attend reellement une decision.
        if graph.get_state(config).next:
            graph.invoke(Command(resume={"decision": "ui"}), config, context=context)
        st.session_state.outcome = app.actions.get_action(context.user_id, pending).status.value
        st.session_state.pending = None
        st.rerun()

st.text(f"resultat={st.session_state.get('outcome')}")
st.text(f"taches={len(app.coach.list_tasks(context.user_id, context.project_id))}")
if st.session_state.get("notice"):
    st.info(st.session_state.notice)
