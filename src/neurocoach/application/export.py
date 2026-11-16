"""Export des donnees d'un utilisateur (DOMAIN_CONTRACTS E-01).

La suppression (E-02, E-03) passe par une action en attente : voir
``PendingActionService.request_user_data_deletion`` et ``request_project_deletion``.
"""

from __future__ import annotations

from typing import Any

from neurocoach.application.base import BaseService, make_event
from neurocoach.domain.models import EventType
from neurocoach.infra.research_repository import ResearchRepository

EXPORT_FORMAT = "neurocoach-export"
EXPORT_VERSION = 1


class DataService(BaseService):
    def export_user_data(self, user_id: str) -> dict[str, Any]:
        """Toutes les donnees de l'utilisateur, et seulement les siennes."""
        now = self.clock.now()
        with self._write() as repo:
            prefs = self._preferences(repo, user_id, now)
            user = repo.get_user(user_id)
            assert user is not None
            projects = []
            for project in repo.list_projects(user_id):
                snapshot = repo.load_snapshot(user_id, project.id)
                projects.append(
                    {
                        "project": project.model_dump(mode="json"),
                        "phases": [
                            phase.model_dump(mode="json") for phase in snapshot.ordered_phases()
                        ],
                        "tasks": [
                            task.model_dump(mode="json") for task in snapshot.ordered_tasks()
                        ],
                        "dependencies": [
                            {"task_id": task_id, "depends_on_task_id": dep_id}
                            for task_id, dep_id in sorted(snapshot.dependencies)
                        ],
                    }
                )
            events = [event.model_dump(mode="json") for event in repo.list_events(user_id)]
            conversations = [
                {
                    "thread_id": thread.id,
                    "project_id": thread.project_id,
                    "messages": self.conversations.export_messages(thread.id),
                }
                for thread in repo.list_threads(user_id)
            ]
            research_repo = ResearchRepository(repo.conn)
            research = [
                {
                    "mission": mission.model_dump(mode="json"),
                    "queries": [
                        q.model_dump(mode="json")
                        for q in research_repo.list_queries(user_id, mission.id)
                    ],
                    "sources": [
                        s.model_dump(mode="json")
                        for s in research_repo.list_sources(user_id, mission.id)
                    ],
                    "findings": [
                        f.model_dump(mode="json")
                        for f in research_repo.list_findings(user_id, mission.id)
                    ],
                    "analyses": [
                        a.model_dump(mode="json")
                        for a in research_repo.list_analyses(user_id, mission.id)
                    ],
                    "solutions": [
                        p.model_dump(mode="json")
                        for p in research_repo.list_solutions(user_id, mission.id)
                    ],
                }
                for mission in research_repo.list_missions(user_id)
            ]
            repo.insert_event(make_event(user_id, EventType.USER_DATA_EXPORTED, now=now))
        return {
            "format": EXPORT_FORMAT,
            "version": EXPORT_VERSION,
            "exported_at": now.isoformat().replace("+00:00", "Z"),
            "user": user.model_dump(mode="json"),
            "preferences": prefs.model_dump(mode="json"),
            "projects": projects,
            "events": events,
            "conversations": conversations,
            "research": research,  # R1 (D-68) : missions, requetes, sources, constats
        }
