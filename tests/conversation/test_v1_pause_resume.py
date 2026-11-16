"""D-85 : simulation 6 validee - taches terminees confirmees ensemble, pause reelle, reprise
apres plusieurs semaines avec un resume fonde sur la base. Faux modele : ces tests verifient
les etats en base, les cartes, la persistance apres redemarrage et ce que le code garantit ;
la formulation du coach (vrai modele) n'est pas jugee ici. Les simulations sont des
references de comportement : aucun texte n'en est recopie.
"""

from __future__ import annotations

import socket
from datetime import timedelta

import pytest

from factories import ALICE
from neurocoach.agent.nodes import ALREADY_PAUSED
from neurocoach.agent.runner import RETURN_AFTER_DAYS
from neurocoach.agent.schemas import IntentResult
from neurocoach.domain.models import ActionStatus, EventType, TaskStatus

VAGUE = "Je veux vendre des bougies artisanales, mais je ne sais pas par où commencer."
DETAILS = (
    "Tester si des personnes seraient intéressées. J'ai 30 minutes par jour. "
    "Mon budget est de 100 €. Proposez-moi un plan."
)
BLOCKED = "Deux boutiques m'ont dit qu'elles ne vendent pas de produits artisanaux."
PAUSE = "Je suis fatiguée, j'aimerais faire une pause."


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("connexion reseau tentee")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def say(coach, project, text):
    return coach.agent.send_message(ALICE, project.id, text)


def confirm(coach, project, turn):
    return coach.agent.decide(ALICE, project.id, turn.pending["pending_action_id"], "confirm")


@pytest.fixture
def planned(coach):
    project = coach.app.coach.create_project(ALICE, "Bougies artisanales", VAGUE)
    say(coach, project, VAGUE)
    confirm(coach, project, say(coach, project, DETAILS))
    return project


def tasks(coach, project):
    return coach.app.coach.list_tasks(ALICE, project.id)


def events(coach, project, kind):
    return [e for e in coach.app.coach.list_events(ALICE, project.id) if e.type is kind]


# --- plusieurs taches terminees, un seul clic -------------------------------------------------


def test_two_tasks_said_done_are_confirmed_together_and_stay_undoable(coach, planned):
    turn = say(coach, planned, "J'ai terminé T1 et T2.")
    assert turn.pending is not None and turn.pending["kind"] == "tasks_done"
    assert "« Confirmer les tâches terminées »" in turn.reply
    assert [t.status for t in tasks(coach, planned)][:2] == [TaskStatus.TODO] * 2  # rien avant
    done = confirm(coach, planned, turn)
    assert done.reply.startswith("C'est enregistré : T1 et T2 terminées.")
    first, second, third = tasks(coach, planned)
    assert (first.status, second.status, third.status) == (
        TaskStatus.DONE, TaskStatus.DONE, TaskStatus.TODO,
    )  # fmt: skip
    changed = events(coach, planned, EventType.TASK_STATUS_CHANGED)
    assert {e.payload["task_ref"] for e in changed} == {"T1", "T2"}
    # Chaque tache reste annulable separement, comme un changement direct.
    second_event = next(e for e in changed if e.payload["task_ref"] == "T2")
    coach.app.coach.undo_status_change(ALICE, second_event.id)
    assert tasks(coach, planned)[1].status is TaskStatus.TODO


def test_tasks_named_by_their_titles_are_recognised_without_numbers(coach, planned):
    titles = [t.title for t in tasks(coach, planned)]
    assert titles[:2] == ["Décrire le client visé", "Préparer cinq questions"]
    turn = say(coach, planned, "J'ai décrit le client visé et préparé les cinq questions, "
                               "c'est terminé.")  # fmt: skip
    assert turn.pending["kind"] == "tasks_done"
    assert [line.split(" « ")[0] for line in turn.pending["preview"]] == ["Tâche T1", "Tâche T2"]


def test_a_task_the_model_proposes_but_the_message_does_not_name_is_left_out(coach, planned):
    """D-57 : jamais de tache devinee ; la proposition du modele est verifiee par le code."""
    coach.llm.script("classify_intent", IntentResult(
        intent="changer_statut", target_status="done", task_refs=["T1", "T3"],
    ))  # fmt: skip
    turn = say(coach, planned, "J'ai terminé la partie sur le client.")
    assert turn.pending["kind"] == "tasks_done"
    assert len(turn.pending["preview"]) == 1 and turn.pending["preview"][0].startswith("Tâche T1")


def test_refusing_the_grouped_card_writes_nothing(coach, planned):
    turn = say(coach, planned, "J'ai terminé T1 et T2.")
    coach.agent.decide(ALICE, planned.id, turn.pending["pending_action_id"], "cancel")
    assert all(t.status is TaskStatus.TODO for t in tasks(coach, planned))
    assert coach.app.actions.get_action(ALICE, turn.pending["pending_action_id"]).status is (
        ActionStatus.CANCELLED
    )


def test_a_single_clear_task_keeps_the_direct_undoable_change(coach, planned):
    turn = say(coach, planned, "J'ai terminé T1")
    assert turn.pending is None and turn.undo_event_id is not None
    assert tasks(coach, planned)[0].status is TaskStatus.DONE


# --- pause reelle --------------------------------------------------------------------------


def test_a_pause_is_proposed_with_her_reason_and_applied_only_after_the_click(coach, planned):
    say(coach, planned, "J'ai terminé T1")
    say(coach, planned, BLOCKED)
    turn = say(coach, planned, PAUSE)
    assert turn.pending is not None and turn.pending["kind"] == "pause"
    assert f"raison notée : « {BLOCKED.rstrip('.')} »" in turn.pending["preview"][0]
    assert "« Mettre en pause »" in turn.reply
    assert coach.app.coach.get_project(ALICE, planned.id).paused_at is None  # rien avant
    applied = confirm(coach, planned, turn)
    assert applied.reply.startswith("Le projet est en pause. 1 tâche terminée sur 3")
    project = coach.app.coach.get_project(ALICE, planned.id)
    assert project.paused_at == coach.app.clock.now() and project.pause_note == BLOCKED
    assert project.status.value == "active"  # statut, plan et taches conserves
    assert [t.status for t in tasks(coach, planned)] == [TaskStatus.DONE] + [TaskStatus.TODO] * 2
    assert len(events(coach, planned, EventType.PROJECT_PAUSED)) == 1
    assert say(coach, planned, PAUSE).reply == ALREADY_PAUSED


def test_a_pause_reason_she_never_gave_is_not_recorded(coach, planned):
    coach.llm.script("classify_intent", IntentResult(
        intent="pause_projet", pause_note="Elle a perdu son emploi et déménage à Paris.",
    ))  # fmt: skip
    turn = say(coach, planned, "Je fais une pause.")
    assert "raison notée" not in turn.pending["preview"][0]
    confirm(coach, planned, turn)
    assert coach.app.coach.get_project(ALICE, planned.id).pause_note is None


def test_cancelling_the_pause_keeps_the_project_running(coach, planned):
    turn = say(coach, planned, PAUSE)
    coach.agent.decide(ALICE, planned.id, turn.pending["pending_action_id"], "cancel")
    assert coach.app.coach.get_project(ALICE, planned.id).paused_at is None


# --- redemarrage, retour, reprise ----------------------------------------------------------


def _paused_after(settings, clock, fake_llm):
    from neurocoach.bootstrap import build_coach_runtime

    first = build_coach_runtime(settings, clock=clock, llm=fake_llm)
    first.app.coach.ensure_user(ALICE, "Alice (test)")
    project = first.app.coach.create_project(ALICE, "Bougies artisanales", VAGUE)
    first.agent.send_message(ALICE, project.id, VAGUE)
    confirm(first, project, first.agent.send_message(ALICE, project.id, DETAILS))
    confirm(first, project, first.agent.send_message(ALICE, project.id, "J'ai terminé T1 et T2."))
    first.agent.send_message(ALICE, project.id, BLOCKED)
    confirm(first, project, first.agent.send_message(ALICE, project.id, PAUSE))
    first.checkpointer.conn.close()
    clock.advance(timedelta(weeks=3))
    return build_coach_runtime(settings, clock=clock, llm=fake_llm), project


def test_after_a_restart_the_paused_project_is_summarised_from_what_is_saved(
    settings, clock, fake_llm
):
    again, project = _paused_after(settings, clock, fake_llm)
    try:
        saved = again.app.coach.get_project(ALICE, project.id)
        assert saved.paused_at is not None and saved.pause_note == BLOCKED
        assert [t.status for t in again.app.coach.list_tasks(ALICE, project.id)] == [
            TaskStatus.DONE, TaskStatus.DONE, TaskStatus.TODO,
        ]  # fmt: skip
        assert again.agent.welcome_back(ALICE, project.id) is True
        recap = again.agent.history(ALICE, project.id)[-1]["content"]
        assert recap.startswith("Bon retour ! Voici où nous en étions sur votre projet :")
        for fact in (
            "Vous avez terminé 2 tâches sur 3 : T1 « Décrire le client visé », "
            "T2 « Préparer cinq questions ».",
            "Nous avions mis le projet en pause le ",
            f"« {BLOCKED.rstrip('.')} ».",
            "Souhaitez-vous reprendre ?",
        ):
            assert fact in recap, fact
        assert "T3" not in recap  # pas de relance de tache pendant la pause
        assert fake_llm.calls == [] or "draft_plan" not in [t for t, _ in fake_llm.calls[-1:]]
        assert again.agent.welcome_back(ALICE, project.id) is False  # une seule fois
    finally:
        again.checkpointer.conn.close()


def test_resuming_keeps_the_done_tasks_and_the_plan_can_then_be_adapted(settings, clock, fake_llm):
    again, project = _paused_after(settings, clock, fake_llm)
    try:
        turn = again.agent.send_message(
            ALICE, project.id, "Bonjour, je suis de retour, je reprends."
        )
        assert turn.pending["kind"] == "resume" and "« Reprendre le projet »" in turn.reply
        resumed = confirm(again, project, turn)
        assert resumed.reply.startswith("Le projet a repris. 2 tâches terminées sur 3")
        assert again.app.coach.get_project(ALICE, project.id).paused_at is None
        assert len(events(again, project, EventType.PROJECT_RESUMED)) == 1
        # Adaptation du plan : les taches terminees ne peuvent pas etre modifiees.
        from neurocoach.domain.proposals import ChangeProposal

        again.llm.script("classify_intent", IntentResult(intent="replanifier"))
        again.llm.script("draft_change", ChangeProposal(
            changes=[{"op": "update", "task_ref": "T3", "fields": {"estimate_minutes": 20}}],
            rationale="Deux heures par semaine : une étape plus courte.",
        ))  # fmt: skip
        change = again.agent.send_message(ALICE, project.id, "J'ai moins de temps, adaptez.")
        confirm(again, project, change)
        first, second, third = again.app.coach.list_tasks(ALICE, project.id)
        assert (first.status, second.status, third.estimate_minutes) == (
            TaskStatus.DONE, TaskStatus.DONE, 20,
        )  # fmt: skip
    finally:
        again.checkpointer.conn.close()


def test_the_resume_button_is_journalised_like_the_card(coach, planned):
    confirm(coach, planned, say(coach, planned, PAUSE))
    text = coach.agent.resume_project(ALICE, planned.id)
    assert text.startswith("Le projet a repris.")
    assert coach.app.coach.get_project(ALICE, planned.id).paused_at is None
    assert len(events(coach, planned, EventType.PROJECT_RESUMED)) == 1
    assert coach.agent.history(ALICE, planned.id)[-1]["content"] == text


def test_a_long_absence_without_pause_also_gets_a_summary_once(coach, planned):
    say(coach, planned, "J'ai terminé T1")
    assert coach.agent.welcome_back(ALICE, planned.id) is False  # actif aujourd'hui
    coach.app.clock.advance(timedelta(days=RETURN_AFTER_DAYS - 1))
    assert coach.agent.welcome_back(ALICE, planned.id) is False
    coach.app.clock.advance(timedelta(days=2))
    assert coach.agent.welcome_back(ALICE, planned.id) is True
    recap = coach.agent.history(ALICE, planned.id)[-1]["content"]
    assert "Vous avez terminé 1 tâche sur 3 : T1 « Décrire le client visé »." in recap
    assert "La prochaine action serait T2 « Préparer cinq questions »." in recap
    assert coach.agent.welcome_back(ALICE, planned.id) is False


def test_no_summary_while_a_proposal_waits_or_on_a_new_project(coach, planned):
    fresh = coach.app.coach.start_project(ALICE)
    coach.agent.greet(ALICE, fresh.id)
    assert coach.agent.welcome_back(ALICE, fresh.id) is False  # aucun message de sa part
    say(coach, planned, PAUSE)  # carte de pause en attente
    coach.app.clock.advance(timedelta(days=30))
    assert coach.agent.welcome_back(ALICE, planned.id) is False


def test_the_summary_never_claims_she_asked_to_remember_the_model_notes(coach, planned):
    """Campagne reelle V1 : « Vous m'aviez demandé de retenir : » suivi de sept notes du modele."""
    config, _ = coach.agent._session(ALICE, planned.id)
    notes = [f"note {n}" for n in range(1, 8)]
    coach.agent.graph.update_state(config, {"brief_draft": {"notes": notes}}, as_node="respond")
    confirm(coach, planned, say(coach, planned, PAUSE))
    recap = coach.agent.return_recap(ALICE, planned.id)
    assert "demandé de retenir" not in recap
    assert "Points notés pendant nos échanges : « note 5 » ; « note 6 » ; « note 7 »." in recap


def test_the_pause_reason_is_asked_in_her_own_words():
    from neurocoach.agent.prompts import _TASKS

    assert "à la première personne et avec ses mots" in _TASKS["classify_intent"]
