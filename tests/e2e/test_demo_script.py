"""Le parcours de docs/DEMO_SCRIPT.md reste reproductible avec le faux fournisseur."""

from __future__ import annotations

from decimal import Decimal

from neurocoach.bootstrap import build_coach_runtime
from neurocoach.demo import DEMO_BRUNO_ID, seed_demo
from neurocoach.domain.models import ActionStatus, TaskStatus
from neurocoach.domain.plans import PlanEdits, TaskEdit


def test_demo_script(settings, clock, fake_llm):
    runtime = build_coach_runtime(settings, clock=clock, llm=fake_llm)
    try:
        seed_demo(runtime.app)
        app, agent = runtime.app, runtime.agent
        app.coach.update_preferences(DEMO_BRUNO_ID, response_length="court", max_visible_tasks=1)
        project = app.coach.list_projects(DEMO_BRUNO_ID)[0]
        assert project.title == "Atelier de réparation de vélos"

        question = agent.send_message(
            DEMO_BRUNO_ID,
            project.id,
            "Je veux ouvrir un atelier de réparation de vélos, par où commencer ?",
        )
        assert question.reply.endswith("?") and question.pending is None
        proposal = agent.send_message(
            DEMO_BRUNO_ID,
            project.id,
            "Trouver trois premiers clients. J'ai 45 minutes par jour et 50 € de budget. "
            "Proposez-moi un plan.",
        )
        revised = agent.revise_plan(
            DEMO_BRUNO_ID,
            project.id,
            proposal.pending["pending_action_id"],
            PlanEdits(
                tasks={
                    "client": TaskEdit(title="Décrire mon client cycliste idéal"),
                    "entretiens": TaskEdit(remove=True),
                }
            ),
        )
        assert app.coach.list_tasks(DEMO_BRUNO_ID, project.id) == []
        done = agent.decide(
            DEMO_BRUNO_ID, project.id, revised.pending["pending_action_id"], "confirm"
        )
        assert done.reply.startswith(
            "Le plan est enregistré. Première action : T1 « Décrire mon client cycliste idéal »."
        )

        t1, t2 = app.coach.list_tasks(DEMO_BRUNO_ID, project.id)
        started = app.coach.set_task_status(DEMO_BRUNO_ID, t1.id, TaskStatus.IN_PROGRESS)
        app.coach.undo_status_change(DEMO_BRUNO_ID, started.event_id)
        app.coach.set_task_status(DEMO_BRUNO_ID, t1.id, TaskStatus.DONE)
        assert app.coach.get_progress(DEMO_BRUNO_ID, project.id).percent == Decimal("50.0")
        app.coach.set_task_status(DEMO_BRUNO_ID, t2.id, TaskStatus.BLOCKED, "J'attends du matériel")
        assert (
            app.coach.get_next_actions(DEMO_BRUNO_ID, project.id).fallback.kind == "lever_blocage"
        )

        replan = agent.send_message(DEMO_BRUNO_ID, project.id, "Je n'ai pas avancé cette semaine")
        assert replan.pending is not None
        yes = agent.send_message(DEMO_BRUNO_ID, project.id, "Oui")
        assert yes.notice.startswith("Pour enregistrer cette proposition")
        cancelled = agent.decide(
            DEMO_BRUNO_ID, project.id, replan.pending["pending_action_id"], "cancel"
        )
        assert cancelled.reply == "D'accord, rien n'a été modifié."
        history = agent.history(DEMO_BRUNO_ID, project.id)
    finally:
        runtime.checkpointer.conn.close()

    restarted = build_coach_runtime(settings, clock=clock, llm=fake_llm)
    try:
        assert restarted.agent.history(DEMO_BRUNO_ID, project.id) == history
        export = restarted.app.data.export_user_data(DEMO_BRUNO_ID)
        assert export["projects"][0]["project"]["title"] == "Atelier de réparation de vélos"
        deletion = restarted.app.actions.request_project_deletion(DEMO_BRUNO_ID, project.id)
        outcome = restarted.app.actions.confirm(DEMO_BRUNO_ID, deletion.id)
        assert outcome.action.status is ActionStatus.APPLIED
        assert restarted.app.coach.list_projects(DEMO_BRUNO_ID) == []
    finally:
        restarted.checkpointer.conn.close()
