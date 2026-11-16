"""PR-01 a PR-06 : progression deterministe et alerte de charge (dont T07)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from factories import TODAY, make_phase, make_task
from neurocoach.domain.models import TaskStatus
from neurocoach.domain.progress import (
    NBSP,
    NO_PLAN_LABEL,
    completion_percent,
    format_percent,
    phase_status,
    summarize_progress,
    workload_alert,
)

S = TaskStatus


@pytest.mark.parametrize(
    ("done", "total", "expected"),
    [
        (0, 0, None),
        (0, 3, Decimal("0.0")),
        (1, 3, Decimal("33.3")),  # T07
        (2, 3, Decimal("66.7")),
        (1, 8, Decimal("12.5")),
        (1, 16, Decimal("6.3")),  # 6,25 arrondi au demi superieur
        (3, 3, Decimal("100.0")),
    ],
)
def test_completion_percent(done, total, expected):
    assert completion_percent(done, total) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("33.3"), "33,3" + NBSP + "%"),
        (Decimal("100.0"), "100" + NBSP + "%"),
        (Decimal("0.0"), "0" + NBSP + "%"),
        (Decimal("12.5"), "12,5" + NBSP + "%"),
        (None, NO_PLAN_LABEL),
    ],
)
def test_format_percent(value, expected):
    assert format_percent(value) == expected


def test_summary_of_one_done_out_of_three():
    tasks = [make_task(1, S.DONE), make_task(2), make_task(3)]
    summary = summarize_progress([make_phase()], tasks, today=TODAY)
    assert (summary.total, summary.done, summary.todo) == (3, 1, 2)
    assert summary.percent == Decimal("33.3")
    assert format_percent(summary.percent) == "33,3" + NBSP + "%"


def test_summary_without_tasks_has_no_percent():
    summary = summarize_progress([make_phase()], [], today=TODAY)
    assert summary.percent is None
    assert summary.phases[0].status == "vide"
    assert summary.phases[0].percent is None


def test_summary_counts_statuses_and_overdue_in_local_day():
    tasks = [
        make_task(1, S.IN_PROGRESS, due_date=TODAY - timedelta(days=1)),
        make_task(2, S.BLOCKED, due_date=TODAY),
        make_task(3, S.DONE, due_date=TODAY - timedelta(days=3)),
        make_task(4, due_date=TODAY - timedelta(days=2)),
    ]
    summary = summarize_progress([make_phase()], tasks, today=TODAY)
    assert (summary.in_progress, summary.blocked, summary.done, summary.todo) == (1, 1, 1, 1)
    # Echeance du jour non en retard ; tache terminee jamais en retard.
    assert summary.overdue == [1, 4]


def test_progress_per_phase_and_ordering():
    first, second = make_phase(0), make_phase(1, title="Phase deux")
    tasks = [
        make_task(1, S.DONE, phase_id=first.id),
        make_task(2, S.DONE, phase_id=first.id),
        make_task(3, phase_id=second.id),
    ]
    summary = summarize_progress([second, first], tasks, today=TODAY)
    assert [phase.phase_id for phase in summary.phases] == [first.id, second.id]
    assert summary.phases[0].percent == Decimal("100.0")
    assert summary.phases[0].status == "terminee"
    assert summary.phases[1].status == "a_faire"


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], "vide"),
        ([S.TODO, S.TODO], "a_faire"),
        ([S.DONE, S.DONE], "terminee"),
        ([S.DONE, S.TODO], "en_cours"),
        ([S.BLOCKED], "en_cours"),
        ([S.IN_PROGRESS, S.TODO], "en_cours"),
    ],
)
def test_phase_status(statuses, expected):
    tasks = [make_task(index + 1, status) for index, status in enumerate(statuses)]
    assert phase_status(tasks) == expected


def test_workload_alert_requires_capacity_and_horizon():
    tasks = [make_task(1, estimate_minutes=60)]
    assert (
        workload_alert(tasks, available_minutes_per_day=None, horizon_date=TODAY, today=TODAY)
        is None
    )
    assert (
        workload_alert(tasks, available_minutes_per_day=30, horizon_date=None, today=TODAY) is None
    )


def test_workload_alert_overrun():
    tasks = [
        make_task(1, estimate_minutes=120),
        make_task(2),
        make_task(3, S.DONE, estimate_minutes=400),
    ]
    alert = workload_alert(
        tasks, available_minutes_per_day=30, horizon_date=TODAY + timedelta(days=2), today=TODAY
    )
    assert alert is not None
    assert alert.level == "depassement"
    assert (alert.effort_minutes, alert.capacity_minutes, alert.unestimated_tasks) == (120, 60, 1)
    assert "dépasse" in alert.message
    assert "sans estimation" in alert.message


def test_workload_alert_low_margin():
    tasks = [make_task(1, estimate_minutes=90)]
    alert = workload_alert(
        tasks, available_minutes_per_day=50, horizon_date=TODAY + timedelta(days=2), today=TODAY
    )
    assert alert is not None
    assert alert.level == "marge_faible"
    assert "presque tout" in alert.message


def test_workload_without_alert_and_minimum_one_day():
    tasks = [make_task(1, estimate_minutes=10)]
    assert (
        workload_alert(tasks, available_minutes_per_day=60, horizon_date=TODAY, today=TODAY) is None
    )
    alert = workload_alert(
        [make_task(1, estimate_minutes=100)],
        available_minutes_per_day=60,
        horizon_date=TODAY - timedelta(days=5),
        today=TODAY,
    )
    assert alert is not None
    assert alert.capacity_minutes == 60
