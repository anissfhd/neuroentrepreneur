"""D-58 : aucune echeance n'entre dans une proposition, ni n'est enregistree par une
confirmation, quand l'utilisateur a desactive les echeances. Regle appliquee par le code
metier (service des actions en attente), quelle que soit la voie d'entree.

Constat de la campagne finale gpt-5-mini : une replanification proposait des echeances
(17, 20 et 24/11) alors qu'elles etaient desactivees ; une confirmation les aurait enregistrees.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from factories import sample_plan
from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.models import ActionStatus, ActionType
from neurocoach.domain.plans import (
    DEADLINES_DISABLED_DETAIL,
    DEADLINES_DISABLED_SINCE_DETAIL,
    AddTask,
    BriefUpdate,
    ChangeCommand,
    TaskChanges,
    UpdateTask,
    has_deadlines,
    strip_deadlines,
)


def _replan(tasks, day):
    """Forme constatee : dates et durees melangees dans la meme replanification."""
    return ChangeCommand(
        operations=[
            UpdateTask(task_id=tasks[0].id, changes=TaskChanges(due_date=day)),
            UpdateTask(
                task_id=tasks[1].id,
                changes=TaskChanges(due_date=day + timedelta(days=3), estimate_minutes=15),
            ),
        ]
    )


# --- regle du domaine ------------------------------------------------------------------------


def test_strip_deadlines_keeps_every_other_change(alice_project):
    tasks = alice_project.tasks
    day = alice_project.project.created_at.date()
    command = _replan(tasks, day)
    command = command.model_copy(
        update={
            "brief": BriefUpdate(horizon_date=day, available_minutes_per_day=30),
            "operations": [
                *command.operations,
                AddTask(
                    key="n", phase="x", title="Nouvelle", acceptance_criteria="Faite", due_date=day
                ),
            ],
        }
    )
    assert has_deadlines(command)
    stripped = strip_deadlines(command)
    assert not has_deadlines(stripped)
    # La modification « date seule » disparait ; la date + duree garde la duree ; l'ajout reste.
    assert [op.op for op in stripped.operations] == ["update_task", "add_task"]
    assert stripped.operations[0].changes.model_fields_set == {"estimate_minutes"}
    assert stripped.operations[1].due_date is None
    assert stripped.brief.available_minutes_per_day == 30
    assert stripped.brief.horizon_date is None


# --- toutes les voies d'entree ----------------------------------------------------------------


def test_replan_proposal_is_stripped_and_confirmation_saves_no_date(app, alice_project):
    user, project, tasks = alice_project.user_id, alice_project.project, alice_project.tasks
    command = _replan(tasks, project.created_at.date())
    action = app.actions.request_change(user, project.id, ActionType.PLAN_REPLAN, command)
    assert action.payload["deadlines_removed"] is True
    assert all("due_date" not in (change.get("after") or {}) for change in action.preview)
    app.actions.confirm(user, action.id)
    saved = app.coach.list_tasks(user, project.id)
    assert all(task.due_date is None for task in saved)
    assert saved[1].estimate_minutes == 15  # le reste de la proposition est bien applique


def test_a_date_only_change_is_refused_explicitly(app, alice_project):
    user, project, task = alice_project.user_id, alice_project.project, alice_project.tasks[1]
    command = ChangeCommand(
        operations=[
            UpdateTask(task_id=task.id, changes=TaskChanges(due_date=project.created_at.date()))
        ]
    )
    with pytest.raises(DomainError) as error:
        app.actions.request_change(user, project.id, ActionType.TASK_UPDATE, command)
    assert error.value.code is ErrorCode.VALIDATION_ERROR
    assert DEADLINES_DISABLED_DETAIL in error.value.user_message
    assert app.actions.get_pending(user, project.id) is None


def test_confirmation_cannot_save_a_date_after_deadlines_are_disabled(app, alice_project):
    """La proposition datee a ete faite echeances activees ; elles sont desactivees avant le
    clic. Appliquer sans les dates trahirait l'apercu : refus explicite, rien n'est ecrit."""
    user, project, task = alice_project.user_id, alice_project.project, alice_project.tasks[1]
    app.coach.update_preferences(user, deadlines_enabled=True)
    day = project.created_at.date() + timedelta(days=4)
    command = ChangeCommand(
        operations=[UpdateTask(task_id=task.id, changes=TaskChanges(due_date=day))]
    )
    action = app.actions.request_change(user, project.id, ActionType.TASK_UPDATE, command)
    app.coach.update_preferences(user, deadlines_enabled=False)
    before = app.coach.list_tasks(user, project.id)
    with pytest.raises(DomainError) as error:
        app.actions.confirm(user, action.id)
    assert DEADLINES_DISABLED_SINCE_DETAIL in error.value.user_message
    assert app.actions.get_action(user, action.id).status is ActionStatus.FAILED
    assert app.coach.list_tasks(user, project.id) == before


def test_plan_creation_never_saves_a_project_date(app, alice, clock):
    project = app.coach.create_project(alice, "Projet")
    brief = BriefUpdate(available_minutes_per_day=30, horizon_date=clock.now().date())
    action = app.actions.request_plan(alice, project.id, sample_plan(), brief)
    assert all("horizon_date" not in (change.get("after") or {}) for change in action.preview)
    app.actions.confirm(alice, action.id)
    saved = app.coach.get_project(alice, project.id)
    assert saved.horizon_date is None and saved.available_minutes_per_day == 30


def test_revised_plan_proposal_is_stripped_too(app, alice):
    from neurocoach.domain.plans import PlanEdits

    project = app.coach.create_project(alice, "Projet")
    app.coach.update_preferences(alice, deadlines_enabled=True)
    draft = sample_plan()
    data = draft.model_dump()
    data["phases"][0]["tasks"][0]["due_in_days"] = 3
    action = app.actions.request_plan(alice, project.id, type(draft).model_validate(data))
    assert any("due_date" in (c.get("after") or {}) for c in action.preview)
    app.coach.update_preferences(alice, deadlines_enabled=False)
    key = action.payload["command"]["operations"][1]["key"]
    revised = app.actions.revise_plan(
        alice, action.id, PlanEdits(tasks={key: {"title": "Titre corrigé"}})
    )
    assert revised.payload["deadlines_removed"] is True
    app.actions.confirm(alice, revised.id)
    assert all(task.due_date is None for task in app.coach.list_tasks(alice, project.id))


def test_existing_dates_are_kept_but_never_added(app, alice_project):
    """Projets existants : une date deja enregistree n'est ni effacee ni modifiee."""
    user, project, task = alice_project.user_id, alice_project.project, alice_project.tasks[0]
    app.coach.update_preferences(user, deadlines_enabled=True)
    day = project.created_at.date() + timedelta(days=2)
    command = ChangeCommand(
        operations=[UpdateTask(task_id=task.id, changes=TaskChanges(due_date=day))]
    )
    app.actions.confirm(
        user, app.actions.request_change(user, project.id, ActionType.TASK_UPDATE, command).id
    )
    app.coach.update_preferences(user, deadlines_enabled=False)
    rename = ChangeCommand(
        operations=[UpdateTask(task_id=task.id, changes=TaskChanges(title="Renommée"))]
    )
    app.actions.confirm(
        user, app.actions.request_change(user, project.id, ActionType.TASK_UPDATE, rename).id
    )
    saved = app.coach.list_tasks(user, project.id)[0]
    assert (saved.title, saved.due_date) == ("Renommée", day)
