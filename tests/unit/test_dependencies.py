"""I-04 et N-01 : dependances, disponibilite et cycles."""

from __future__ import annotations

import pytest

from factories import make_task
from neurocoach.domain.dependencies import (
    find_cycle,
    is_ready,
    open_dependents,
    unmet_dependencies,
    validate_dependency_graph,
)
from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.models import TaskStatus


def _tasks(*tasks):
    return {task.id: task for task in tasks}


T1, T2, T3 = make_task(1), make_task(2), make_task(3)


def test_unmet_dependencies_sorted_by_number_and_include_missing():
    tasks = _tasks(T1, T2, T3)
    edges = {(T3.id, T2.id), (T3.id, T1.id), (T3.id, "tsk_missing")}
    assert unmet_dependencies(T3.id, tasks, edges) == ["tsk_missing", T1.id, T2.id]


def test_done_dependency_is_met():
    done = make_task(1, TaskStatus.DONE)
    tasks = _tasks(done, T2)
    assert unmet_dependencies(T2.id, tasks, {(T2.id, done.id)}) == []
    assert is_ready(T2, tasks, {(T2.id, done.id)})


@pytest.mark.parametrize(
    ("status", "ready"),
    [
        (TaskStatus.TODO, True),
        (TaskStatus.IN_PROGRESS, True),
        (TaskStatus.BLOCKED, False),
        (TaskStatus.DONE, False),
    ],
)
def test_readiness_depends_on_status(status, ready):
    task = make_task(1, status)
    assert is_ready(task, _tasks(task), set()) is ready


def test_unmet_dependency_makes_task_not_ready():
    tasks = _tasks(T1, T2)
    assert not is_ready(T2, tasks, {(T2.id, T1.id)})


def test_open_dependents_ignores_done_tasks():
    done = make_task(3, TaskStatus.DONE)
    tasks = _tasks(T1, T2, done)
    edges = {(T2.id, T1.id), (done.id, T1.id)}
    assert open_dependents(T1.id, tasks, edges) == 1


def test_find_cycle_on_acyclic_graph_returns_none():
    assert find_cycle({"a", "b", "c"}, {("b", "a"), ("c", "b"), ("c", "a")}) is None


def test_find_cycle_detects_direct_cycle():
    cycle = find_cycle({"a", "b"}, {("a", "b"), ("b", "a")})
    assert cycle is not None
    assert cycle[0] == cycle[-1]


def test_find_cycle_detects_indirect_cycle():
    cycle = find_cycle(set(), {("a", "b"), ("b", "c"), ("c", "a"), ("d", "a")})
    assert cycle is not None
    assert set(cycle) == {"a", "b", "c"}


def test_validate_refuses_self_dependency():
    with pytest.raises(DomainError) as error:
        validate_dependency_graph({"a"}, {("a", "a")})
    assert error.value.code is ErrorCode.VALIDATION_ERROR


def test_validate_refuses_unknown_task():
    with pytest.raises(DomainError) as error:
        validate_dependency_graph({"a"}, {("a", "b")})
    assert error.value.code is ErrorCode.VALIDATION_ERROR


def test_validate_refuses_cycle():
    with pytest.raises(DomainError) as error:
        validate_dependency_graph({"a", "b", "c"}, {("a", "b"), ("b", "c"), ("c", "a")})
    assert error.value.code is ErrorCode.CYCLE_DETECTED


def test_validate_accepts_valid_graph():
    validate_dependency_graph({"a", "b", "c"}, {("b", "a"), ("c", "b")})
