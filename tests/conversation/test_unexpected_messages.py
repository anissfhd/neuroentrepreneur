"""Phase 4 : messages inattendus, demandes contradictoires et changements d'avis (faux LLM)."""

from __future__ import annotations

import pytest

from factories import ALICE
from neurocoach.domain.errors import USER_MESSAGES, ErrorCode
from neurocoach.domain.models import ActionStatus, TaskStatus

VAGUE = "Je veux vendre des bougies artisanales, mais je ne sais pas par où commencer."
DETAILS = (
    "Tester si des personnes seraient intéressées. J'ai 30 minutes par jour. "
    "Mon budget est de 100 €. Proposez-moi un plan."
)
FAILURES = {USER_MESSAGES[ErrorCode.LLM_UNAVAILABLE], USER_MESSAGES[ErrorCode.LLM_OUTPUT_INVALID]}


@pytest.fixture
def draft(coach):
    return coach.app.coach.create_project(ALICE, "Bougies artisanales", VAGUE)


@pytest.fixture
def planned(coach, draft):
    coach.agent.send_message(ALICE, draft.id, VAGUE)
    turn = coach.agent.send_message(ALICE, draft.id, DETAILS)
    coach.agent.decide(ALICE, draft.id, turn.pending["pending_action_id"], "confirm")
    return draft


def _say(coach, project, text):
    return coach.agent.send_message(ALICE, project.id, text)


@pytest.mark.parametrize(
    "text",
    [
        "???",
        "👍",
        "azertyuiop qsdfghjkl",
        "<script>alert('x')</script>",
        "**gras** [lien](javascript:alert(1))",
        "x" * 2000,
        "Je veux tout et son contraire : aller vite et prendre mon temps.",
    ],
)
def test_unexpected_messages_get_a_calm_answer_without_writing(coach, planned, text):
    before = coach.app.coach.get_snapshot(ALICE, planned.id)
    turn = _say(coach, planned, text)
    assert turn.reply and turn.reply not in FAILURES
    assert coach.app.coach.get_snapshot(ALICE, planned.id) == before
    # Le texte est conserve tel quel, sans interpretation (rendu sans HTML par Streamlit).
    assert coach.agent.history(ALICE, planned.id)[-2]["content"] == text


def test_emoji_agreement_keeps_the_proposal_pending(coach, draft):
    """D-44 : « 👍 » equivaut a « oui » et n'annule plus la proposition."""
    _say(coach, draft, VAGUE)
    action_id = _say(coach, draft, DETAILS).pending["pending_action_id"]
    turn = _say(coach, draft, "👍")
    assert turn.notice.startswith("Pour enregistrer cette proposition")
    assert coach.app.actions.get_action(ALICE, action_id).status is ActionStatus.PENDING


def test_contradictory_information_keeps_the_latest_value(coach, draft):
    _say(coach, draft, VAGUE)
    first = _say(coach, draft, DETAILS)
    # D-84 : le temps avec l'unite qu'elle a employee.
    assert "Temps disponible : environ 30 min par jour" in first.reply
    second = _say(coach, draft, "Finalement j'ai 2 h par jour.")
    assert "Temps disponible : environ 120 min par jour" in second.reply
    assert (
        coach.app.actions.get_action(ALICE, first.pending["pending_action_id"]).status
        is ActionStatus.CANCELLED
    )


def test_change_of_mind_on_a_status_is_undone_without_trace_of_error(coach, planned):
    done = _say(coach, planned, "J'ai terminé T1")
    coach.app.coach.undo_status_change(ALICE, done.undo_event_id)
    assert coach.app.coach.list_tasks(ALICE, planned.id)[0].status is TaskStatus.TODO
    again = _say(coach, planned, "Je commence T1")
    assert again.reply.startswith("T1 est maintenant en cours.")


def test_contradictory_status_request_is_explained(coach, planned):
    _say(coach, planned, "J'ai terminé T1")
    turn = _say(coach, planned, "T1 est bloquée car je doute")
    assert turn.reply.startswith("Ce changement de statut n'est pas possible")
    assert coach.app.coach.list_tasks(ALICE, planned.id)[0].status is TaskStatus.DONE


def test_add_then_cancel_then_delete_leaves_a_consistent_plan(coach, planned):
    add = _say(coach, planned, "Ajoute « Fixer un prix »")
    coach.agent.decide(ALICE, planned.id, add.pending["pending_action_id"], "cancel")
    delete = _say(coach, planned, "Supprime T3")
    coach.agent.decide(ALICE, planned.id, delete.pending["pending_action_id"], "confirm")
    refs = [task.ref for task in coach.app.coach.list_tasks(ALICE, planned.id)]
    assert refs == ["T1", "T2"]
    assert coach.app.actions.get_pending(ALICE, planned.id) is None
