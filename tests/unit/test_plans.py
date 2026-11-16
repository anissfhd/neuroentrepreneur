"""Brouillons de plan, commandes et moteur d'application (sections 4, 5 et 11.3)."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from pydantic import ValidationError

from factories import NOW, TODAY, make_phase, make_snapshot, make_task, sample_plan
from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.models import ActionType, ProjectStatus, TaskStatus
from neurocoach.domain.plans import (
    AddPhase,
    AddTask,
    BriefUpdate,
    ChangeCommand,
    DeletePhase,
    DeleteTask,
    MoveTask,
    PlanDraft,
    TaskChanges,
    UpdateTask,
    apply_action_command,
    apply_command,
    plan_create_command,
    validate_command_for,
)

S = TaskStatus


def _apply(action_type, snapshot, command):
    return apply_action_command(action_type, snapshot, command, now=NOW, today=TODAY)


def _code(excinfo) -> ErrorCode:
    return excinfo.value.code


# --- brouillon de plan ----------------------------------------------------------------


def _draft(tasks_per_phase, phases=1, **task_overrides):
    return {
        "objective": "Objectif de test",
        "phases": [
            {
                "title": f"Phase {p}",
                "tasks": [
                    {
                        "key": f"t{p}_{i}",
                        "title": f"Tâche {p}-{i}",
                        "acceptance_criteria": "Critère vérifiable",
                        **task_overrides,
                    }
                    for i in range(tasks_per_phase)
                ],
            }
            for p in range(phases)
        ],
    }


def test_plan_draft_accepts_reference_plan():
    assert len(sample_plan().phases[0].tasks) == 3


@pytest.mark.parametrize(
    "payload",
    [
        _draft(1, phases=0),
        _draft(1, phases=6),
        _draft(8, phases=1),
        _draft(7, phases=3),  # 21 taches
        _draft(0, phases=1),
    ],
)
def test_plan_draft_bounds(payload):
    with pytest.raises(ValidationError):
        PlanDraft.model_validate(payload)


def test_plan_draft_refuses_duplicate_keys_unknown_and_self_dependencies():
    duplicate = _draft(2)
    duplicate["phases"][0]["tasks"][1]["key"] = "t0_0"
    unknown = _draft(1, depends_on=["absente"])
    self_dep = _draft(1, depends_on=["t0_0"])
    for payload in (duplicate, unknown, self_dep):
        with pytest.raises(ValidationError):
            PlanDraft.model_validate(payload)


def test_plan_draft_refuses_missing_acceptance_criteria():
    payload = _draft(1)
    del payload["phases"][0]["tasks"][0]["acceptance_criteria"]
    with pytest.raises(ValidationError):
        PlanDraft.model_validate(payload)


def test_plan_create_command_ignores_deadlines_when_disabled():
    command = plan_create_command(sample_plan(), today=TODAY, deadlines_enabled=False)
    tasks = [op for op in command.operations if isinstance(op, AddTask)]
    assert all(task.due_date is None for task in tasks)
    assert all(task.priority == 3 for task in tasks)
    assert command.brief is not None
    assert command.brief.target_outcome == sample_plan().objective
    assert command.brief.assumptions == ["30 minutes par jour"]


def test_plan_create_command_converts_relative_deadlines():
    command = plan_create_command(sample_plan(), today=TODAY, deadlines_enabled=True)
    dues = [op.due_date for op in command.operations if isinstance(op, AddTask)]
    assert dues == [TODAY + timedelta(days=2), TODAY + timedelta(days=4), None]


def test_plan_create_command_keeps_explicit_brief():
    brief = BriefUpdate(target_outcome="Résultat choisi", available_minutes_per_day=30)
    command = plan_create_command(sample_plan(), today=TODAY, deadlines_enabled=False, brief=brief)
    assert command.brief is not None
    assert command.brief.target_outcome == "Résultat choisi"
    assert command.brief.available_minutes_per_day == 30


# --- plan.create ----------------------------------------------------------------------


def test_plan_create_builds_hierarchy_and_activates_project():
    snapshot = make_snapshot(phases=[], status=ProjectStatus.DRAFT)
    command = plan_create_command(sample_plan(), today=TODAY, deadlines_enabled=False)
    result = _apply(ActionType.PLAN_CREATE, snapshot, command)
    new = result.snapshot
    assert new.project.status is ProjectStatus.ACTIVE
    assert new.project.version == snapshot.project.version + 1
    assert new.project.next_task_number == 4
    tasks = new.ordered_tasks()
    assert [task.ref for task in tasks] == ["T1", "T2", "T3"]
    assert [task.position for task in tasks] == [0, 1, 2]
    assert all(task.status is S.TODO and task.version == 1 for task in tasks)
    assert new.dependencies == {(tasks[1].id, tasks[0].id), (tasks[2].id, tasks[1].id)}
    # L'etat d'origine n'est jamais modifie.
    assert snapshot.tasks == {} and snapshot.project.status is ProjectStatus.DRAFT


def test_plan_create_preview_is_readable_and_free_of_internal_ids():
    snapshot = make_snapshot(phases=[], status=ProjectStatus.DRAFT)
    command = plan_create_command(sample_plan(), today=TODAY, deadlines_enabled=False)
    result = _apply(ActionType.PLAN_CREATE, snapshot, command)
    kinds = [(change.op, change.entity) for change in result.changes]
    assert kinds[0] == ("update", "project")
    assert ("add", "phase") in kinds
    task_changes = [change for change in result.changes if change.entity == "task"]
    assert task_changes[1].after["depends_on"] == ["T1"]
    serialized = json.dumps([change.model_dump(mode="json") for change in result.changes])
    for prefix in ("tsk_", "pha_", "prj_", "usr_"):
        assert prefix not in serialized


def test_plan_create_allows_forward_dependencies():
    payload = _draft(2)
    payload["phases"][0]["tasks"][0]["depends_on"] = ["t0_1"]
    command = plan_create_command(
        PlanDraft.model_validate(payload), today=TODAY, deadlines_enabled=False
    )
    result = _apply(
        ActionType.PLAN_CREATE, make_snapshot(phases=[], status=ProjectStatus.DRAFT), command
    )
    first, second = result.snapshot.ordered_tasks()
    assert result.snapshot.dependencies == {(first.id, second.id)}


def test_plan_create_refuses_cycles():
    payload = _draft(2)
    payload["phases"][0]["tasks"][0]["depends_on"] = ["t0_1"]
    payload["phases"][0]["tasks"][1]["depends_on"] = ["t0_0"]
    command = plan_create_command(
        PlanDraft.model_validate(payload), today=TODAY, deadlines_enabled=False
    )
    with pytest.raises(DomainError) as error:
        _apply(
            ActionType.PLAN_CREATE, make_snapshot(phases=[], status=ProjectStatus.DRAFT), command
        )
    assert _code(error) is ErrorCode.CYCLE_DETECTED


def test_plan_create_refuses_duplicate_titles_in_a_phase():
    payload = _draft(2)
    payload["phases"][0]["tasks"][1]["title"] = payload["phases"][0]["tasks"][0]["title"].upper()
    command = plan_create_command(
        PlanDraft.model_validate(payload), today=TODAY, deadlines_enabled=False
    )
    with pytest.raises(DomainError) as error:
        _apply(
            ActionType.PLAN_CREATE, make_snapshot(phases=[], status=ProjectStatus.DRAFT), command
        )
    assert _code(error) is ErrorCode.VALIDATION_ERROR


def test_plan_create_on_active_project_is_refused():
    command = plan_create_command(sample_plan(), today=TODAY, deadlines_enabled=False)
    with pytest.raises(DomainError) as error:
        _apply(ActionType.PLAN_CREATE, make_snapshot([make_task(1)]), command)
    assert _code(error) is ErrorCode.VALIDATION_ERROR


def test_plan_create_only_adds_and_needs_a_task():
    draft = make_snapshot(phases=[], status=ProjectStatus.DRAFT)
    with pytest.raises(DomainError):
        _apply(
            ActionType.PLAN_CREATE,
            draft,
            ChangeCommand(operations=[AddPhase(key="p", title="Phase seule")]),
        )
    with pytest.raises(DomainError):
        _apply(ActionType.PLAN_CREATE, draft, ChangeCommand(operations=[DeleteTask(task_id="x")]))


def test_horizon_in_the_past_is_refused():
    command = plan_create_command(
        sample_plan(),
        today=TODAY,
        deadlines_enabled=False,
        brief=BriefUpdate(horizon_date=TODAY - timedelta(days=1)),
    )
    with pytest.raises(DomainError) as error:
        _apply(
            ActionType.PLAN_CREATE, make_snapshot(phases=[], status=ProjectStatus.DRAFT), command
        )
    assert _code(error) is ErrorCode.VALIDATION_ERROR


# --- modifications et replanification -----------------------------------------------


def _three_tasks():
    t1, t2, t3 = make_task(1, S.DONE), make_task(2), make_task(3)
    return make_snapshot([t1, t2, t3], dependencies={(t3.id, t2.id), (t2.id, t1.id)})


def test_update_task_records_diff_and_bumps_versions():
    snapshot = _three_tasks()
    t2 = make_task(2)
    command = ChangeCommand(
        operations=[UpdateTask(task_id=t2.id, changes=TaskChanges(title="Nouveau titre"))]
    )
    result = _apply(ActionType.TASK_UPDATE, snapshot, command)
    assert result.snapshot.tasks[t2.id].title == "Nouveau titre"
    assert result.snapshot.tasks[t2.id].version == 2
    assert result.snapshot.tasks[t2.id].updated_at == NOW
    assert result.snapshot.project.version == snapshot.project.version + 1
    change = result.changes[0]
    assert (change.op, change.ref, change.before, change.after) == (
        "update",
        "T2",
        {"title": "Tâche 2"},
        {"title": "Nouveau titre"},
    )


def test_update_without_real_difference_records_nothing():
    snapshot = _three_tasks()
    command = ChangeCommand(
        operations=[UpdateTask(task_id=make_task(2).id, changes=TaskChanges(title="Tâche 2"))]
    )
    result = _apply(ActionType.TASK_UPDATE, snapshot, command)
    assert result.changes == []
    assert result.snapshot.project.version == snapshot.project.version


def test_due_date_can_be_set_and_cleared():
    snapshot = make_snapshot([make_task(1, due_date=TODAY)])
    command = ChangeCommand(
        operations=[UpdateTask(task_id=make_task(1).id, changes=TaskChanges(due_date=None))]
    )
    result = _apply(ActionType.TASK_UPDATE, snapshot, command)
    assert result.snapshot.tasks[make_task(1).id].due_date is None


@pytest.mark.parametrize(
    "operation",
    [
        UpdateTask(task_id=make_task(1).id, changes=TaskChanges(title="Autre titre")),
        UpdateTask(task_id=make_task(1).id, changes=TaskChanges(due_date=TODAY)),
        DeleteTask(task_id=make_task(1).id),
        MoveTask(task_id=make_task(1).id, phase=make_phase().id, position=2),
    ],
)
def test_done_tasks_are_protected(operation):
    """R-CONF-03 et I-11 : une replanification ne touche jamais une tache terminee."""
    with pytest.raises(DomainError) as error:
        _apply(ActionType.PLAN_REPLAN, _three_tasks(), ChangeCommand(operations=[operation]))
    assert _code(error) is ErrorCode.DONE_TASK_PROTECTED


def test_description_of_done_task_can_change():
    command = ChangeCommand(
        operations=[
            UpdateTask(task_id=make_task(1).id, changes=TaskChanges(description="Note ajoutée"))
        ]
    )
    result = _apply(ActionType.TASK_UPDATE, _three_tasks(), command)
    assert result.snapshot.tasks[make_task(1).id].description == "Note ajoutée"


def test_delete_task_removes_dependencies_both_ways_and_renumbers_positions():
    snapshot = _three_tasks()
    t2 = make_task(2)
    result = _apply(
        ActionType.TASK_DELETE, snapshot, ChangeCommand(operations=[DeleteTask(task_id=t2.id)])
    )
    assert t2.id not in result.snapshot.tasks
    assert result.snapshot.dependencies == set()
    assert [task.position for task in result.snapshot.ordered_tasks()] == [0, 1]
    assert result.changes[0].before == {"title": "Tâche 2"}


def test_replan_adds_phase_and_task_with_dependencies():
    snapshot = _three_tasks()
    command = ChangeCommand(
        operations=[
            AddPhase(key="vente", title="Première vente"),
            AddTask(
                key="annonce",
                phase="vente",
                title="Publier une annonce",
                acceptance_criteria="Annonce en ligne",
                depends_on=[make_task(3).id],
            ),
        ]
    )
    result = _apply(ActionType.PLAN_REPLAN, snapshot, command)
    new_task = next(task for task in result.snapshot.tasks.values() if task.number == 4)
    assert (new_task.id, make_task(3).id) in result.snapshot.dependencies
    assert result.snapshot.project.next_task_number == 5
    assert result.changes[-1].after["depends_on"] == ["T3"]


def test_move_task_between_phases():
    first, second = make_phase(0), make_phase(1, title="Phase deux")
    t1 = make_task(1, phase_id=first.id)
    t2 = make_task(2, phase_id=first.id)
    t3 = make_task(3, phase_id=second.id, position=0)
    snapshot = make_snapshot([t1, t2, t3], phases=[first, second])
    command = ChangeCommand(operations=[MoveTask(task_id=t1.id, phase=second.id, position=0)])
    result = _apply(ActionType.PLAN_REPLAN, snapshot, command)
    assert [task.number for task in result.snapshot.phase_tasks(second.id)] == [1, 3]
    assert [task.number for task in result.snapshot.phase_tasks(first.id)] == [2]
    assert result.snapshot.tasks[t2.id].position == 0
    assert result.changes[0].after == {"phase": "Phase deux", "position": 0}


def test_move_to_same_place_is_a_no_op():
    t1, t2 = make_task(1), make_task(2)
    snapshot = make_snapshot([t1, t2])
    command = ChangeCommand(operations=[MoveTask(task_id=t2.id, phase=make_phase().id, position=1)])
    assert _apply(ActionType.PLAN_REPLAN, snapshot, command).changes == []


def test_delete_phase_only_when_empty():
    first, second = make_phase(0), make_phase(1)
    snapshot = make_snapshot([make_task(1, phase_id=first.id)], phases=[first, second])
    result = _apply(
        ActionType.PLAN_REPLAN,
        snapshot,
        ChangeCommand(operations=[DeletePhase(phase_id=second.id)]),
    )
    assert second.id not in result.snapshot.phases
    with pytest.raises(DomainError) as error:
        _apply(
            ActionType.PLAN_REPLAN,
            snapshot,
            ChangeCommand(operations=[DeletePhase(phase_id=first.id)]),
        )
    assert _code(error) is ErrorCode.VALIDATION_ERROR


def test_unknown_references_are_not_found():
    snapshot = _three_tasks()
    for operation in (
        DeleteTask(task_id="tsk_" + "f" * 32),
        AddTask(key="x", phase="pha_inconnue", title="Titre ok", acceptance_criteria="Critère"),
    ):
        with pytest.raises(DomainError) as error:
            _apply(ActionType.PLAN_REPLAN, snapshot, ChangeCommand(operations=[operation]))
        assert _code(error) is ErrorCode.NOT_FOUND


def test_unknown_dependency_and_duplicate_keys_are_invalid():
    snapshot = _three_tasks()
    unknown_dep = AddTask(
        key="x",
        phase=make_phase().id,
        title="Titre ok",
        acceptance_criteria="Critère",
        depends_on=["inconnue"],
    )
    duplicate = [
        AddPhase(key="p", title="Phase A"),
        AddPhase(key="p", title="Phase B"),
    ]
    duplicate_task = [
        AddTask(key="k", phase=make_phase().id, title="Titre un", acceptance_criteria="Critère"),
        AddTask(key="k", phase=make_phase().id, title="Titre deux", acceptance_criteria="Critère"),
    ]
    for operations in ([unknown_dep], duplicate, duplicate_task):
        with pytest.raises(DomainError) as error:
            _apply(ActionType.PLAN_REPLAN, snapshot, ChangeCommand(operations=operations))
        assert _code(error) is ErrorCode.VALIDATION_ERROR


def test_dependency_on_a_task_deleted_in_the_same_command_is_invalid():
    snapshot = _three_tasks()
    command = ChangeCommand(
        operations=[
            AddTask(
                key="x",
                phase=make_phase().id,
                title="Titre ok",
                acceptance_criteria="Critère",
                depends_on=[make_task(3).id],
            ),
            DeleteTask(task_id=make_task(3).id),
        ]
    )
    with pytest.raises(DomainError) as error:
        _apply(ActionType.PLAN_REPLAN, snapshot, command)
    assert _code(error) is ErrorCode.VALIDATION_ERROR


def test_replan_creating_a_cycle_is_refused():
    def add(key: str, other: str) -> AddTask:
        return AddTask(
            key=key,
            phase=make_phase().id,
            title=f"Titre {key}",
            acceptance_criteria="Critère",
            depends_on=[other],
        )

    command = ChangeCommand(operations=[add("x", "y"), add("y", "x")])
    with pytest.raises(DomainError) as error:
        _apply(ActionType.PLAN_REPLAN, _three_tasks(), command)
    assert _code(error) is ErrorCode.CYCLE_DETECTED


def test_new_task_may_depend_on_existing_chain():
    t1, t2 = make_task(1), make_task(2)
    snapshot = make_snapshot([t1, t2], dependencies={(t2.id, t1.id)})
    command = ChangeCommand(
        operations=[
            AddTask(
                key="x",
                phase=make_phase().id,
                title="Titre ok",
                acceptance_criteria="Critère",
                depends_on=[t2.id],
            ),
        ]
    )
    result = _apply(ActionType.PLAN_REPLAN, snapshot, command)
    assert len(result.snapshot.dependencies) == 2


# --- forme des commandes --------------------------------------------------------------


@pytest.mark.parametrize(
    ("action_type", "command"),
    [
        (ActionType.TASK_CREATE, ChangeCommand()),
        (ActionType.TASK_UPDATE, ChangeCommand(operations=[DeleteTask(task_id="x")])),
        (
            ActionType.TASK_DELETE,
            ChangeCommand(brief=BriefUpdate(facts=["x"]), operations=[DeleteTask(task_id="x")]),
        ),
        (ActionType.PLAN_REPLAN, ChangeCommand()),
        (ActionType.PROJECT_DELETE, ChangeCommand()),
        (ActionType.USER_DELETE_DATA, ChangeCommand()),
    ],
)
def test_command_shapes_are_checked(action_type, command):
    with pytest.raises(DomainError) as error:
        validate_command_for(action_type, _three_tasks(), command, today=TODAY)
    assert _code(error) is ErrorCode.VALIDATION_ERROR


def test_task_create_requires_existing_phase():
    command = ChangeCommand(
        operations=[
            AddTask(key="x", phase="nouvelle", title="Titre ok", acceptance_criteria="Ok ok")
        ]
    )
    with pytest.raises(DomainError) as error:
        validate_command_for(ActionType.TASK_CREATE, _three_tasks(), command, today=TODAY)
    assert _code(error) is ErrorCode.NOT_FOUND


def test_task_create_appends_task():
    command = ChangeCommand(
        operations=[
            AddTask(key="x", phase=make_phase().id, title="Titre ok", acceptance_criteria="Ok ok")
        ]
    )
    result = _apply(ActionType.TASK_CREATE, _three_tasks(), command)
    new = [task for task in result.snapshot.tasks.values() if task.number == 4]
    assert new and new[0].position == 3


# --- modifications partielles ---------------------------------------------------------


def test_task_changes_require_a_field_and_refuse_empty_required_fields():
    with pytest.raises(ValidationError):
        TaskChanges()
    for name in ("title", "acceptance_criteria", "priority"):
        with pytest.raises(ValidationError):
            TaskChanges(**{name: None})


def test_partial_models_serialize_only_provided_fields_and_round_trip():
    changes = TaskChanges(due_date=None, priority=4)
    dumped = changes.model_dump(mode="json")
    assert dumped == {"due_date": None, "priority": 4}
    command = ChangeCommand(operations=[UpdateTask(task_id="tsk_x", changes=changes)])
    restored = ChangeCommand.model_validate(json.loads(json.dumps(command.model_dump(mode="json"))))
    restored_changes = restored.operations[0].changes
    assert restored_changes.provided() == {"due_date": None, "priority": 4}


def test_apply_command_without_operations_is_neutral():
    snapshot = _three_tasks()
    result = apply_command(snapshot, ChangeCommand(), now=NOW)
    assert result.changes == []
    assert result.snapshot.project == snapshot.project
