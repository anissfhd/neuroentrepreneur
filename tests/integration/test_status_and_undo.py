"""Changements de statut directs, journalises et annulables (R-CONF-01a, T-05, U-01 a U-04)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.models import ActionType, EventType, TaskStatus
from neurocoach.domain.plans import ChangeCommand, DeleteTask

S = TaskStatus


def test_status_change_is_direct_and_journaled(app, alice_project):
    user = alice_project.user_id
    task = alice_project.tasks[0]
    change = app.coach.set_task_status(user, task.id, S.DONE)
    assert change.changed
    assert change.task.status is S.DONE
    assert change.task.version == task.version + 1
    assert app.actions.get_pending(user, alice_project.project.id) is None
    events = app.coach.list_events(user, alice_project.project.id)
    last = events[-1]
    assert last.id == change.event_id
    assert last.type is EventType.TASK_STATUS_CHANGED
    assert last.payload["from"] == "todo"
    assert last.payload["to"] == "done"
    assert last.payload["task_ref"] == "T1"


def test_same_status_creates_no_event(app, alice_project):
    user = alice_project.user_id
    task = alice_project.tasks[0]
    count = len(app.coach.list_events(user))
    change = app.coach.set_task_status(user, task.id, S.TODO)
    assert not change.changed
    assert len(app.coach.list_events(user)) == count


def test_starting_a_task_with_unmet_dependency_warns(app, alice_project):
    user = alice_project.user_id
    change = app.coach.set_task_status(user, alice_project.tasks[1].id, S.IN_PROGRESS)
    assert change.task.status is S.IN_PROGRESS
    assert change.warnings == ["UNMET_DEPENDENCIES"]
    assert change.unmet_dependencies == ["T1"]


def test_blocking_requires_reason(app, alice_project):
    with pytest.raises(DomainError) as error:
        app.coach.set_task_status(alice_project.user_id, alice_project.tasks[0].id, S.BLOCKED)
    assert error.value.code is ErrorCode.VALIDATION_ERROR


def test_invalid_transition_is_refused(app, alice_project):
    user = alice_project.user_id
    task = alice_project.tasks[0]
    app.coach.set_task_status(user, task.id, S.DONE)
    with pytest.raises(DomainError) as error:
        app.coach.set_task_status(user, task.id, S.BLOCKED, "Raison quelconque")
    assert error.value.code is ErrorCode.INVALID_TRANSITION


def test_undo_restores_previous_state(app, alice_project, clock):
    user = alice_project.user_id
    task = alice_project.tasks[0]
    blocked = app.coach.set_task_status(user, task.id, S.BLOCKED, "Attente d'un fournisseur")
    clock.advance(timedelta(minutes=1))
    done = app.coach.set_task_status(user, task.id, S.DONE)
    reverted = app.coach.undo_status_change(user, done.event_id)
    assert reverted.status is S.BLOCKED
    assert reverted.blocked_reason == "Attente d'un fournisseur"
    assert reverted.completed_at is None
    assert reverted.version == done.task.version + 1
    last = app.coach.list_events(user)[-1]
    assert last.type is EventType.TASK_STATUS_REVERTED
    assert last.reverts_event_id == done.event_id
    # U-01 : un changement plus ancien n'est plus annulable.
    with pytest.raises(DomainError) as error:
        app.coach.undo_status_change(user, blocked.event_id)
    assert error.value.code is ErrorCode.INVALID_TRANSITION


def test_undo_of_reopening_restores_completion_time(app, alice_project, clock):
    user = alice_project.user_id
    task = alice_project.tasks[0]
    done = app.coach.set_task_status(user, task.id, S.DONE)
    clock.advance(timedelta(hours=2))
    reopened = app.coach.set_task_status(user, task.id, S.TODO)
    restored = app.coach.undo_status_change(user, reopened.event_id)
    assert restored.status is S.DONE
    assert restored.completed_at == done.task.completed_at


def test_undo_cannot_be_applied_twice_or_undone(app, alice_project):
    user = alice_project.user_id
    change = app.coach.set_task_status(user, alice_project.tasks[0].id, S.DONE)
    app.coach.undo_status_change(user, change.event_id)
    with pytest.raises(DomainError) as error:
        app.coach.undo_status_change(user, change.event_id)
    assert error.value.code is ErrorCode.INVALID_TRANSITION
    revert_event = app.coach.list_events(user)[-1]
    with pytest.raises(DomainError) as error:
        app.coach.undo_status_change(user, revert_event.id)
    assert error.value.code is ErrorCode.INVALID_TRANSITION


def test_only_status_events_can_be_undone(app, alice_project):
    user = alice_project.user_id
    created = app.coach.list_events(user, alice_project.project.id)[0]
    with pytest.raises(DomainError) as error:
        app.coach.undo_status_change(user, created.id)
    assert error.value.code is ErrorCode.VALIDATION_ERROR


def test_undo_after_task_deletion_is_not_found(app, alice_project):
    user, project = alice_project.user_id, alice_project.project
    task = alice_project.tasks[2]
    change = app.coach.set_task_status(user, task.id, S.IN_PROGRESS)
    action = app.actions.request_change(
        user,
        project.id,
        ActionType.TASK_DELETE,
        ChangeCommand(operations=[DeleteTask(task_id=task.id)]),
    )
    app.actions.confirm(user, action.id)
    with pytest.raises(DomainError) as error:
        app.coach.undo_status_change(user, change.event_id)
    assert error.value.code is ErrorCode.NOT_FOUND
