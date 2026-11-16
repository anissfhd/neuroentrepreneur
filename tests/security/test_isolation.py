"""T10 : aucun acces aux donnees d'un autre utilisateur (I-02, I-03).

Chaque service appele par Alice avec un identifiant appartenant a Bruno doit repondre
NOT_FOUND, sans ecrire quoi que ce soit chez Bruno.
"""

from __future__ import annotations

import pytest

from factories import sample_plan
from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.models import ActionStatus, ActionType, TaskStatus
from neurocoach.domain.plans import (
    AddTask,
    ChangeCommand,
    DeleteTask,
    MoveTask,
    TaskChanges,
    UpdateTask,
)


@pytest.fixture
def world(app, alice_project, bruno_project):
    bruno = bruno_project.user_id
    bruno_task = bruno_project.tasks[0]
    status_event = app.coach.set_task_status(bruno, bruno_task.id, TaskStatus.IN_PROGRESS)
    bruno_action = app.actions.request_project_deletion(bruno, bruno_project.project.id)
    before = {
        "snapshot": app.coach.get_snapshot(bruno, bruno_project.project.id),
        "events": app.coach.list_events(bruno),
        "action": app.actions.get_action(bruno, bruno_action.id),
    }
    return {
        "alice": alice_project,
        "bruno": bruno_project,
        "bruno_task": bruno_task,
        "bruno_event": status_event.event_id,
        "bruno_action": bruno_action,
        "before": before,
    }


def _cross_user_calls(app, world):
    alice = world["alice"].user_id
    alice_project = world["alice"].project.id
    alice_phase = world["alice"].tasks[0].phase_id
    bruno_project = world["bruno"].project.id
    bruno_task = world["bruno_task"]
    action_id = world["bruno_action"].id
    update = ChangeCommand(
        operations=[UpdateTask(task_id=bruno_task.id, changes=TaskChanges(title="Piratage"))]
    )
    return {
        "get_project": lambda: app.coach.get_project(alice, bruno_project),
        "get_snapshot": lambda: app.coach.get_snapshot(alice, bruno_project),
        "list_tasks": lambda: app.coach.list_tasks(alice, bruno_project),
        "get_progress": lambda: app.coach.get_progress(alice, bruno_project),
        "get_next_actions": lambda: app.coach.get_next_actions(alice, bruno_project),
        "get_workload_alert": lambda: app.coach.get_workload_alert(alice, bruno_project),
        "list_events": lambda: app.coach.list_events(alice, bruno_project),
        "get_thread": lambda: app.coach.get_conversation_thread(alice, bruno_project),
        "set_task_status": lambda: app.coach.set_task_status(alice, bruno_task.id, "done"),
        "undo_status_change": lambda: app.coach.undo_status_change(alice, world["bruno_event"]),
        "request_plan": lambda: app.actions.request_plan(alice, bruno_project, sample_plan()),
        "request_change_on_other_project": lambda: app.actions.request_change(
            alice, bruno_project, ActionType.TASK_UPDATE, update
        ),
        "update_foreign_task_from_own_project": lambda: app.actions.request_change(
            alice, alice_project, ActionType.TASK_UPDATE, update
        ),
        "delete_foreign_task_from_own_project": lambda: app.actions.request_change(
            alice,
            alice_project,
            ActionType.TASK_DELETE,
            ChangeCommand(operations=[DeleteTask(task_id=bruno_task.id)]),
        ),
        "move_foreign_task_into_own_phase": lambda: app.actions.request_change(
            alice,
            alice_project,
            ActionType.PLAN_REPLAN,
            ChangeCommand(operations=[MoveTask(task_id=bruno_task.id, phase=alice_phase)]),
        ),
        "add_task_to_foreign_phase": lambda: app.actions.request_change(
            alice,
            alice_project,
            ActionType.PLAN_REPLAN,
            ChangeCommand(
                operations=[
                    AddTask(
                        key="x",
                        phase=bruno_task.phase_id,
                        title="Intrusion",
                        acceptance_criteria="Aucun",
                    )
                ]
            ),
        ),
        "depend_on_foreign_task": lambda: app.actions.request_change(
            alice,
            alice_project,
            ActionType.PLAN_REPLAN,
            ChangeCommand(
                operations=[
                    AddTask(
                        key="x",
                        phase=alice_phase,
                        title="Dépendance",
                        acceptance_criteria="Aucun",
                        depends_on=[bruno_task.id],
                    )
                ]
            ),
        ),
        "request_project_deletion": lambda: app.actions.request_project_deletion(
            alice, bruno_project
        ),
        "get_action": lambda: app.actions.get_action(alice, action_id),
        "confirm": lambda: app.actions.confirm(alice, action_id),
        "cancel": lambda: app.actions.cancel(alice, action_id),
    }


CALLS = [
    "get_project",
    "get_snapshot",
    "list_tasks",
    "get_progress",
    "get_next_actions",
    "get_workload_alert",
    "list_events",
    "get_thread",
    "set_task_status",
    "undo_status_change",
    "request_plan",
    "request_change_on_other_project",
    "update_foreign_task_from_own_project",
    "delete_foreign_task_from_own_project",
    "move_foreign_task_into_own_phase",
    "add_task_to_foreign_phase",
    "depend_on_foreign_task",
    "request_project_deletion",
    "get_action",
    "confirm",
    "cancel",
]


@pytest.mark.parametrize("name", CALLS)
def test_cross_user_access_is_not_found_and_writes_nothing(app, world, name):
    call = _cross_user_calls(app, world)[name]
    with pytest.raises(DomainError) as error:
        call()
    assert error.value.code in {ErrorCode.NOT_FOUND, ErrorCode.VALIDATION_ERROR}
    if name not in {"depend_on_foreign_task"}:
        assert error.value.code is ErrorCode.NOT_FOUND
    bruno = world["bruno"].user_id
    before = world["before"]
    assert app.coach.get_snapshot(bruno, world["bruno"].project.id) == before["snapshot"]
    assert app.coach.list_events(bruno) == before["events"]
    action = app.actions.get_action(bruno, world["bruno_action"].id)
    assert action == before["action"]
    assert action.status is ActionStatus.PENDING


def test_all_cross_user_calls_are_covered(app, world):
    assert set(_cross_user_calls(app, world)) == set(CALLS)


def test_each_user_sees_only_their_projects(app, world):
    alice = world["alice"].user_id
    bruno = world["bruno"].user_id
    assert [p.id for p in app.coach.list_projects(alice)] == [world["alice"].project.id]
    assert [p.id for p in app.coach.list_projects(bruno)] == [world["bruno"].project.id]
    assert all(event.user_id == alice for event in app.coach.list_events(alice))
