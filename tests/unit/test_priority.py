"""N-01 a N-06 : score explicable, selection limitee et repli."""

from __future__ import annotations

from datetime import timedelta

import pytest

from factories import TODAY, make_phase, make_task
from neurocoach.domain.models import TaskStatus
from neurocoach.domain.priority import FACTOR_NAMES, score_task, select_next_actions, urgency_points

S = TaskStatus


def _select(tasks, edges=(), *, max_visible=3, deadlines=False, minutes=None, phases=None):
    return select_next_actions(
        phases or [make_phase()],
        {task.id: task for task in tasks},
        set(edges),
        today=TODAY,
        max_visible=max_visible,
        deadlines_enabled=deadlines,
        available_minutes_per_day=minutes,
    )


@pytest.mark.parametrize(
    ("days", "points"),
    [(None, 0), (-2, 10), (0, 10), (1, 8), (3, 8), (4, 6), (7, 6), (8, 4), (14, 4), (15, 2)],
)
def test_urgency_points(days, points):
    due = None if days is None else TODAY + timedelta(days=days)
    assert urgency_points(due, TODAY) == points


def test_score_lists_every_factor():
    score, factors = score_task(
        make_task(1, S.IN_PROGRESS, priority=4, due_date=TODAY, estimate_minutes=20),
        today=TODAY,
        deadlines_enabled=True,
        available_minutes_per_day=30,
        open_dependent_count=5,
    )
    assert tuple(factors) == FACTOR_NAMES
    assert factors == {
        "priorite": 8,
        "urgence": 10,
        "deja_commencee": 3,
        "impact": 6,
        "temps_disponible": 2,
    }
    assert score == 29


def test_urgency_ignored_when_deadlines_disabled():
    _, factors = score_task(
        make_task(1, due_date=TODAY),
        today=TODAY,
        deadlines_enabled=False,
        available_minutes_per_day=None,
        open_dependent_count=0,
    )
    assert factors["urgence"] == 0
    assert factors["temps_disponible"] == 0


def test_too_long_task_gets_negative_time_factor():
    _, factors = score_task(
        make_task(1, estimate_minutes=90),
        today=TODAY,
        deadlines_enabled=False,
        available_minutes_per_day=30,
        open_dependent_count=0,
    )
    assert factors["temps_disponible"] == -3


def test_no_tasks_means_no_plan():
    assert _select([]).state == "pas_de_plan"


def test_all_done_means_plan_finished():
    assert _select([make_task(1, S.DONE)]).state == "plan_termine"


def test_selection_is_limited_by_preference():
    tasks = [make_task(n) for n in range(1, 6)]
    for limit in (1, 2, 3):
        result = _select(tasks, max_visible=limit)
        assert result.state == "ok"
        assert len(result.items) == limit


def test_blocked_and_waiting_tasks_are_never_proposed():
    t1 = make_task(1, S.BLOCKED)
    t2 = make_task(2)
    t3 = make_task(3)
    result = _select([t1, t2, t3], edges={(t2.id, t1.id)})
    assert [item.number for item in result.items] == [3]


def test_order_by_score_then_phase_then_position():
    first, second = make_phase(0), make_phase(1)
    tasks = [
        make_task(1, phase_id=second.id, position=0),
        make_task(2, phase_id=first.id, position=1),
        make_task(3, phase_id=first.id, position=0),
        make_task(4, phase_id=second.id, position=1, priority=5),
    ]
    result = _select(tasks, phases=[first, second], max_visible=3)
    assert [item.number for item in result.items] == [4, 3, 2]


def test_in_progress_task_is_preferred():
    result = _select([make_task(1), make_task(2, S.IN_PROGRESS)], max_visible=1)
    assert result.items[0].number == 2
    assert result.items[0].factors["deja_commencee"] == 3


def test_fallback_unblock_when_nothing_ready():
    t1 = make_task(1, S.BLOCKED)
    t2 = make_task(2)
    result = _select([t1, t2], edges={(t2.id, t1.id)})
    assert result.state == "repli"
    assert result.items == []
    assert result.fallback is not None
    assert (result.fallback.number, result.fallback.kind) == (1, "lever_blocage")


def test_fallback_split_when_only_oversized_tasks():
    result = _select([make_task(1, estimate_minutes=240)], minutes=30)
    assert result.state == "repli"
    assert result.fallback is not None
    assert result.fallback.kind == "decouper"


def test_unblock_is_preferred_over_split():
    result = _select([make_task(1, S.BLOCKED), make_task(2, estimate_minutes=240)], minutes=30)
    assert result.fallback is not None
    assert result.fallback.kind == "lever_blocage"


def test_oversized_task_is_not_first_choice_when_others_fit():
    result = _select([make_task(1, estimate_minutes=240, priority=5), make_task(2)], minutes=30)
    assert [item.number for item in result.items] == [2]


def test_no_action_when_only_dangling_dependencies():
    t1 = make_task(1)
    result = _select([t1], edges={(t1.id, "tsk_absente")})
    assert result.state == "aucune_action"


def test_recommendation_reports_unmet_dependencies_of_fallback():
    t1 = make_task(1, S.BLOCKED)
    t2 = make_task(2, S.BLOCKED)
    result = _select([t1, t2], edges={(t2.id, t1.id)})
    assert result.fallback is not None
    assert result.fallback.ref == "T1"
    other = _select([t2, make_task(1)], edges={(t2.id, make_task(1).id)}, max_visible=3)
    assert [item.number for item in other.items] == [1]
