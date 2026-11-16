"""Prochaines actions : score explicable, selection et repli (DOMAIN_CONTRACTS section 8).

Portions adaptees de Personal Progress Assistant AI
(https://github.com/LancelotGalahad/Personal-Progress-Assistant-AI,
commit 83d24df8f751aa7a311fa69ecfbb98df1d4df229, core/engine.py,
priority_score et recommend_daily_focus).
Copyright (c) 2026 Personal Progress Assistant contributors - licence MIT
(texte complet : THIRD_PARTY_NOTICES.md, annexe A).
Modifications : facteurs reduits et renommes (priorite, urgence, deja_commencee, impact,
temps_disponible) ; urgence seulement si les echeances sont activees ; facteurs energie,
difficulte et report retires ; limite d'affichage issue des preferences ; repli
« lever le blocage » ou « decouper » ; tri stable par phase, position et numero.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Literal

from pydantic import Field

from neurocoach.domain.dependencies import Edge, is_ready, open_dependents, unmet_dependencies
from neurocoach.domain.models import DomainModel, Phase, Task, TaskStatus

FACTOR_NAMES = ("priorite", "urgence", "deja_commencee", "impact", "temps_disponible")


class Recommendation(DomainModel):
    task_id: str
    number: int
    title: str
    status: TaskStatus
    score: int
    factors: dict[str, int]
    kind: Literal["action", "lever_blocage", "decouper"]
    unmet_dependencies: list[int] = Field(default_factory=list)

    @property
    def ref(self) -> str:
        return f"T{self.number}"


class NextActions(DomainModel):
    state: Literal["ok", "repli", "plan_termine", "pas_de_plan", "aucune_action"]
    items: list[Recommendation]
    fallback: Recommendation | None = None


def urgency_points(due_date: date | None, today: date) -> int:
    """Paliers d'urgence selon les jours restants avant l'echeance."""
    if due_date is None:
        return 0
    days = (due_date - today).days
    if days <= 0:
        return 10
    if days <= 3:
        return 8
    if days <= 7:
        return 6
    if days <= 14:
        return 4
    return 2


def fits_available_time(task: Task, available_minutes_per_day: int | None) -> bool | None:
    """``None`` si l'estimation ou la disponibilite est inconnue."""
    if task.estimate_minutes is None or available_minutes_per_day is None:
        return None
    return task.estimate_minutes <= available_minutes_per_day


def score_task(
    task: Task,
    *,
    today: date,
    deadlines_enabled: bool,
    available_minutes_per_day: int | None,
    open_dependent_count: int,
) -> tuple[int, dict[str, int]]:
    """N-02 : somme de facteurs nommes ; le detail est renvoye tel quel."""
    fit = fits_available_time(task, available_minutes_per_day)
    factors = {
        "priorite": 2 * task.priority,
        "urgence": urgency_points(task.due_date, today) if deadlines_enabled else 0,
        "deja_commencee": 3 if task.status is TaskStatus.IN_PROGRESS else 0,
        "impact": 2 * min(3, open_dependent_count),
        "temps_disponible": 0 if fit is None else (2 if fit else -3),
    }
    return sum(factors.values()), factors


def select_next_actions(
    phases: Iterable[Phase],
    tasks: Mapping[str, Task],
    edges: Iterable[Edge],
    *,
    today: date,
    max_visible: int,
    deadlines_enabled: bool,
    available_minutes_per_day: int | None,
) -> NextActions:
    """N-03 a N-06 : selection limitee par la preference, puis repli eventuel."""
    edge_list = list(edges)
    phase_positions = {phase.id: phase.position for phase in phases}
    if not tasks:
        return NextActions(state="pas_de_plan", items=[])
    if all(task.status is TaskStatus.DONE for task in tasks.values()):
        return NextActions(state="plan_termine", items=[])

    def recommend(task: Task, kind: str) -> Recommendation:
        score, factors = score_task(
            task,
            today=today,
            deadlines_enabled=deadlines_enabled,
            available_minutes_per_day=available_minutes_per_day,
            open_dependent_count=open_dependents(task.id, tasks, edge_list),
        )
        unmet = unmet_dependencies(task.id, tasks, edge_list)
        return Recommendation(
            task_id=task.id,
            number=task.number,
            title=task.title,
            status=task.status,
            score=score,
            factors=factors,
            kind=kind,
            unmet_dependencies=[tasks[dep].number for dep in unmet if dep in tasks],
        )

    def order(item: Recommendation) -> tuple[int, int, int, int]:
        task = tasks[item.task_id]
        return (-item.score, phase_positions.get(task.phase_id, 0), task.position, task.number)

    ready = [task for task in tasks.values() if is_ready(task, tasks, edge_list)]
    fitting = [
        recommend(task, "action")
        for task in ready
        if fits_available_time(task, available_minutes_per_day) is not False
    ]
    if fitting:
        return NextActions(state="ok", items=sorted(fitting, key=order)[:max_visible])

    blocked = [
        recommend(task, "lever_blocage")
        for task in tasks.values()
        if task.status is TaskStatus.BLOCKED
    ]
    oversized = [
        recommend(task, "decouper")
        for task in ready
        if fits_available_time(task, available_minutes_per_day) is False
    ]
    for pool in (blocked, oversized):
        if pool:
            return NextActions(state="repli", items=[], fallback=sorted(pool, key=order)[0])
    return NextActions(state="aucune_action", items=[])
