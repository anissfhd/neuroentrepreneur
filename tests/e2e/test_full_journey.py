"""Parcours complet (phase 4) : creation, clarification, changement d'avis, plan, correction,
confirmation, modification, progression, blocage, redemarrage, export et suppression.

Un seul scenario long, execute avec le faux LLM, sur une base et des checkpoints temporaires.
"""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal

from factories import ALICE, BRUNO
from neurocoach.application.formatting import format_resume_message
from neurocoach.bootstrap import build_coach_runtime
from neurocoach.domain.models import ActionStatus, TaskStatus
from neurocoach.domain.plans import PlanEdits, TaskEdit

VAGUE = "Je veux vendre des bougies artisanales, mais je ne sais pas par où commencer."


def _pending_id(turn) -> str:
    assert turn.pending is not None, turn.reply
    return turn.pending["pending_action_id"]


def test_complete_journey_with_restart_export_and_deletion(coach, settings, clock, fake_llm):
    app, agent = coach.app, coach.agent

    # 1. Creation d'un projet vide (ecriture directe autorisee, R-CONF-01c).
    project = app.coach.create_project(ALICE, "Bougies artisanales", VAGUE)
    assert app.coach.get_progress(ALICE, project.id).percent is None

    # 2. Clarification : reponse du coach (le modele), au plus une question, rien propose.
    first = agent.send_message(ALICE, project.id, VAGUE)
    assert first.reply and first.reply.count("?") <= 1 and first.pending is None

    # 3. Plan propose, puis changement d'avis sur le temps disponible avant toute decision.
    proposal = agent.send_message(
        ALICE,
        project.id,
        "Tester si des personnes seraient intéressées. J'ai 30 minutes par jour. "
        "Mon budget est de 100 €. Proposez-moi un plan.",
    )
    first_action = _pending_id(proposal)
    changed = agent.send_message(ALICE, project.id, "En fait plutôt 1 h par jour.")
    assert app.actions.get_action(ALICE, first_action).status is ActionStatus.CANCELLED
    second_action = _pending_id(changed)
    assert "Temps disponible : environ 60 min par jour" in changed.reply  # D-84 : ses mots
    assert app.coach.list_tasks(ALICE, project.id) == []

    # 4. Correction avant confirmation, puis confirmation.
    revised = agent.revise_plan(
        ALICE,
        project.id,
        second_action,
        PlanEdits(tasks={"client": TaskEdit(title="Décrire ma cliente idéale")}),
    )
    confirmed = agent.decide(ALICE, project.id, _pending_id(revised), "confirm")
    assert confirmed.reply.startswith("Le plan est enregistré. Première action : T1")
    assert len(app.coach.list_tasks(ALICE, project.id)) == 3

    # 5. Modification confirmee par le chat.
    rename = agent.send_message(ALICE, project.id, "Renomme T3 en « Interroger cinq personnes »")
    agent.decide(ALICE, project.id, _pending_id(rename), "confirm")
    assert app.coach.list_tasks(ALICE, project.id)[2].title == "Interroger cinq personnes"

    # 6. Progression, puis blocage avec raison.
    assert agent.send_message(ALICE, project.id, "J'ai terminé T1").undo_event_id
    agent.send_message(ALICE, project.id, "T2 est bloquée car j'attends du matériel")
    tasks = app.coach.list_tasks(ALICE, project.id)
    assert tasks[1].status is TaskStatus.BLOCKED
    assert app.coach.get_progress(ALICE, project.id).percent == Decimal("33.3")
    assert app.coach.get_next_actions(ALICE, project.id).fallback.kind == "lever_blocage"

    # 7. Redemarrage : historique et etat identiques, message de reprise factuel.
    history = agent.history(ALICE, project.id)
    coach.checkpointer.conn.close()
    restarted = build_coach_runtime(settings, clock=clock, llm=fake_llm)
    try:
        assert restarted.agent.history(ALICE, project.id) == history
        resume = format_resume_message(
            project,
            restarted.app.coach.get_progress(ALICE, project.id),
            restarted.app.coach.get_next_actions(ALICE, project.id),
        )
        assert resume.startswith("Vous avez terminé 1 tâche sur 3.")
        assert "lever ce blocage" in resume

        # 8. Export : donnees et conversation d'Alice seulement.
        bruno_project = restarted.app.coach.create_project(BRUNO, "Projet de Bruno")
        restarted.agent.send_message(BRUNO, bruno_project.id, "Bonjour")
        export = restarted.app.data.export_user_data(ALICE)
        serialized = json.dumps(export, ensure_ascii=False)
        assert "Interroger cinq personnes" in serialized
        assert export["conversations"][0]["messages"][0]["content"] == VAGUE
        assert BRUNO not in serialized and bruno_project.id not in serialized

        # 9. Suppression du projet puis effacement complet des donnees d'Alice.
        thread_id = export["conversations"][0]["thread_id"]
        deletion = restarted.app.actions.request_project_deletion(ALICE, project.id)
        restarted.app.actions.confirm(ALICE, deletion.id)
        state = restarted.graph.get_state({"configurable": {"thread_id": thread_id}})
        assert state.values == {}
        erase = restarted.app.actions.request_user_data_deletion(ALICE)
        restarted.app.actions.confirm(ALICE, erase.id)
        assert restarted.app.coach.list_projects(ALICE) == []
        assert restarted.agent.history(BRUNO, bruno_project.id)
    finally:
        restarted.checkpointer.conn.close()

    # Aucune ligne residuelle d'Alice, hormis la trace de l'action d'effacement (E-02).
    conn = sqlite3.connect(settings.business_db_path)
    try:
        leftovers = {}
        for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'"):
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            if "user_id" in columns and table not in ("users", "preferences"):
                count = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (ALICE,)
                ).fetchone()[0]
                leftovers[table] = count
        assert leftovers.pop("pending_actions") == 1
        assert set(leftovers.values()) == {0}, leftovers
        trace = conn.execute(
            "SELECT action_type, payload_json, preview_json FROM pending_actions WHERE user_id = ?",
            (ALICE,),
        ).fetchone()
        assert trace[0] == "user.delete_data"
        assert "Bougies" not in trace[1] + trace[2]
    finally:
        conn.close()
