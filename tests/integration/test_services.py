"""Services de lecture, projets, preferences et donnees de demonstration."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from factories import ALICE, sample_plan
from neurocoach.demo import DEMO_ALICE_ID, DEMO_BRUNO_ID, seed_demo
from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.models import (
    ActionType,
    EventType,
    ProjectStatus,
    ResponseLength,
    TaskStatus,
)
from neurocoach.domain.plans import BriefUpdate, ChangeCommand, TaskChanges, UpdateTask

S = TaskStatus


def test_create_project_validates_and_journals(app, alice):
    project = app.coach.create_project(alice, "Bougies")
    assert project.status is ProjectStatus.DRAFT
    assert app.coach.list_events(alice, project.id)[0].type is EventType.PROJECT_CREATED
    with pytest.raises(DomainError) as error:
        app.coach.create_project(alice, "ab")
    assert error.value.code is ErrorCode.VALIDATION_ERROR


def test_unknown_user_is_not_found(app):
    with pytest.raises(DomainError) as error:
        app.coach.create_project("usr_inconnu", "Projet fantôme")
    assert error.value.code is ErrorCode.NOT_FOUND


def test_ensure_user_is_idempotent(app):
    first = app.coach.ensure_user(ALICE, "Alice")
    assert app.coach.ensure_user(ALICE, "Autre nom") == first
    assert [user.id for user in app.coach.list_users()] == [ALICE]


def test_list_tasks_filters_and_pagination(app, alice_project):
    user, project = alice_project.user_id, alice_project.project
    app.coach.set_task_status(user, alice_project.tasks[0].id, S.DONE)
    assert [task.number for task in app.coach.list_tasks(user, project.id, status="done")] == [1]
    assert [task.number for task in app.coach.list_tasks(user, project.id, limit=1, offset=1)] == [
        2
    ]
    phase_id = alice_project.tasks[0].phase_id
    assert len(app.coach.list_tasks(user, project.id, phase_id=phase_id)) == 3
    for limit, offset in ((0, 0), (51, 0), (10, -1)):
        with pytest.raises(DomainError):
            app.coach.list_tasks(user, project.id, limit=limit, offset=offset)


def test_progress_one_out_of_three(app, alice_project):
    """T07 au niveau des services : 33,3 % calcule depuis la base."""
    user, project = alice_project.user_id, alice_project.project
    app.coach.set_task_status(user, alice_project.tasks[0].id, S.DONE)
    summary = app.coach.get_progress(user, project.id)
    assert summary.percent == Decimal("33.3")
    assert (summary.done, summary.total) == (1, 3)


def test_preferences_update_is_journaled_and_respected(app, alice_project):
    user, project = alice_project.user_id, alice_project.project
    assert len(app.coach.get_next_actions(user, project.id).items) == 1  # dependances en chaine
    prefs = app.coach.update_preferences(
        user, response_length="court", max_visible_tasks=1, one_question_at_a_time=True
    )
    assert prefs.response_length is ResponseLength.COURT
    event = app.coach.list_events(user)[-1]
    assert event.type is EventType.PREFERENCES_UPDATED
    assert event.payload["changed"] == {"response_length": "court", "max_visible_tasks": 1}
    count = len(app.coach.list_events(user))
    app.coach.update_preferences(user, max_visible_tasks=1)
    assert len(app.coach.list_events(user)) == count


@pytest.mark.parametrize(
    "changes", [{"inconnu": 1}, {"max_visible_tasks": 5}, {"display_timezone": "Nulle/Part"}]
)
def test_invalid_preferences_are_refused(app, alice, changes):
    with pytest.raises(DomainError) as error:
        app.coach.update_preferences(alice, **changes)
    assert error.value.code is ErrorCode.VALIDATION_ERROR


def test_next_actions_follow_dependencies(app, alice_project):
    user, project = alice_project.user_id, alice_project.project
    assert [item.ref for item in app.coach.get_next_actions(user, project.id).items] == ["T1"]
    app.coach.set_task_status(user, alice_project.tasks[0].id, S.DONE)
    assert [item.ref for item in app.coach.get_next_actions(user, project.id).items] == ["T2"]


def test_deadlines_preference_drives_urgency(app, alice_project):
    user, project = alice_project.user_id, alice_project.project
    task = alice_project.tasks[0]
    today = project.created_at.date()
    command = ChangeCommand(
        operations=[UpdateTask(task_id=task.id, changes=TaskChanges(due_date=today))]
    )
    app.coach.update_preferences(user, deadlines_enabled=True)
    app.actions.confirm(
        user, app.actions.request_change(user, project.id, ActionType.TASK_UPDATE, command).id
    )
    assert app.coach.get_next_actions(user, project.id).items[0].factors["urgence"] == 10
    # Echeances desactivees ensuite : la date enregistree est conservee, mais ignoree (D-58).
    app.coach.update_preferences(user, deadlines_enabled=False)
    assert app.coach.get_next_actions(user, project.id).items[0].factors["urgence"] == 0
    assert app.coach.list_tasks(user, project.id)[0].due_date == today


def test_workload_alert_from_project_brief(app, alice, clock):
    project = app.coach.create_project(alice, "Projet chargé")
    app.coach.update_preferences(alice, deadlines_enabled=True)  # date visee : D-58
    brief = BriefUpdate(
        available_minutes_per_day=5, horizon_date=clock.now().date() + timedelta(days=2)
    )
    action = app.actions.request_plan(alice, project.id, sample_plan(), brief)
    app.actions.confirm(alice, action.id)
    alert = app.coach.get_workload_alert(alice, project.id)
    assert alert is not None
    assert alert.level == "depassement"
    assert alert.unestimated_tasks == 2


def test_demo_seed_is_idempotent(app):
    first = seed_demo(app)
    assert len(first["created"]) == 2
    assert seed_demo(app)["created"] == []
    alice_projects = app.coach.list_projects(DEMO_ALICE_ID)
    assert [project.title for project in alice_projects] == ["Bougies artisanales"]
    summary = app.coach.get_progress(DEMO_ALICE_ID, alice_projects[0].id)
    assert (summary.done, summary.total) == (1, 3)
    bruno_projects = app.coach.list_projects(DEMO_BRUNO_ID)
    assert bruno_projects[0].status is ProjectStatus.DRAFT
