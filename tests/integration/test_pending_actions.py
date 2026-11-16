"""Cycle de vie des actions en attente : T03, T04, T05, T09, expiration, conflits, atomicite."""

from __future__ import annotations

import json
import sqlite3
from datetime import timedelta

import pytest

from factories import sample_plan
from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.models import ActionStatus, ActionType, ProjectStatus, TaskStatus
from neurocoach.domain.plans import ChangeCommand, TaskChanges, UpdateTask
from neurocoach.infra.repositories import SqliteRepository


@pytest.fixture
def draft(app, alice):
    project = app.coach.create_project(alice, "Bougies artisanales")
    return alice, project


def _tasks(app, user, project_id):
    return app.coach.list_tasks(user, project_id)


def test_request_does_not_write_business_data(app, draft):
    """T09 : tant que rien n'est confirme, l'etat metier est inchange."""
    user, project = draft
    before = app.coach.get_snapshot(user, project.id)
    action = app.actions.request_plan(user, project.id, sample_plan())
    assert action.status is ActionStatus.PENDING
    assert action.expires_at == action.created_at + timedelta(minutes=15)
    assert app.coach.get_snapshot(user, project.id) == before
    assert app.actions.get_pending(user, project.id) == action


def test_cancel_writes_nothing(app, draft):
    """T03 : refus du plan -> zero tache creee."""
    user, project = draft
    action = app.actions.request_plan(user, project.id, sample_plan())
    cancelled = app.actions.cancel(user, action.id)
    assert cancelled.status is ActionStatus.CANCELLED
    assert _tasks(app, user, project.id) == []
    assert app.coach.get_project(user, project.id).status is ProjectStatus.DRAFT
    # Annuler a nouveau est sans effet.
    assert app.actions.cancel(user, action.id).status is ActionStatus.CANCELLED


def test_confirm_applies_once(app, draft):
    """T04 : approbation -> taches creees une seule fois, journal complet."""
    user, project = draft
    action = app.actions.request_plan(user, project.id, sample_plan())
    outcome = app.actions.confirm(user, action.id)
    assert outcome.action.status is ActionStatus.APPLIED
    assert outcome.result["task_refs"] == ["T1", "T2", "T3"]
    assert len(_tasks(app, user, project.id)) == 3
    assert app.coach.get_project(user, project.id).status is ProjectStatus.ACTIVE
    types = [event.type.value for event in app.coach.list_events(user, project.id)]
    assert types[-2:] == ["plan.applied", "pending_action.applied"]


def test_double_confirmation_does_not_duplicate(app, draft):
    """T05 : double clic -> aucune duplication."""
    user, project = draft
    action = app.actions.request_plan(user, project.id, sample_plan())
    app.actions.confirm(user, action.id)
    with pytest.raises(DomainError) as error:
        app.actions.confirm(user, action.id)
    assert error.value.code is ErrorCode.ACTION_ALREADY_DECIDED
    assert error.value.data["status"] == "applied"
    assert len(_tasks(app, user, project.id)) == 3


def test_confirm_after_cancel_is_refused(app, draft):
    user, project = draft
    action = app.actions.request_plan(user, project.id, sample_plan())
    app.actions.cancel(user, action.id)
    with pytest.raises(DomainError) as error:
        app.actions.confirm(user, action.id)
    assert error.value.code is ErrorCode.ACTION_ALREADY_DECIDED
    assert _tasks(app, user, project.id) == []


def test_expired_action_is_blocked(app, draft, clock):
    user, project = draft
    action = app.actions.request_plan(user, project.id, sample_plan())
    clock.advance(timedelta(minutes=15))
    with pytest.raises(DomainError) as error:
        app.actions.confirm(user, action.id)
    assert error.value.code is ErrorCode.ACTION_EXPIRED
    assert app.actions.get_action(user, action.id).status is ActionStatus.EXPIRED
    assert _tasks(app, user, project.id) == []


def test_action_is_still_valid_just_before_expiry(app, draft, clock):
    user, project = draft
    action = app.actions.request_plan(user, project.id, sample_plan())
    clock.advance(timedelta(minutes=14, seconds=59))
    assert app.actions.confirm(user, action.id).action.status is ActionStatus.APPLIED


def test_new_proposal_supersedes_the_previous_one(app, draft):
    user, project = draft
    first = app.actions.request_plan(user, project.id, sample_plan())
    second = app.actions.request_plan(user, project.id, sample_plan(objective="Autre objectif"))
    assert app.actions.get_action(user, first.id).status is ActionStatus.SUPERSEDED
    assert app.actions.get_pending(user, project.id) == second
    with pytest.raises(DomainError) as error:
        app.actions.confirm(user, first.id)
    assert error.value.code is ErrorCode.ACTION_ALREADY_DECIDED
    app.actions.confirm(user, second.id)
    project_after = app.coach.get_project(user, project.id)
    assert project_after.target_outcome == "Autre objectif"


def test_version_conflict_requires_a_new_preview(app, alice_project):
    user, project = alice_project.user_id, alice_project.project
    target = alice_project.tasks[2]
    command = ChangeCommand(
        operations=[UpdateTask(task_id=target.id, changes=TaskChanges(title="Titre revu"))]
    )
    action = app.actions.request_change(user, project.id, ActionType.TASK_UPDATE, command)
    app.coach.set_task_status(user, alice_project.tasks[0].id, TaskStatus.DONE)
    with pytest.raises(DomainError) as error:
        app.actions.confirm(user, action.id)
    assert error.value.code is ErrorCode.VERSION_CONFLICT
    stored = app.actions.get_action(user, action.id)
    assert stored.status is ActionStatus.FAILED
    assert stored.result == {"error": "VERSION_CONFLICT"}
    titles = [task.title for task in _tasks(app, user, project.id)]
    assert "Titre revu" not in titles


def test_failure_during_application_leaves_no_partial_write(app, draft, monkeypatch):
    """I-09 / US-08 : panne apres l'ecriture des taches -> tout est annule."""
    user, project = draft
    action = app.actions.request_plan(user, project.id, sample_plan())
    original = SqliteRepository.insert_event

    def failing_insert(self, event):
        if event.type.value == "plan.applied":
            raise sqlite3.OperationalError("disque plein (simulé)")
        return original(self, event)

    monkeypatch.setattr(SqliteRepository, "insert_event", failing_insert)
    with pytest.raises(DomainError) as error:
        app.actions.confirm(user, action.id)
    assert error.value.code is ErrorCode.STORAGE_ERROR
    monkeypatch.undo()
    assert _tasks(app, user, project.id) == []
    assert app.coach.get_project(user, project.id).status is ProjectStatus.DRAFT
    stored = app.actions.get_action(user, action.id)
    assert stored.status is ActionStatus.FAILED
    assert stored.result == {"error": "STORAGE_ERROR"}


def test_domain_error_during_application_marks_action_failed(app, draft, monkeypatch):
    user, project = draft
    action = app.actions.request_plan(user, project.id, sample_plan())

    def refuse(*args, **kwargs):
        raise DomainError(ErrorCode.VALIDATION_ERROR, "Refus simulé.")

    monkeypatch.setattr("neurocoach.application.pending_actions.apply_action_command", refuse)
    with pytest.raises(DomainError) as error:
        app.actions.confirm(user, action.id)
    assert error.value.code is ErrorCode.VALIDATION_ERROR
    assert app.actions.get_action(user, action.id).status is ActionStatus.FAILED


def test_task_update_flow_with_due_date(app, alice_project):
    user, project = alice_project.user_id, alice_project.project
    task = alice_project.tasks[1]
    app.coach.update_preferences(user, deadlines_enabled=True)  # D-58 : dates seulement si activees
    due = project.created_at.date() + timedelta(days=5)
    command = ChangeCommand(
        operations=[UpdateTask(task_id=task.id, changes=TaskChanges(due_date=due))]
    )
    action = app.actions.request_change(user, project.id, ActionType.TASK_UPDATE, command)
    assert action.preview == [
        {
            "op": "update",
            "entity": "task",
            "ref": "T2",
            "before": {"due_date": None},
            "after": {"due_date": due.isoformat()},
        }
    ]
    outcome = app.actions.confirm(user, action.id)
    assert outcome.result["task_refs"] == ["T2"]
    updated_task = app.coach.list_tasks(user, project.id)[1]
    assert updated_task.due_date == due
    assert updated_task.version == task.version + 1


def test_request_without_any_change_is_refused(app, alice_project):
    user, project = alice_project.user_id, alice_project.project
    task = alice_project.tasks[0]
    command = ChangeCommand(
        operations=[UpdateTask(task_id=task.id, changes=TaskChanges(title=task.title))]
    )
    with pytest.raises(DomainError) as error:
        app.actions.request_change(user, project.id, ActionType.TASK_UPDATE, command)
    assert error.value.code is ErrorCode.VALIDATION_ERROR
    assert app.actions.get_pending(user, project.id) is None


def test_deletions_need_their_dedicated_request(app, alice_project):
    with pytest.raises(DomainError) as error:
        app.actions.request_change(
            alice_project.user_id,
            alice_project.project.id,
            ActionType.PROJECT_DELETE,
            ChangeCommand(),
        )
    assert error.value.code is ErrorCode.VALIDATION_ERROR


def test_stored_preview_has_no_internal_identifiers(app, draft):
    user, project = draft
    action = app.actions.request_plan(user, project.id, sample_plan())
    serialized = json.dumps(action.preview)
    for prefix in ("tsk_", "pha_", "prj_", "usr_"):
        assert prefix not in serialized


def test_unknown_action_is_not_found(app, alice):
    with pytest.raises(DomainError) as error:
        app.actions.confirm(alice, "pac_inexistante")
    assert error.value.code is ErrorCode.NOT_FOUND
