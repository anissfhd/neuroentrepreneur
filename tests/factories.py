"""Fabriques de donnees de test, toutes fictives."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

from neurocoach.domain.models import Phase, Project, ProjectStatus, Task, TaskStatus
from neurocoach.domain.plans import PlanDraft, ProjectSnapshot

NOW = datetime(2026, 11, 9, 9, 0, tzinfo=UTC)
TODAY = date(2026, 11, 9)
ALICE = "usr_" + "a" * 32
BRUNO = "usr_" + "b" * 32
PROJECT_ID = "prj_" + "1" * 32


def make_project(**overrides: Any) -> Project:
    values: dict[str, Any] = {
        "id": PROJECT_ID,
        "user_id": ALICE,
        "title": "Projet de test",
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return Project(**values)


def make_phase(index: int = 0, **overrides: Any) -> Phase:
    values: dict[str, Any] = {
        "id": f"pha_{index:032d}",
        "project_id": PROJECT_ID,
        "title": f"Phase {index + 1}",
        "position": index,
    }
    values.update(overrides)
    return Phase(**values)


def make_task(number: int = 1, status: TaskStatus = TaskStatus.TODO, **overrides: Any) -> Task:
    values: dict[str, Any] = {
        "id": f"tsk_{number:032d}",
        "project_id": PROJECT_ID,
        "phase_id": make_phase().id,
        "number": number,
        "title": f"Tâche {number}",
        "acceptance_criteria": f"Critère {number}",
        "status": status,
        "position": number - 1,
        "created_at": NOW,
        "updated_at": NOW,
    }
    if status is TaskStatus.DONE:
        values["completed_at"] = NOW
    if status is TaskStatus.BLOCKED:
        values["blocked_reason"] = "En attente d'un retour"
    values.update(overrides)
    return Task(**values)


def make_snapshot(
    tasks: Sequence[Task] = (),
    *,
    phases: Sequence[Phase] | None = None,
    dependencies: set[tuple[str, str]] | None = None,
    status: ProjectStatus = ProjectStatus.ACTIVE,
) -> ProjectSnapshot:
    phase_list = list(phases) if phases is not None else [make_phase()]
    next_number = max((task.number for task in tasks), default=0) + 1
    return ProjectSnapshot(
        project=make_project(status=status, next_task_number=next_number),
        phases={phase.id: phase for phase in phase_list},
        tasks={task.id: task for task in tasks},
        dependencies=set(dependencies or set()),
    )


def sample_plan(**overrides: Any) -> PlanDraft:
    """Plan de reference du dossier : trois micro-taches chainees (docs/04)."""
    values: dict[str, Any] = {
        "objective": "Tester l'intérêt pour des bougies artisanales",
        "assumptions": ["30 minutes par jour"],
        "phases": [
            {
                "title": "Valider l'intérêt",
                "tasks": [
                    {
                        "key": "client",
                        "title": "Décrire le client visé",
                        "acceptance_criteria": "Une phrase décrit le client idéal",
                        "estimate_minutes": 20,
                        "due_in_days": 2,
                    },
                    {
                        "key": "questions",
                        "title": "Préparer cinq questions",
                        "acceptance_criteria": "Cinq questions sont rédigées",
                        "depends_on": ["client"],
                        "due_in_days": 4,
                    },
                    {
                        "key": "entretiens",
                        "title": "Interroger trois personnes",
                        "acceptance_criteria": "Trois échanges sont notés",
                        "depends_on": ["questions"],
                    },
                ],
            }
        ],
    }
    values.update(overrides)
    return PlanDraft.model_validate(values)


class RecordingConversationStore:
    """Double de test du stockage conversationnel (phase 2 : checkpointer LangGraph)."""

    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.messages: dict[str, list[dict[str, str]]] = {}
        self.fail_on_delete = False

    def delete_threads(self, thread_ids: Sequence[str]) -> None:
        if self.fail_on_delete:
            raise RuntimeError("stockage conversationnel indisponible")
        self.deleted.extend(thread_ids)

    def export_messages(self, thread_id: str) -> list[dict[str, str]]:
        return list(self.messages.get(thread_id, []))
