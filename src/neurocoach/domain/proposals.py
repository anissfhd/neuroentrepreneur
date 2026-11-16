"""Proposition de modification produite par le LLM et sa conversion en commande (11.4).

Le LLM ne designe les taches que par leur reference d'affichage (« T3 ») et les phases par
leur titre. La conversion se fait ici, contre l'etat reel du projet : une reference inconnue
leve NOT_FOUND et une valeur invalide leve VALIDATION_ERROR. Aucune ecriture n'a lieu.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, ValidationError

from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.models import ActionType, DomainModel, validation_detail
from neurocoach.domain.plans import (
    AddPhase,
    AddTask,
    ChangeCommand,
    DeleteTask,
    MoveTask,
    Operation,
    ProjectSnapshot,
    TaskChanges,
    UpdateTask,
)

TaskRef = Annotated[str, StringConstraints(pattern=r"^T[1-9][0-9]{0,3}$")]
_REF = re.compile(r"^T([1-9][0-9]{0,3})$")


class ProposedFields(DomainModel):
    """Champs explicites (D-41) : un schema ferme, accepte par les sorties structurees strictes.

    ``None`` signifie « inchange » ; effacer une echeance passe par l'edition directe.
    """

    title: str | None = None
    acceptance_criteria: str | None = None
    description: str | None = None
    priority: int | None = None
    estimate_minutes: int | None = None
    due_date: date | None = None
    depends_on: list[TaskRef] = Field(default_factory=list)

    def provided(self) -> dict[str, Any]:
        values = self.model_dump(exclude={"depends_on"})
        return {name: value for name, value in values.items() if value is not None}


class ProposedChange(DomainModel):
    op: Literal["add", "update", "delete", "move"]
    task_ref: TaskRef | None = None
    phase_title: str | None = Field(default=None, max_length=80)
    fields: ProposedFields = Field(default_factory=ProposedFields)


class ChangeProposal(DomainModel):
    changes: list[ProposedChange] = Field(min_length=1, max_length=10)
    rationale: str = Field(default="", max_length=300)


def _task_id(snapshot: ProjectSnapshot, ref: str | None) -> str:
    match = _REF.match(ref or "")
    if match is not None:
        number = int(match.group(1))
        for task in snapshot.tasks.values():
            if task.number == number:
                return task.id
    # Sans reference, la demande est imprecise (correction R0) : le graphe pose une question.
    raise DomainError(
        ErrorCode.NOT_FOUND,
        f"Je ne trouve pas la tâche {ref or '(non précisée)'}.",
        unclear=ref is None,
    )


def proposal_to_command(
    snapshot: ProjectSnapshot, proposal: ChangeProposal, *, replan: bool
) -> tuple[ActionType, ChangeCommand]:
    """Traduit la proposition ; le type d'action depend du nombre et de la nature des changes."""
    phases_by_title = {phase.title.casefold(): phase.id for phase in snapshot.phases.values()}
    new_phase_keys: dict[str, str] = {}
    operations: list[Operation] = []

    def phase_ref(title: str | None) -> str:
        if title is None:
            first = snapshot.ordered_phases()
            if not first:
                raise DomainError(ErrorCode.VALIDATION_ERROR, "Aucune phase n'existe encore.")
            return first[0].id
        key = title.strip().casefold()
        if key in phases_by_title:
            return phases_by_title[key]
        if key not in new_phase_keys:
            new_phase_keys[key] = f"phase_nouvelle{len(new_phase_keys) + 1}"
            operations.append(AddPhase(key=new_phase_keys[key], title=title.strip()))
        return new_phase_keys[key]

    try:
        for index, change in enumerate(proposal.changes, start=1):
            fields = change.fields.provided()
            if change.op == "add":
                depends = [_task_id(snapshot, ref) for ref in change.fields.depends_on]
                operations.append(
                    AddTask(
                        key=f"ajout{index}",
                        phase=phase_ref(change.phase_title),
                        depends_on=depends,
                        **fields,
                    )
                )
            elif change.op == "update":
                task_id = _task_id(snapshot, change.task_ref)
                current = {dep for owner, dep in snapshot.dependencies if owner == task_id}
                asked = {_task_id(snapshot, ref) for ref in change.fields.depends_on}
                if change.fields.depends_on and asked != current:
                    # Constate avec gpt-5-mini : une date demandee devenait une dependance.
                    raise DomainError(
                        ErrorCode.VALIDATION_ERROR,
                        "Je ne change pas l'ordre des tâches (une tâche qui doit en attendre "
                        "une autre) avec cette demande : rien n'a été modifié. Une date limite "
                        "est une échéance, pas une dépendance.",
                    )
                if not fields:
                    # Constate avec gpt-5.6-terra (R0) : une modification vide, affichee comme
                    # une erreur technique. ``unclear`` : le graphe pose une question a la place.
                    raise DomainError(
                        ErrorCode.VALIDATION_ERROR,
                        "Aucune modification n'a été précisée.",
                        unclear=True,
                        task_ref=change.task_ref,
                    )
                operations.append(UpdateTask(task_id=task_id, changes=TaskChanges(**fields)))
            elif change.op == "delete":
                operations.append(DeleteTask(task_id=_task_id(snapshot, change.task_ref)))
            else:
                operations.append(
                    MoveTask(
                        task_id=_task_id(snapshot, change.task_ref),
                        phase=phase_ref(change.phase_title),
                    )
                )
    except ValidationError as exc:
        # Champ manquant ou hors limites (« title : Field required ») : detail technique,
        # jamais montre tel quel ; le graphe pose une question a la place.
        raise DomainError(ErrorCode.VALIDATION_ERROR, validation_detail(exc), unclear=True) from exc

    command = ChangeCommand(operations=operations)
    if replan or len(operations) != 1:
        return ActionType.PLAN_REPLAN, command
    single = operations[0]
    if isinstance(single, UpdateTask):
        return ActionType.TASK_UPDATE, command
    if isinstance(single, DeleteTask):
        return ActionType.TASK_DELETE, command
    if isinstance(single, AddTask) and single.phase in snapshot.phases:
        return ActionType.TASK_CREATE, command
    return ActionType.PLAN_REPLAN, command


def find_task_by_ref(snapshot: ProjectSnapshot, ref: str | None) -> str | None:
    """Identifiant interne d'une reference « T<n> », ou ``None`` si elle n'existe pas."""
    try:
        return _task_id(snapshot, ref)
    except DomainError:
        return None
