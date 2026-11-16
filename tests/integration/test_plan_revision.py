"""DOMAIN_CONTRACTS 5.5 : correction d'un plan propose par les services (sans graphe)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from factories import sample_plan
from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.models import ActionStatus, ActionType
from neurocoach.domain.plans import ChangeCommand, DeleteTask, PlanEdits, TaskEdit


@pytest.fixture
def proposal(app, alice):
    project = app.coach.create_project(alice, "Bougies artisanales")
    return project, app.actions.request_plan(alice, project.id, sample_plan())


def test_view_lists_editable_phases_and_tasks(app, alice, proposal):
    _, action = proposal
    view = app.actions.plan_draft_view(alice, action.id)
    assert [phase["title"] for phase in view] == ["Valider l'intérêt"]
    assert [task["key"] for task in view[0]["tasks"]] == ["client", "questions", "entretiens"]


def test_revision_supersedes_and_writes_nothing(app, alice, proposal):
    project, action = proposal
    revised = app.actions.revise_plan(
        alice, action.id, PlanEdits(tasks={"client": TaskEdit(title="Décrire ma cliente")})
    )
    assert app.actions.get_action(alice, action.id).status is ActionStatus.SUPERSEDED
    assert revised.status is ActionStatus.PENDING
    assert app.coach.list_tasks(alice, project.id) == []
    assert revised.preview != action.preview


def test_only_a_pending_and_valid_plan_can_be_revised(app, alice, proposal, alice_project, clock):
    _, action = proposal
    edits = PlanEdits(tasks={"client": TaskEdit(title="Autre titre")})
    other = app.actions.request_change(
        alice,
        alice_project.project.id,
        ActionType.TASK_DELETE,
        ChangeCommand(operations=[DeleteTask(task_id=alice_project.tasks[2].id)]),
    )
    with pytest.raises(DomainError) as error:
        app.actions.revise_plan(alice, other.id, edits)
    assert error.value.code is ErrorCode.VALIDATION_ERROR
    clock.advance(timedelta(minutes=15))
    with pytest.raises(DomainError) as error:
        app.actions.revise_plan(alice, action.id, edits)
    assert error.value.code is ErrorCode.ACTION_EXPIRED
    app.actions.cancel(alice, action.id)
    with pytest.raises(DomainError) as error:
        app.actions.plan_draft_view(alice, action.id)
    assert error.value.code is ErrorCode.ACTION_ALREADY_DECIDED


def test_revision_of_another_users_proposal_is_not_found(app, bruno, proposal):
    _, action = proposal
    with pytest.raises(DomainError) as error:
        app.actions.revise_plan(bruno, action.id, PlanEdits())
    assert error.value.code is ErrorCode.NOT_FOUND
