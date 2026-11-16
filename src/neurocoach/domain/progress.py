"""Progression deterministe et alerte de charge (DOMAIN_CONTRACTS section 7).

Portions adaptees de Personal Progress Assistant AI
(https://github.com/LancelotGalahad/Personal-Progress-Assistant-AI,
commit 83d24df8f751aa7a311fa69ecfbb98df1d4df229, core/engine.py,
progress_summary et workload_warning).
Copyright (c) 2026 Personal Progress Assistant contributors - licence MIT
(texte complet : THIRD_PARTY_NOTICES.md, annexe A).
Modifications : arrondi a une decimale (Decimal, demi superieur), aucune progression
sans tache, progression et statut par phase, retard calcule dans le fuseau d'affichage,
capacite en minutes par jour, textes en francais.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from neurocoach.domain.models import DomainModel, Phase, Task, TaskStatus

ONE_DECIMAL = Decimal("0.1")
NBSP = chr(0x00A0)  # espace insecable avant « % » (typographie francaise)
NO_PLAN_LABEL = "Pas encore de plan"

PhaseStatus = Literal["vide", "a_faire", "en_cours", "terminee"]


def completion_percent(done: int, total: int) -> Decimal | None:
    """PR-01 / PR-02 : pourcentage a une decimale, ``None`` sans tache."""
    if total == 0:
        return None
    return (Decimal(done) * 100 / Decimal(total)).quantize(ONE_DECIMAL, rounding=ROUND_HALF_UP)


def format_percent(value: Decimal | None) -> str:
    """PR-05 : virgule decimale et espace insecable ; ``.0`` supprime."""
    if value is None:
        return NO_PLAN_LABEL
    text = f"{value:.1f}"
    if text.endswith(".0"):
        text = text[:-2]
    return text.replace(".", ",") + NBSP + "%"


class PhaseProgress(DomainModel):
    phase_id: str
    title: str
    position: int
    total: int
    done: int
    percent: Decimal | None
    status: PhaseStatus


class ProgressSummary(DomainModel):
    total: int
    done: int
    in_progress: int
    blocked: int
    todo: int
    overdue: list[int]
    percent: Decimal | None
    phases: list[PhaseProgress]


def phase_status(tasks: list[Task]) -> PhaseStatus:
    """PR-03 : statut calcule d'une phase."""
    if not tasks:
        return "vide"
    if all(task.status is TaskStatus.DONE for task in tasks):
        return "terminee"
    if all(task.status is TaskStatus.TODO for task in tasks):
        return "a_faire"
    return "en_cours"


def summarize_progress(
    phases: Iterable[Phase], tasks: Iterable[Task], *, today: date
) -> ProgressSummary:
    """PR-04 : synthese a partir des seules donnees stockees."""
    task_list = list(tasks)

    def count(status: TaskStatus) -> int:
        return sum(1 for task in task_list if task.status is status)

    overdue = sorted(
        task.number
        for task in task_list
        if task.status is not TaskStatus.DONE
        and task.due_date is not None
        and task.due_date < today
    )
    phase_items = []
    for phase in sorted(phases, key=lambda item: (item.position, item.id)):
        members = [task for task in task_list if task.phase_id == phase.id]
        done = sum(1 for task in members if task.status is TaskStatus.DONE)
        phase_items.append(
            PhaseProgress(
                phase_id=phase.id,
                title=phase.title,
                position=phase.position,
                total=len(members),
                done=done,
                percent=completion_percent(done, len(members)),
                status=phase_status(members),
            )
        )
    done_count = count(TaskStatus.DONE)
    return ProgressSummary(
        total=len(task_list),
        done=done_count,
        in_progress=count(TaskStatus.IN_PROGRESS),
        blocked=count(TaskStatus.BLOCKED),
        todo=count(TaskStatus.TODO),
        overdue=overdue,
        percent=completion_percent(done_count, len(task_list)),
        phases=phase_items,
    )


class WorkloadAlert(DomainModel):
    level: Literal["depassement", "marge_faible"]
    effort_minutes: int
    capacity_minutes: int
    unestimated_tasks: int

    @property
    def message(self) -> str:
        hours = f"{self.effort_minutes} min estimées pour environ {self.capacity_minutes} min"
        if self.level == "depassement":
            text = f"Le plan dépasse le temps disponible ({hours}). Réduire le périmètre aiderait."
        else:
            text = f"Le plan utilise presque tout le temps disponible ({hours})."
        if self.unestimated_tasks:
            text += f" {self.unestimated_tasks} tâche(s) sans estimation ne sont pas comptées."
        return text


def workload_alert(
    tasks: Iterable[Task],
    *,
    available_minutes_per_day: int | None,
    horizon_date: date | None,
    today: date,
) -> WorkloadAlert | None:
    """PR-06 : compare l'effort restant a la capacite declaree."""
    if available_minutes_per_day is None or horizon_date is None:
        return None
    days = max(1, (horizon_date - today).days)
    capacity = available_minutes_per_day * days
    remaining = [task for task in tasks if task.status is not TaskStatus.DONE]
    effort = sum(task.estimate_minutes or 0 for task in remaining)
    unestimated = sum(1 for task in remaining if task.estimate_minutes is None)
    if effort > capacity:
        level: Literal["depassement", "marge_faible"] = "depassement"
    elif effort * 100 > capacity * 85:
        level = "marge_faible"
    else:
        return None
    return WorkloadAlert(
        level=level,
        effort_minutes=effort,
        capacity_minutes=capacity,
        unestimated_tasks=unestimated,
    )
