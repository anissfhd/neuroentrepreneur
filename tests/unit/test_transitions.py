"""T-01 a T-07 et U-02 : table de transitions des taches."""

from __future__ import annotations

from datetime import timedelta
from itertools import product

import pytest

from factories import NOW, make_task
from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.models import TaskStatus
from neurocoach.domain.transitions import ALLOWED_TRANSITIONS, apply_transition, revert_transition

LATER = NOW + timedelta(hours=1)
S = TaskStatus


def _reason_for(target: TaskStatus) -> str | None:
    return "Attente fournisseur" if target is S.BLOCKED else None


@pytest.mark.parametrize(("source", "target"), sorted(ALLOWED_TRANSITIONS))
def test_allowed_transitions_change_status_and_bump_version(source, target):
    task = make_task(status=source)
    outcome = apply_transition(task, target, reason=_reason_for(target), now=LATER)
    assert outcome.changed
    assert outcome.task.status is target
    assert outcome.task.version == task.version + 1
    assert outcome.task.updated_at == LATER
    assert (outcome.from_status, outcome.to_status) == (source, target)


def test_transition_matrix_is_exactly_the_contract():
    forbidden = {
        (a, b) for a, b in product(S, S) if a is not b and (a, b) not in ALLOWED_TRANSITIONS
    }
    assert forbidden == {(S.DONE, S.BLOCKED)}


def test_done_to_blocked_is_refused():
    with pytest.raises(DomainError) as error:
        apply_transition(make_task(status=S.DONE), S.BLOCKED, reason="Raison", now=LATER)
    assert error.value.code is ErrorCode.INVALID_TRANSITION


@pytest.mark.parametrize("status", [S.TODO, S.IN_PROGRESS, S.DONE])
def test_same_status_is_a_no_op(status):
    task = make_task(status=status)
    outcome = apply_transition(task, status, reason=None, now=LATER)
    assert not outcome.changed
    assert outcome.task == task


def test_blocked_again_with_new_reason_updates_reason():
    task = make_task(status=S.BLOCKED)
    outcome = apply_transition(task, S.BLOCKED, reason="Nouvelle raison", now=LATER)
    assert outcome.changed
    assert outcome.task.blocked_reason == "Nouvelle raison"
    assert outcome.previous_reason == task.blocked_reason
    assert outcome.task.version == task.version + 1


def test_blocked_again_with_same_reason_is_a_no_op():
    task = make_task(status=S.BLOCKED)
    outcome = apply_transition(task, S.BLOCKED, reason=task.blocked_reason, now=LATER)
    assert not outcome.changed


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_blocking_requires_a_reason(reason):
    with pytest.raises(DomainError) as error:
        apply_transition(make_task(), S.BLOCKED, reason=reason, now=LATER)
    assert error.value.code is ErrorCode.VALIDATION_ERROR


def test_blocking_reason_too_short_is_refused():
    with pytest.raises(DomainError) as error:
        apply_transition(make_task(), S.BLOCKED, reason="ab", now=LATER)
    assert error.value.code is ErrorCode.VALIDATION_ERROR


def test_leaving_blocked_clears_the_reason():
    outcome = apply_transition(make_task(status=S.BLOCKED), S.TODO, reason=None, now=LATER)
    assert outcome.task.blocked_reason is None


def test_done_sets_and_reopen_clears_completed_at():
    done = apply_transition(make_task(), S.DONE, reason=None, now=LATER).task
    assert done.completed_at == LATER
    reopened = apply_transition(done, S.TODO, reason=None, now=LATER + timedelta(minutes=5)).task
    assert reopened.completed_at is None


def test_reason_ignored_when_not_blocking():
    outcome = apply_transition(make_task(), S.IN_PROGRESS, reason="inutile", now=LATER)
    assert outcome.task.blocked_reason is None


def test_revert_restores_previous_blocked_state():
    task = make_task(status=S.BLOCKED)
    outcome = apply_transition(task, S.IN_PROGRESS, reason=None, now=LATER)
    reverted = revert_transition(
        outcome.task,
        from_status=outcome.from_status,
        previous_reason=outcome.previous_reason,
        previous_completed_at=outcome.previous_completed_at,
        now=LATER,
    )
    assert reverted.status is S.BLOCKED
    assert reverted.blocked_reason == task.blocked_reason
    assert reverted.version == outcome.task.version + 1


def test_revert_restores_original_completion_time():
    task = make_task(status=S.DONE)
    reopened = apply_transition(task, S.TODO, reason=None, now=LATER)
    reverted = revert_transition(
        reopened.task,
        from_status=S.DONE,
        previous_reason=None,
        previous_completed_at=reopened.previous_completed_at,
        now=LATER,
    )
    assert reverted.completed_at == NOW


def test_revert_to_done_without_previous_time_uses_now():
    reverted = revert_transition(
        make_task(), from_status=S.DONE, previous_reason=None, previous_completed_at=None, now=LATER
    )
    assert reverted.completed_at == LATER
