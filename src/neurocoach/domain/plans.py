"""Commandes de modification d'un projet et moteur d'application (DOMAIN_CONTRACTS 4, 5, 11.3).

Toutes les ecritures soumises a confirmation (plan.create, plan.replan, task.create,
task.update, task.delete) s'expriment comme une ``ChangeCommand`` : une mise a jour
facultative du brief et une liste d'operations. Le meme moteur calcule l'apercu lors de la
demande et le nouvel etat lors de la confirmation.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import (
    Field,
    StringConstraints,
    field_validator,
    model_serializer,
    model_validator,
)

from neurocoach.domain.dependencies import Edge, validate_dependency_graph
from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.models import (
    ActionType,
    Criterion,
    Description,
    DomainModel,
    EstimateMinutes,
    ExitCriterion,
    MinutesPerDay,
    Outcome,
    Phase,
    PhaseTitle,
    Priority,
    Project,
    ProjectStatus,
    ShortItem,
    Task,
    TaskStatus,
    TaskTitle,
    build,
    new_id,
    updated,
)

KEY_PATTERN = r"^[a-z][a-z0-9_]{0,19}$"
Key = Annotated[str, StringConstraints(pattern=KEY_PATTERN)]


class _PartialModel(DomainModel):
    """Modele dont seuls les champs explicitement fournis sont serialises et appliques."""

    @model_serializer(mode="wrap")
    def _only_provided(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        return {name: value for name, value in data.items() if name in self.model_fields_set}

    def provided(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in sorted(self.model_fields_set)}


class BriefUpdate(_PartialModel):
    target_outcome: Outcome | None = None
    constraints: list[ShortItem] = Field(default_factory=list, max_length=10)
    facts: list[ShortItem] = Field(default_factory=list, max_length=10)
    assumptions: list[ShortItem] = Field(default_factory=list, max_length=10)
    available_minutes_per_day: MinutesPerDay | None = None
    horizon_date: date | None = None


class TaskChanges(_PartialModel):
    title: TaskTitle | None = None
    acceptance_criteria: Criterion | None = None
    description: Description | None = None
    priority: Priority | None = None
    estimate_minutes: EstimateMinutes | None = None
    due_date: date | None = None

    @model_validator(mode="after")
    def _check_fields(self) -> TaskChanges:
        if not self.model_fields_set:
            raise ValueError("aucune modification demandee")
        for required in ("title", "acceptance_criteria", "priority"):
            if required in self.model_fields_set and getattr(self, required) is None:
                raise ValueError(f"{required} ne peut pas etre vide")
        return self


class AddPhase(DomainModel):
    op: Literal["add_phase"] = "add_phase"
    key: Key
    title: PhaseTitle
    exit_criterion: ExitCriterion | None = None


class DeletePhase(DomainModel):
    op: Literal["delete_phase"] = "delete_phase"
    phase_id: str


class AddTask(DomainModel):
    op: Literal["add_task"] = "add_task"
    key: Key
    phase: str
    """Identifiant d'une phase existante ou cle d'une phase ajoutee dans la meme commande."""
    title: TaskTitle
    acceptance_criteria: Criterion
    description: Description | None = None
    priority: Priority = 3
    estimate_minutes: EstimateMinutes | None = None
    due_date: date | None = None
    depends_on: list[str] = Field(default_factory=list, max_length=10)
    """Identifiants de taches existantes ou cles de taches ajoutees dans la meme commande."""


class UpdateTask(DomainModel):
    op: Literal["update_task"] = "update_task"
    task_id: str
    changes: TaskChanges


class MoveTask(DomainModel):
    op: Literal["move_task"] = "move_task"
    task_id: str
    phase: str
    position: int | None = Field(default=None, ge=0)


class DeleteTask(DomainModel):
    op: Literal["delete_task"] = "delete_task"
    task_id: str


Operation = Annotated[
    AddPhase | DeletePhase | AddTask | UpdateTask | MoveTask | DeleteTask,
    Field(discriminator="op"),
]


class ChangeCommand(DomainModel):
    brief: BriefUpdate | None = None
    operations: list[Operation] = Field(default_factory=list, max_length=100)


DEADLINES_DISABLED_DETAIL = (
    "Les échéances sont désactivées dans vos préférences : rien n'a été proposé, car la "
    "demande ne portait que sur des dates."
)
DEADLINES_DISABLED_SINCE_DETAIL = (
    "Les échéances ont été désactivées depuis cette proposition : elle n'a pas été appliquée. "
    "Refaites la demande."
)


def has_deadlines(command: ChangeCommand) -> bool:
    """Une echeance de tache ou une date visee de projet figure-t-elle dans la commande ?"""
    if command.brief is not None and command.brief.horizon_date is not None:
        return True
    for op in command.operations:
        if isinstance(op, AddTask) and op.due_date is not None:
            return True
        if isinstance(op, UpdateTask) and "due_date" in op.changes.model_fields_set:
            return True
    return False


def strip_deadlines(command: ChangeCommand) -> ChangeCommand:
    """PF-05 (D-58) : retire toute echeance d'une commande quand l'utilisateur les a
    desactivees. Une modification qui ne portait que sur une date disparait ; les autres
    changements sont conserves a l'identique. Les donnees deja enregistrees ne changent pas."""
    operations: list[Operation] = []
    for op in command.operations:
        if isinstance(op, AddTask) and op.due_date is not None:
            operations.append(op.model_copy(update={"due_date": None}))
        elif isinstance(op, UpdateTask) and "due_date" in op.changes.model_fields_set:
            kept = {name: getattr(op.changes, name) for name in op.changes.model_fields_set}
            kept.pop("due_date")
            if kept:
                operations.append(op.model_copy(update={"changes": TaskChanges(**kept)}))
        else:
            operations.append(op)
    brief = command.brief
    if brief is not None and brief.horizon_date is not None:
        values = {name: getattr(brief, name) for name in brief.model_fields_set}
        values.pop("horizon_date", None)
        brief = BriefUpdate(**values) if values else None
    return ChangeCommand(brief=brief, operations=operations)


class Change(DomainModel):
    """Element d'apercu avant/apres (DOMAIN_CONTRACTS section 5.2)."""

    op: Literal["add", "update", "delete", "move"]
    entity: Literal["project", "phase", "task", "user"]
    ref: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None


@dataclass
class ProjectSnapshot:
    """Etat complet d'un projet : la base de travail du moteur."""

    project: Project
    phases: dict[str, Phase]
    tasks: dict[str, Task]
    dependencies: set[Edge] = field(default_factory=set)

    def copy(self) -> ProjectSnapshot:
        return ProjectSnapshot(
            self.project, dict(self.phases), dict(self.tasks), set(self.dependencies)
        )

    def ordered_phases(self) -> list[Phase]:
        return sorted(self.phases.values(), key=lambda phase: (phase.position, phase.id))

    def phase_tasks(self, phase_id: str) -> list[Task]:
        members = [task for task in self.tasks.values() if task.phase_id == phase_id]
        return sorted(members, key=lambda task: (task.position, task.number))

    def ordered_tasks(self) -> list[Task]:
        return [task for phase in self.ordered_phases() for task in self.phase_tasks(phase.id)]

    def versions(self) -> dict[str, Any]:
        return {
            "project": self.project.version,
            "tasks": {task_id: task.version for task_id, task in sorted(self.tasks.items())},
        }


@dataclass
class CommandResult:
    snapshot: ProjectSnapshot
    changes: list[Change]


def jsonable(value: Any) -> Any:
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list | tuple):
        return [jsonable(item) for item in value]
    return value


def _comparable(model: DomainModel) -> dict[str, Any]:
    return model.model_dump(exclude={"version", "updated_at"})


class _Engine:
    def __init__(self, snapshot: ProjectSnapshot, now: datetime) -> None:
        self.original = snapshot
        self.work = snapshot.copy()
        self.now = now
        self.phase_keys: dict[str, str] = {}
        self.task_keys: dict[str, str] = {}
        self.pending_dependencies: list[tuple[str, str]] = []
        self.changes: list[dict[str, Any]] = []

    # --- resolution -----------------------------------------------------------------
    def resolve_phase(self, ref: str) -> str:
        if ref in self.phase_keys:
            return self.phase_keys[ref]
        if ref in self.work.phases:
            return ref
        raise DomainError(ErrorCode.NOT_FOUND, "Phase introuvable.")

    def resolve_task(self, ref: str) -> str:
        task_id = self.task_keys.get(ref, ref)
        if task_id in self.work.tasks:
            return task_id
        raise DomainError(ErrorCode.NOT_FOUND, "Tâche introuvable.")

    def existing_task(self, task_id: str) -> Task:
        return self.work.tasks[self.resolve_task(task_id)]

    @staticmethod
    def protect(task: Task) -> None:
        if task.status is TaskStatus.DONE:
            raise DomainError(ErrorCode.DONE_TASK_PROTECTED, f"{task.ref}.")

    def record(self, op: str, entity: str, ref: str, before: Any = None, after: Any = None) -> None:
        self.changes.append(
            {
                "op": op,
                "entity": entity,
                "ref": ref,
                "before": {key: jsonable(value) for key, value in before.items()}
                if before is not None
                else None,
                "after": {key: jsonable(value) for key, value in after.items()}
                if after is not None
                else None,
            }
        )

    # --- operations -----------------------------------------------------------------
    def apply_brief(self, brief: BriefUpdate) -> None:
        project = self.work.project
        fields = brief.provided()
        before = {name: getattr(project, name) for name in fields}
        diff = [name for name, value in fields.items() if before[name] != value]
        if not diff:
            return
        self.work.project = updated(project, **fields)
        self.record(
            "update",
            "project",
            "projet",
            {name: before[name] for name in diff},
            {name: fields[name] for name in diff},
        )

    def add_phase(self, op: AddPhase) -> None:
        if op.key in self.phase_keys:
            raise DomainError(ErrorCode.VALIDATION_ERROR, f"Clé de phase en double : {op.key}.")
        position = max((phase.position for phase in self.work.phases.values()), default=-1) + 1
        phase = build(
            Phase,
            id=new_id("pha"),
            project_id=self.work.project.id,
            title=op.title,
            exit_criterion=op.exit_criterion,
            position=position,
        )
        self.work.phases[phase.id] = phase
        self.phase_keys[op.key] = phase.id
        self.record(
            "add",
            "phase",
            phase.title,
            None,
            {"title": phase.title, "exit_criterion": op.exit_criterion},
        )

    def delete_phase(self, op: DeletePhase) -> None:
        phase_id = self.resolve_phase(op.phase_id)
        if self.work.phase_tasks(phase_id):
            raise DomainError(ErrorCode.VALIDATION_ERROR, "La phase contient encore des tâches.")
        phase = self.work.phases.pop(phase_id)
        self.record("delete", "phase", phase.title, {"title": phase.title}, None)

    def add_task(self, op: AddTask) -> None:
        if op.key in self.task_keys:
            raise DomainError(ErrorCode.VALIDATION_ERROR, f"Clé de tâche en double : {op.key}.")
        phase_id = self.resolve_phase(op.phase)
        number = self.work.project.next_task_number
        self.work.project = updated(self.work.project, next_task_number=number + 1)
        position = max((task.position for task in self.work.phase_tasks(phase_id)), default=-1) + 1
        task = build(
            Task,
            id=new_id("tsk"),
            project_id=self.work.project.id,
            phase_id=phase_id,
            number=number,
            title=op.title,
            description=op.description,
            acceptance_criteria=op.acceptance_criteria,
            priority=op.priority,
            estimate_minutes=op.estimate_minutes,
            due_date=op.due_date,
            position=position,
            created_at=self.now,
            updated_at=self.now,
        )
        self.work.tasks[task.id] = task
        self.task_keys[op.key] = task.id
        self.pending_dependencies.extend((task.id, ref) for ref in op.depends_on)
        self.record(
            "add",
            "task",
            task.ref,
            None,
            {
                "title": task.title,
                "phase": self.work.phases[phase_id].title,
                "acceptance_criteria": task.acceptance_criteria,
                "priority": task.priority,
                "estimate_minutes": task.estimate_minutes,
                "due_date": task.due_date,
                "depends_on": [],
                "task_id": task.id,
            },
        )

    def update_task(self, op: UpdateTask) -> None:
        task = self.existing_task(op.task_id)
        fields = op.changes.provided()
        if set(fields) - {"description"}:
            self.protect(task)
        new_task = updated(task, **fields)
        diff = [name for name in fields if getattr(task, name) != getattr(new_task, name)]
        if not diff:
            return
        self.work.tasks[task.id] = new_task
        self.record(
            "update",
            "task",
            task.ref,
            {name: getattr(task, name) for name in diff},
            {name: getattr(new_task, name) for name in diff},
        )

    def move_task(self, op: MoveTask) -> None:
        task = self.existing_task(op.task_id)
        self.protect(task)
        target_id = self.resolve_phase(op.phase)
        siblings = [item for item in self.work.phase_tasks(target_id) if item.id != task.id]
        index = len(siblings) if op.position is None else min(op.position, len(siblings))
        current = self.work.phase_tasks(task.phase_id)
        if task.phase_id == target_id and current.index(task) == index:
            return
        moved = updated(task, phase_id=target_id)
        siblings.insert(index, moved)
        for position, item in enumerate(siblings):
            self.work.tasks[item.id] = updated(item, position=position)
        self.record(
            "move",
            "task",
            task.ref,
            {"phase": self.work.phases[task.phase_id].title},
            {"phase": self.work.phases[target_id].title, "position": index},
        )

    def delete_task(self, op: DeleteTask) -> None:
        task = self.existing_task(op.task_id)
        self.protect(task)
        del self.work.tasks[task.id]
        self.work.dependencies = {edge for edge in self.work.dependencies if task.id not in edge}
        self.record("delete", "task", task.ref, {"title": task.title}, None)

    # --- finalisation ---------------------------------------------------------------
    def finalize(self, *, activate: bool) -> CommandResult:
        self._resolve_dependencies()
        validate_dependency_graph(set(self.work.tasks), self.work.dependencies)
        self._check_duplicate_titles()
        self._renumber_positions()
        if activate and self.work.project.status is ProjectStatus.DRAFT:
            self.work.project = updated(self.work.project, status=ProjectStatus.ACTIVE)
        self._bump_versions()
        return CommandResult(self.work, [Change(**change) for change in self.changes])

    def _resolve_dependencies(self) -> None:
        for task_id, ref in self.pending_dependencies:
            if task_id not in self.work.tasks:
                continue
            dep_id = self.task_keys.get(ref, ref)
            if dep_id not in self.work.tasks:
                raise DomainError(ErrorCode.VALIDATION_ERROR, f"Dépendance inconnue : {ref}.")
            self.work.dependencies.add((task_id, dep_id))
        refs: dict[str, list[str]] = defaultdict(list)
        for task_id, dep_id in sorted(
            self.work.dependencies, key=lambda edge: self.work.tasks[edge[1]].number
        ):
            refs[task_id].append(self.work.tasks[dep_id].ref)
        for change in self.changes:
            if change["op"] == "add" and change["entity"] == "task":
                # L'identifiant interne ne sert qu'ici : il n'apparait jamais dans l'apercu.
                task_id = change["after"].pop("task_id")
                change["after"]["depends_on"] = refs.get(task_id, [])

    def _check_duplicate_titles(self) -> None:
        for phase_id in self.work.phases:
            seen: set[str] = set()
            for task in self.work.phase_tasks(phase_id):
                key = task.title.casefold()
                if key in seen:
                    raise DomainError(
                        ErrorCode.VALIDATION_ERROR,
                        f"Titre en double dans une phase : « {task.title} ».",
                    )
                seen.add(key)

    def _renumber_positions(self) -> None:
        for position, phase in enumerate(self.work.ordered_phases()):
            if phase.position != position:
                self.work.phases[phase.id] = updated(phase, position=position)
        for phase_id in self.work.phases:
            for position, task in enumerate(self.work.phase_tasks(phase_id)):
                if task.position != position:
                    self.work.tasks[task.id] = updated(task, position=position)

    def _bump_versions(self) -> None:
        changed = False
        for task_id, task in list(self.work.tasks.items()):
            before = self.original.tasks.get(task_id)
            if before is None:
                changed = True
            elif _comparable(before) != _comparable(task):
                self.work.tasks[task_id] = updated(
                    task, version=before.version + 1, updated_at=self.now
                )
                changed = True
        changed = changed or (
            set(self.work.tasks) != set(self.original.tasks)
            or self.work.phases != self.original.phases
            or self.work.dependencies != self.original.dependencies
            or _comparable(self.work.project) != _comparable(self.original.project)
        )
        if changed:
            self.work.project = updated(
                self.work.project,
                version=self.original.project.version + 1,
                updated_at=self.now,
            )


def apply_command(
    snapshot: ProjectSnapshot, command: ChangeCommand, *, now: datetime, activate: bool = False
) -> CommandResult:
    """Applique la commande a une copie de l'etat ; l'etat d'origine n'est jamais modifie."""
    engine = _Engine(snapshot, now)
    if command.brief is not None:
        engine.apply_brief(command.brief)
    handlers = {
        "add_phase": engine.add_phase,
        "delete_phase": engine.delete_phase,
        "add_task": engine.add_task,
        "update_task": engine.update_task,
        "move_task": engine.move_task,
        "delete_task": engine.delete_task,
    }
    for operation in command.operations:
        handlers[operation.op](operation)
    return engine.finalize(activate=activate)


_SINGLE_OPERATION = {
    ActionType.TASK_CREATE: AddTask,
    ActionType.TASK_UPDATE: UpdateTask,
    ActionType.TASK_DELETE: DeleteTask,
}


def validate_command_for(
    action_type: ActionType, snapshot: ProjectSnapshot, command: ChangeCommand, *, today: date
) -> None:
    """Forme attendue d'une commande selon le type d'action (DOMAIN_CONTRACTS 4.2)."""
    operations = command.operations
    if action_type is ActionType.PLAN_CREATE:
        if snapshot.project.status is not ProjectStatus.DRAFT:
            raise DomainError(
                ErrorCode.VALIDATION_ERROR, "Un plan existe déjà ; utilisez une replanification."
            )
        if any(not isinstance(op, AddPhase | AddTask) for op in operations):
            raise DomainError(ErrorCode.VALIDATION_ERROR, "Un nouveau plan ne fait qu'ajouter.")
        if not any(isinstance(op, AddTask) for op in operations):
            raise DomainError(ErrorCode.VALIDATION_ERROR, "Le plan ne contient aucune tâche.")
    elif action_type is ActionType.PLAN_REPLAN:
        if command.brief is not None or not operations:
            raise DomainError(ErrorCode.VALIDATION_ERROR, "Replanification vide ou invalide.")
    elif action_type in _SINGLE_OPERATION:
        expected = _SINGLE_OPERATION[action_type]
        if command.brief is not None or len(operations) != 1:
            raise DomainError(ErrorCode.VALIDATION_ERROR, "Une seule opération est attendue.")
        if not isinstance(operations[0], expected):
            raise DomainError(ErrorCode.VALIDATION_ERROR, "Opération incompatible avec l'action.")
        if isinstance(operations[0], AddTask) and operations[0].phase not in snapshot.phases:
            raise DomainError(ErrorCode.NOT_FOUND, "Phase introuvable.")
    else:
        raise DomainError(ErrorCode.VALIDATION_ERROR, "Cette action ne modifie pas un plan.")
    horizon = command.brief.horizon_date if command.brief is not None else None
    if horizon is not None and horizon < today:
        raise DomainError(ErrorCode.VALIDATION_ERROR, "L'horizon doit être aujourd'hui ou après.")


def apply_action_command(
    action_type: ActionType,
    snapshot: ProjectSnapshot,
    command: ChangeCommand,
    *,
    now: datetime,
    today: date,
) -> CommandResult:
    validate_command_for(action_type, snapshot, command, today=today)
    return apply_command(snapshot, command, now=now, activate=action_type is ActionType.PLAN_CREATE)


# --- Modification d'un plan propose avant confirmation (DOMAIN_CONTRACTS 5.5) -------------


class TaskEdit(DomainModel):
    title: TaskTitle | None = None
    acceptance_criteria: Criterion | None = None
    estimate_minutes: EstimateMinutes | None = None
    remove: bool = False


class PlanEdits(DomainModel):
    phase_titles: dict[str, PhaseTitle] = Field(default_factory=dict)
    tasks: dict[str, TaskEdit] = Field(default_factory=dict)


def revise_plan_command(command: ChangeCommand, edits: PlanEdits) -> ChangeCommand:
    """Applique les corrections de l'utilisateur a un plan propose ; rien n'est ecrit ici.

    Les taches retirees disparaissent aussi des dependances ; une phase videe est retiree.
    """
    phase_keys = {op.key for op in command.operations if isinstance(op, AddPhase)}
    task_keys = {op.key for op in command.operations if isinstance(op, AddTask)}
    unknown = (set(edits.phase_titles) - phase_keys) | (set(edits.tasks) - task_keys)
    if unknown:
        raise DomainError(ErrorCode.VALIDATION_ERROR, f"Éléments inconnus : {sorted(unknown)}.")
    removed = {key for key, edit in edits.tasks.items() if edit.remove}
    kept_tasks: list[AddTask] = []
    for op in command.operations:
        if isinstance(op, AddTask) and op.key not in removed:
            edit = edits.tasks.get(op.key, TaskEdit())
            changes = {
                name: value
                for name, value in edit.model_dump(exclude={"remove"}).items()
                if value is not None
            }
            changes["depends_on"] = [dep for dep in op.depends_on if dep not in removed]
            kept_tasks.append(op.model_copy(update=changes))
    if not kept_tasks:
        raise DomainError(ErrorCode.VALIDATION_ERROR, "Le plan doit garder au moins une tâche.")
    used_phases = {task.phase for task in kept_tasks}
    operations: list[AddPhase | AddTask] = []
    for op in command.operations:
        if isinstance(op, AddPhase) and op.key in used_phases:
            title = edits.phase_titles.get(op.key)
            operations.append(op.model_copy(update={"title": title}) if title else op)
            operations.extend(task for task in kept_tasks if task.phase == op.key)
    return ChangeCommand(brief=command.brief, operations=operations)


# --- Brouillon de plan produit par le LLM (DOMAIN_CONTRACTS 11.3) --------------------------


class PlanTaskDraft(DomainModel):
    key: Key
    title: TaskTitle
    acceptance_criteria: Criterion
    description: Description | None = None
    estimate_minutes: EstimateMinutes | None = None
    priority: Priority | None = None
    due_in_days: int | None = Field(default=None, ge=0, le=365)
    depends_on: list[Key] = Field(default_factory=list, max_length=10)


# D-83 : l'etape est numerotee a l'affichage ; un numero ecrit par le modele en tete du
# titre donnait « Étape 1 : 1) Vérifier la demande » (recette reelle du 12/11/2026).
PHASE_NUMBER = re.compile(
    r"^\s*(?:(?:[ée]tape|phase)\s*)?\d{1,2}\s*[).:\-" "\N{EN DASH}\N{EM DASH}" r"]\s*",
    re.IGNORECASE,
)


class PlanPhaseDraft(DomainModel):
    title: PhaseTitle
    exit_criterion: ExitCriterion | None = None
    tasks: list[PlanTaskDraft] = Field(min_length=1, max_length=7)

    @field_validator("title", mode="before")
    @classmethod
    def _drop_number(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = PHASE_NUMBER.sub("", value, count=1)
            return stripped if len(stripped.strip()) >= 3 else value
        return value


class PlanDraft(DomainModel):
    objective: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)
    ]
    assumptions: list[ShortItem] = Field(default_factory=list, max_length=5)
    phases: list[PlanPhaseDraft] = Field(min_length=1, max_length=5)
    # D-77 : risques ou prerequis importants, et comment realiser la premiere action.
    risks: list[ShortItem] = Field(default_factory=list, max_length=4)
    first_step: str | None = Field(default=None, max_length=300)
    # D-78 : presentation du plan par le modele (pourquoi il convient a cette personne).
    summary: str | None = Field(default=None, max_length=900)

    @model_validator(mode="after")
    def _check_structure(self) -> PlanDraft:
        tasks = [task for phase in self.phases for task in phase.tasks]
        if len(tasks) > 20:
            raise ValueError("un plan contient au plus 20 taches")
        keys = [task.key for task in tasks]
        if len(set(keys)) != len(keys):
            raise ValueError("cles de taches en double")
        for task in tasks:
            for dep in task.depends_on:
                if dep == task.key:
                    raise ValueError(f"la tache {task.key} depend d'elle-meme")
                if dep not in keys:
                    raise ValueError(f"dependance inconnue : {dep}")
        return self


def plan_create_command(
    draft: PlanDraft,
    *,
    today: date,
    deadlines_enabled: bool,
    brief: BriefUpdate | None = None,
) -> ChangeCommand:
    """Convertit un brouillon valide en commande ``plan.create`` (PF-05 pour les echeances)."""
    brief_fields = brief.provided() if brief is not None else {}
    brief_fields.setdefault("target_outcome", draft.objective)
    if draft.assumptions:
        brief_fields.setdefault("assumptions", list(draft.assumptions))
    operations: list[AddPhase | AddTask] = []
    for index, phase in enumerate(draft.phases, start=1):
        phase_key = f"phase{index}"
        operations.append(
            AddPhase(key=phase_key, title=phase.title, exit_criterion=phase.exit_criterion)
        )
        for task in phase.tasks:
            due = None
            if deadlines_enabled and task.due_in_days is not None:
                due = today + timedelta(days=task.due_in_days)
            operations.append(
                AddTask(
                    key=task.key,
                    phase=phase_key,
                    title=task.title,
                    acceptance_criteria=task.acceptance_criteria,
                    description=task.description,
                    priority=task.priority or 3,
                    estimate_minutes=task.estimate_minutes,
                    due_date=due,
                    depends_on=list(task.depends_on),
                )
            )
    return ChangeCommand(brief=BriefUpdate(**brief_fields), operations=operations)
