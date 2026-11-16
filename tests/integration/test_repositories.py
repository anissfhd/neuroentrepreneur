"""Repositories : aller-retour des entites, versions, numeros jamais reutilises (I-06)."""

from __future__ import annotations

import sqlite3

import pytest

from neurocoach.application.base import unit_of_work
from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.models import ActionType, TaskStatus
from neurocoach.domain.plans import AddTask, ChangeCommand, DeleteTask


def test_snapshot_round_trip(app, alice_project):
    snapshot = app.coach.get_snapshot(alice_project.user_id, alice_project.project.id)
    with unit_of_work(app.database, write=False) as repo:
        again = repo.load_snapshot(alice_project.user_id, alice_project.project.id)
    assert again == snapshot
    assert len(snapshot.tasks) == 3
    assert len(snapshot.dependencies) == 2
    assert snapshot.project.constraints == []


def test_project_lists_and_threads(app, alice):
    first = app.coach.create_project(alice, "Premier projet")
    second = app.coach.create_project(alice, "Second projet", "Une idée")
    assert [project.id for project in app.coach.list_projects(alice)] == [first.id, second.id]
    thread = app.coach.get_conversation_thread(alice, first.id)
    assert thread.id.startswith("thr_")
    assert app.coach.get_conversation_thread(alice, first.id) == thread


def test_task_numbers_are_never_reused(app, alice_project):
    user, project = alice_project.user_id, alice_project.project
    last = alice_project.tasks[-1]
    delete = app.actions.request_change(
        user,
        project.id,
        ActionType.TASK_DELETE,
        ChangeCommand(operations=[DeleteTask(task_id=last.id)]),
    )
    app.actions.confirm(user, delete.id)
    phase_id = last.phase_id
    create = app.actions.request_change(
        user,
        project.id,
        ActionType.TASK_CREATE,
        ChangeCommand(
            operations=[
                AddTask(key="n", phase=phase_id, title="Nouvelle tâche", acceptance_criteria="Fait")
            ]
        ),
    )
    app.actions.confirm(user, create.id)
    numbers = [task.number for task in app.coach.list_tasks(user, project.id)]
    assert numbers == [1, 2, 4]


def test_events_are_listed_in_order(app, alice_project):
    events = app.coach.list_events(alice_project.user_id, alice_project.project.id)
    types = [event.type.value for event in events]
    assert types == [
        "project.created",
        "pending_action.created",
        "plan.applied",
        "pending_action.applied",
    ]


def test_storage_errors_become_domain_errors(app):
    with pytest.raises(DomainError) as error, unit_of_work(app.database, write=True) as repo:
        repo.conn.execute("INSERT INTO table_absente VALUES (1)")
    assert error.value.code is ErrorCode.STORAGE_ERROR


def test_task_status_round_trip(app, alice_project):
    user = alice_project.user_id
    task = alice_project.tasks[0]
    app.coach.set_task_status(user, task.id, TaskStatus.BLOCKED, "Attente d'un devis")
    with unit_of_work(app.database, write=False) as repo:
        stored = repo.get_task(user, task.id)
    assert stored.status is TaskStatus.BLOCKED
    assert stored.blocked_reason == "Attente d'un devis"


def test_one_pending_action_per_project_is_enforced_by_the_schema(app, alice_project):
    user, project = alice_project.user_id, alice_project.project
    app.actions.request_project_deletion(user, project.id)
    with pytest.raises(sqlite3.IntegrityError), app.database.transaction(write=True) as conn:
        conn.execute(
            "INSERT INTO pending_actions (id, user_id, project_id, action_type, payload_json, "
            "preview_json, expected_versions_json, status, idempotency_key, created_at, "
            "expires_at) VALUES ('pac_x', ?, ?, 'task.delete', '{}', '[]', '{}', 'pending', "
            "'cle-unique', 'x', 'x')",
            (user, project.id),
        )
