"""T11 et US-08 : pannes et sorties invalides du LLM -> message clair, donnees intactes."""

from __future__ import annotations

import pytest

from factories import ALICE
from neurocoach.domain.errors import USER_MESSAGES, DomainError, ErrorCode

VAGUE = "Je veux vendre des bougies artisanales, mais je ne sais pas par où commencer."
DETAILS = (
    "Tester si des personnes seraient intéressées. J'ai 30 minutes par jour. "
    "Mon budget est de 100 €. Proposez-moi un plan."
)


@pytest.fixture
def project(coach):
    return coach.app.coach.create_project(ALICE, "Bougies artisanales")


def _state(coach, project):
    return (
        coach.app.coach.get_snapshot(ALICE, project.id),
        coach.app.actions.get_pending(ALICE, project.id),
    )


@pytest.mark.parametrize("task", ["coach_turn", "clarify"])
def test_llm_unavailable_leaves_data_intact(coach, project, fake_llm, task):
    before = _state(coach, project)
    fake_llm.script(task, DomainError(ErrorCode.LLM_UNAVAILABLE))
    turn = coach.agent.send_message(ALICE, project.id, VAGUE)
    assert turn.reply == USER_MESSAGES[ErrorCode.LLM_UNAVAILABLE]
    assert turn.pending is None
    assert _state(coach, project) == before


def test_invalid_plan_creates_no_proposal(coach, project, fake_llm):
    coach.agent.send_message(ALICE, project.id, VAGUE)
    fake_llm.script("draft_plan", {"objective": "x", "phases": []})
    turn = coach.agent.send_message(ALICE, project.id, DETAILS)
    assert turn.reply == USER_MESSAGES[ErrorCode.LLM_OUTPUT_INVALID]
    assert turn.pending is None
    assert coach.app.actions.get_pending(ALICE, project.id) is None


def test_conversation_recovers_after_a_failure(coach, project, fake_llm):
    fake_llm.script("classify_intent", DomainError(ErrorCode.LLM_UNAVAILABLE))
    coach.agent.send_message(ALICE, project.id, VAGUE)
    retry = coach.agent.send_message(ALICE, project.id, VAGUE)
    # D-78 : la nouvelle tentative recoit une vraie reponse du modele, sans erreur.
    assert retry.error is None and retry.reply.startswith("[Réponse simulée]")


def test_reply_failure_falls_back_to_the_error_message(coach, project, fake_llm):
    coach.agent.send_message(ALICE, project.id, VAGUE)
    plan = coach.agent.send_message(ALICE, project.id, DETAILS)
    coach.agent.decide(ALICE, project.id, plan.pending["pending_action_id"], "confirm")
    # Projet actif : un message libre recoit une reponse redigee par le LLM, ici en panne.
    fake_llm.script("coach_reply", DomainError(ErrorCode.LLM_UNAVAILABLE))
    turn = coach.agent.send_message(ALICE, project.id, "Je réfléchis encore à tout ça.")
    assert turn.reply == USER_MESSAGES[ErrorCode.LLM_UNAVAILABLE]


def test_invalid_change_reference_is_explained(coach, project, fake_llm):
    coach.agent.send_message(ALICE, project.id, VAGUE)
    plan = coach.agent.send_message(ALICE, project.id, DETAILS)
    coach.agent.decide(ALICE, project.id, plan.pending["pending_action_id"], "confirm")
    fake_llm.script(
        "draft_change", {"changes": [{"op": "delete", "task_ref": "T9"}], "rationale": ""}
    )
    turn = coach.agent.send_message(ALICE, project.id, "Supprime T9")
    assert "Je ne trouve pas la tâche T9." in turn.reply
    assert coach.app.actions.get_pending(ALICE, project.id) is None


def test_empty_or_too_long_messages_are_refused(coach, project):
    for text in ("   ", "x" * 2001):
        with pytest.raises(DomainError) as error:
            coach.agent.send_message(ALICE, project.id, text)
        assert error.value.code is ErrorCode.VALIDATION_ERROR


def test_storage_failure_during_confirmation_is_reported(coach, project, monkeypatch):
    coach.agent.send_message(ALICE, project.id, VAGUE)
    plan = coach.agent.send_message(ALICE, project.id, DETAILS)

    def broken(*args, **kwargs):
        raise DomainError(ErrorCode.STORAGE_ERROR)

    monkeypatch.setattr(coach.app.actions, "confirm", broken)
    result = coach.agent.decide(ALICE, project.id, plan.pending["pending_action_id"], "confirm")
    assert result.notice == USER_MESSAGES[ErrorCode.STORAGE_ERROR]
    assert coach.app.coach.list_tasks(ALICE, project.id) == []
    assert result.reply == "La proposition attend toujours votre décision."
