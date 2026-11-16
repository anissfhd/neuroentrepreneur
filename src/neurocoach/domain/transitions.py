"""Transitions de statut des taches (DOMAIN_CONTRACTS section 2.1 et 6.2).

Portions adaptees de Personal Progress Assistant AI
(https://github.com/LancelotGalahad/Personal-Progress-Assistant-AI,
commit 83d24df8f751aa7a311fa69ecfbb98df1d4df229, core/engine.py, update_task_status).
Copyright (c) 2026 Personal Progress Assistant contributors - licence MIT
(texte complet : THIRD_PARTY_NOTICES.md, annexe A).
Modifications : statuts todo/in_progress/blocked/done, table de transitions explicite,
transition done -> blocked interdite, versionnement, entites immuables, annulation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.models import STATUS_LABELS, Task, TaskStatus, updated

_T = TaskStatus

ALLOWED_TRANSITIONS: frozenset[tuple[TaskStatus, TaskStatus]] = frozenset(
    {
        (_T.TODO, _T.IN_PROGRESS),
        (_T.TODO, _T.BLOCKED),
        (_T.TODO, _T.DONE),
        (_T.IN_PROGRESS, _T.TODO),
        (_T.IN_PROGRESS, _T.BLOCKED),
        (_T.IN_PROGRESS, _T.DONE),
        (_T.BLOCKED, _T.TODO),
        (_T.BLOCKED, _T.IN_PROGRESS),
        (_T.BLOCKED, _T.DONE),
        (_T.DONE, _T.TODO),
        (_T.DONE, _T.IN_PROGRESS),
    }
)


@dataclass(frozen=True)
class TransitionOutcome:
    task: Task
    changed: bool
    from_status: TaskStatus
    to_status: TaskStatus
    previous_reason: str | None
    previous_completed_at: datetime | None


def _clean(reason: str | None) -> str | None:
    if reason is None:
        return None
    stripped = reason.strip()
    return stripped or None


def apply_transition(
    task: Task, target: TaskStatus | str, *, reason: str | None, now: datetime
) -> TransitionOutcome:
    """Applique T-01 a T-04 et T-06 ; renvoie la tache (inchangee si sans effet)."""
    target = TaskStatus(target)
    reason = _clean(reason)
    unchanged = TransitionOutcome(
        task, False, task.status, target, task.blocked_reason, task.completed_at
    )

    if target is task.status:
        # T-01 : sans effet, sauf mise a jour de la raison d'un blocage.
        if target is TaskStatus.BLOCKED and reason and reason != task.blocked_reason:
            new_task = updated(
                task, blocked_reason=reason, version=task.version + 1, updated_at=now
            )
            return TransitionOutcome(
                new_task, True, task.status, target, task.blocked_reason, task.completed_at
            )
        return unchanged

    if (task.status, target) not in ALLOWED_TRANSITIONS:
        raise DomainError(
            ErrorCode.INVALID_TRANSITION,
            f"{STATUS_LABELS[task.status]} -> {STATUS_LABELS[target]}.",
        )
    if target is TaskStatus.BLOCKED and reason is None:
        raise DomainError(ErrorCode.VALIDATION_ERROR, "Une raison est requise pour bloquer.")

    new_task = updated(
        task,
        status=target,
        blocked_reason=reason if target is TaskStatus.BLOCKED else None,
        # T-03 : completed_at conserve s'il existe deja, efface en quittant done.
        completed_at=(task.completed_at or now) if target is TaskStatus.DONE else None,
        version=task.version + 1,
        updated_at=now,
    )
    return TransitionOutcome(
        new_task, True, task.status, target, task.blocked_reason, task.completed_at
    )


def revert_transition(
    task: Task,
    *,
    from_status: TaskStatus,
    previous_reason: str | None,
    previous_completed_at: datetime | None,
    now: datetime,
) -> Task:
    """U-02 : restaure le statut precedent, sa raison et sa date de fin."""
    restored_completed = None
    if from_status is TaskStatus.DONE:
        restored_completed = previous_completed_at or now
    return updated(
        task,
        status=from_status,
        blocked_reason=previous_reason if from_status is TaskStatus.BLOCKED else None,
        completed_at=restored_completed,
        version=task.version + 1,
        updated_at=now,
    )
