"""E-01 a E-03 : export, suppression d'un projet et de toutes les donnees."""

from __future__ import annotations

import json

import pytest

from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.models import ActionStatus, EventType


def test_export_contains_only_the_user_data(app, alice_project, bruno_project, conversations):
    user = alice_project.user_id
    thread = app.coach.get_conversation_thread(user, alice_project.project.id)
    conversations.messages[thread.id] = [{"role": "user", "content": "Bonjour"}]
    export = app.data.export_user_data(user)
    assert export["format"] == "neurocoach-export"
    assert export["user"]["id"] == user
    assert [item["project"]["id"] for item in export["projects"]] == [alice_project.project.id]
    assert len(export["projects"][0]["tasks"]) == 3
    assert len(export["projects"][0]["dependencies"]) == 2
    assert export["conversations"][0]["messages"] == [{"role": "user", "content": "Bonjour"}]
    serialized = json.dumps(export)
    assert bruno_project.project.id not in serialized
    assert bruno_project.user_id not in serialized
    assert app.coach.list_events(user)[-1].type is EventType.USER_DATA_EXPORTED


def test_project_deletion_requires_confirmation(app, alice_project):
    user, project = alice_project.user_id, alice_project.project
    action = app.actions.request_project_deletion(user, project.id)
    assert action.preview[0]["before"] == {"phases": 1, "tasks": 3}
    app.actions.cancel(user, action.id)
    assert app.coach.get_project(user, project.id) is not None


def test_project_deletion_removes_content_and_conversation(app, alice, conversations, make_planned):
    kept = make_planned(alice, "Projet conservé")
    removed = make_planned(alice, "Projet supprimé")
    thread = app.coach.get_conversation_thread(alice, removed.project.id)
    action = app.actions.request_project_deletion(alice, removed.project.id)
    outcome = app.actions.confirm(alice, action.id)
    assert outcome.result == {"deleted_project_id": removed.project.id, "threads_deleted": 1}
    assert conversations.deleted == [thread.id]
    with pytest.raises(DomainError) as error:
        app.coach.get_project(alice, removed.project.id)
    assert error.value.code is ErrorCode.NOT_FOUND
    assert [project.id for project in app.coach.list_projects(alice)] == [kept.project.id]
    assert len(app.coach.list_tasks(alice, kept.project.id)) == 3
    remaining = app.coach.list_events(alice)
    assert all(event.project_id != removed.project.id for event in remaining)
    assert any(event.type is EventType.PROJECT_DELETED for event in remaining)
    assert app.actions.get_action(alice, action.id).status is ActionStatus.APPLIED


def test_conversation_store_failure_keeps_everything(app, alice_project, conversations):
    user, project = alice_project.user_id, alice_project.project
    conversations.fail_on_delete = True
    action = app.actions.request_project_deletion(user, project.id)
    with pytest.raises(DomainError) as error:
        app.actions.confirm(user, action.id)
    assert error.value.code is ErrorCode.STORAGE_ERROR
    assert len(app.coach.list_tasks(user, project.id)) == 3
    assert app.actions.get_action(user, action.id).status is ActionStatus.FAILED


def test_user_data_deletion_spares_other_users(app, alice_project, bruno_project, conversations):
    user = alice_project.user_id
    app.coach.update_preferences(user, max_visible_tasks=1)
    thread = app.coach.get_conversation_thread(user, alice_project.project.id)
    action = app.actions.request_user_data_deletion(user)
    assert action.preview[0]["before"] == {"projects": 1, "tasks": 3}
    outcome = app.actions.confirm(user, action.id)
    assert outcome.result == {"projects": 1, "tasks": 3, "threads_deleted": 1}
    assert conversations.deleted == [thread.id]
    assert app.coach.list_projects(user) == []
    assert app.coach.list_events(user) == []
    assert app.coach.get_preferences(user).max_visible_tasks == 3
    # Seule trace conservee : l'action appliquee elle-meme.
    assert app.actions.get_action(user, action.id).status is ActionStatus.APPLIED
    # L'autre utilisateur est intact.
    other = bruno_project.user_id
    assert len(app.coach.list_tasks(other, bruno_project.project.id)) == 3
    assert app.coach.list_events(other)


def test_user_data_deletion_with_pending_project_action(app, alice_project):
    user, project = alice_project.user_id, alice_project.project
    pending_project = app.actions.request_project_deletion(user, project.id)
    action = app.actions.request_user_data_deletion(user)
    app.actions.confirm(user, action.id)
    assert app.coach.list_projects(user) == []
    with pytest.raises(DomainError):
        app.actions.get_action(user, pending_project.id)
