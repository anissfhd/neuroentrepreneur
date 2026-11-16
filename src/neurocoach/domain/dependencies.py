"""Dependances entre taches : disponibilite et absence de cycle (DOMAIN_CONTRACTS I-04, N-01).

Portions adaptees de Personal Progress Assistant AI
(https://github.com/LancelotGalahad/Personal-Progress-Assistant-AI,
commit 83d24df8f751aa7a311fa69ecfbb98df1d4df229, core/engine.py, dependency_state).
Copyright (c) 2026 Personal Progress Assistant contributors - licence MIT
(texte complet : THIRD_PARTY_NOTICES.md, annexe A).
Modifications : aretes explicites (tache, dependance), detection de cycles ajoutee,
validation des references, comptage des dependantes ouvertes.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping

from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.models import Task, TaskStatus

Edge = tuple[str, str]
"""(tache, tache dont elle depend)"""

READY_STATUSES = frozenset({TaskStatus.TODO, TaskStatus.IN_PROGRESS})


def unmet_dependencies(task_id: str, tasks: Mapping[str, Task], edges: Iterable[Edge]) -> list[str]:
    """Dependances non terminees (ou inexistantes) d'une tache, triees par numero."""
    unmet = [
        dep
        for (task, dep) in edges
        if task == task_id and (dep not in tasks or tasks[dep].status is not TaskStatus.DONE)
    ]
    return sorted(unmet, key=lambda dep: tasks[dep].number if dep in tasks else 0)


def is_ready(task: Task, tasks: Mapping[str, Task], edges: Iterable[Edge]) -> bool:
    """N-01 : a faire ou en cours, et toutes les dependances terminees."""
    return task.status in READY_STATUSES and not unmet_dependencies(task.id, tasks, edges)


def open_dependents(task_id: str, tasks: Mapping[str, Task], edges: Iterable[Edge]) -> int:
    """Nombre de taches non terminees qui dependent directement de ``task_id``."""
    return sum(
        1
        for (task, dep) in edges
        if dep == task_id and task in tasks and tasks[task].status is not TaskStatus.DONE
    )


def find_cycle(nodes: Iterable[str], edges: Iterable[Edge]) -> list[str] | None:
    """Renvoie un cycle (liste de noeuds, premier = dernier) ou ``None``."""
    graph: dict[str, list[str]] = defaultdict(list)
    all_nodes = set(nodes)
    for task, dep in sorted(edges):
        graph[task].append(dep)
        all_nodes.update((task, dep))

    visiting, done = set(), set()
    for start in sorted(all_nodes):
        if start in done:
            continue
        path = [start]
        stack = [iter(graph[start])]
        visiting.add(start)
        while stack:
            nxt = next(stack[-1], None)
            if nxt is None:
                finished = path.pop()
                stack.pop()
                visiting.discard(finished)
                done.add(finished)
                continue
            if nxt in visiting:
                return [*path[path.index(nxt) :], nxt]
            if nxt not in done:
                visiting.add(nxt)
                path.append(nxt)
                stack.append(iter(graph[nxt]))
    return None


def validate_dependency_graph(task_ids: set[str], edges: Iterable[Edge]) -> None:
    """Refuse auto-dependances, references inconnues et cycles (I-04)."""
    edge_list = list(edges)
    for task, dep in edge_list:
        if task == dep:
            raise DomainError(ErrorCode.VALIDATION_ERROR, "Une tâche ne peut dépendre d'elle-même.")
        if task not in task_ids or dep not in task_ids:
            raise DomainError(ErrorCode.VALIDATION_ERROR, "Dépendance vers une tâche inconnue.")
    if find_cycle(task_ids, edge_list) is not None:
        raise DomainError(ErrorCode.CYCLE_DETECTED)
