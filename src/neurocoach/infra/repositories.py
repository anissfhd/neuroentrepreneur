"""Acces SQL a la base metier, toujours filtre par utilisateur (I-02, I-03).

Une ressource d'un autre utilisateur est indiscernable d'une ressource inexistante :
les deux levent ``NOT_FOUND``.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from typing import Any

from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.models import (
    ActionStatus,
    ActivityEvent,
    ConversationThread,
    EventType,
    PendingAction,
    Phase,
    Preferences,
    Project,
    Task,
    User,
)
from neurocoach.domain.plans import ProjectSnapshot


def to_db_datetime(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat().replace("+00:00", "Z")


def from_db_datetime(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def to_db_date(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def from_db_date(value: str | None) -> date | None:
    return None if value is None else date.fromisoformat(value)


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _not_found(what: str) -> DomainError:
    return DomainError(ErrorCode.NOT_FOUND, f"{what} introuvable.")


_PROJECT_COLUMNS = (
    "id, user_id, title, idea, target_outcome, constraints_json, facts_json, assumptions_json, "
    "available_minutes_per_day, horizon_date, status, next_task_number, version, created_at, "
    "updated_at, title_pending, paused_at, pause_note"
)
_TASK_COLUMNS = (
    "id, project_id, phase_id, number, title, description, acceptance_criteria, status, "
    "blocked_reason, priority, estimate_minutes, due_date, position, completed_at, version, "
    "created_at, updated_at"
)


class SqliteRepository:
    """Operations SQL sur une connexion deja placee dans une transaction."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # --- conversions ----------------------------------------------------------------
    @staticmethod
    def _user(row: sqlite3.Row) -> User:
        return User(
            id=row["id"],
            display_name=row["display_name"],
            created_at=from_db_datetime(row["created_at"]),
            first_name=row["first_name"],
            last_name=row["last_name"],
            username=row["username"],
        )

    @staticmethod
    def _preferences(row: sqlite3.Row) -> Preferences:
        return Preferences(
            user_id=row["user_id"],
            response_length=row["response_length"],
            max_visible_tasks=row["max_visible_tasks"],
            one_question_at_a_time=bool(row["one_question_at_a_time"]),
            deadlines_enabled=bool(row["deadlines_enabled"]),
            cadence=row["cadence"],
            display_timezone=row["display_timezone"],
            updated_at=from_db_datetime(row["updated_at"]),
        )

    @staticmethod
    def _project(row: sqlite3.Row) -> Project:
        return Project(
            id=row["id"],
            user_id=row["user_id"],
            title=row["title"],
            idea=row["idea"],
            target_outcome=row["target_outcome"],
            constraints=json.loads(row["constraints_json"]),
            facts=json.loads(row["facts_json"]),
            assumptions=json.loads(row["assumptions_json"]),
            available_minutes_per_day=row["available_minutes_per_day"],
            horizon_date=from_db_date(row["horizon_date"]),
            status=row["status"],
            next_task_number=row["next_task_number"],
            version=row["version"],
            created_at=from_db_datetime(row["created_at"]),
            updated_at=from_db_datetime(row["updated_at"]),
            title_pending=bool(row["title_pending"]),
            paused_at=from_db_datetime(row["paused_at"]),
            pause_note=row["pause_note"],
        )

    @staticmethod
    def _phase(row: sqlite3.Row) -> Phase:
        return Phase(
            id=row["id"],
            project_id=row["project_id"],
            title=row["title"],
            exit_criterion=row["exit_criterion"],
            position=row["position"],
        )

    @staticmethod
    def _task(row: sqlite3.Row) -> Task:
        return Task(
            id=row["id"],
            project_id=row["project_id"],
            phase_id=row["phase_id"],
            number=row["number"],
            title=row["title"],
            description=row["description"],
            acceptance_criteria=row["acceptance_criteria"],
            status=row["status"],
            blocked_reason=row["blocked_reason"],
            priority=row["priority"],
            estimate_minutes=row["estimate_minutes"],
            due_date=from_db_date(row["due_date"]),
            position=row["position"],
            completed_at=from_db_datetime(row["completed_at"]),
            version=row["version"],
            created_at=from_db_datetime(row["created_at"]),
            updated_at=from_db_datetime(row["updated_at"]),
        )

    @staticmethod
    def _action(row: sqlite3.Row) -> PendingAction:
        return PendingAction(
            id=row["id"],
            user_id=row["user_id"],
            project_id=row["project_id"],
            action_type=row["action_type"],
            payload=json.loads(row["payload_json"]),
            preview=json.loads(row["preview_json"]),
            expected_versions=json.loads(row["expected_versions_json"]),
            status=row["status"],
            idempotency_key=row["idempotency_key"],
            created_at=from_db_datetime(row["created_at"]),
            expires_at=from_db_datetime(row["expires_at"]),
            decided_at=from_db_datetime(row["decided_at"]),
            result=json.loads(row["result_json"]) if row["result_json"] else None,
        )

    @staticmethod
    def _event(row: sqlite3.Row) -> ActivityEvent:
        return ActivityEvent(
            id=row["id"],
            user_id=row["user_id"],
            project_id=row["project_id"],
            task_id=row["task_id"],
            pending_action_id=row["pending_action_id"],
            type=row["type"],
            payload=json.loads(row["payload_json"]),
            reverts_event_id=row["reverts_event_id"],
            created_at=from_db_datetime(row["created_at"]),
        )

    @staticmethod
    def _thread(row: sqlite3.Row) -> ConversationThread:
        return ConversationThread(
            id=row["id"],
            user_id=row["user_id"],
            project_id=row["project_id"],
            created_at=from_db_datetime(row["created_at"]),
        )

    # --- utilisateurs et preferences ------------------------------------------------
    def insert_user(self, user: User, username_key: str | None = None) -> None:
        """D-76 : la cle d'unicite est verifiee par un index unique (insensible a la casse et
        aux espaces de bord) ; un doublon leve ``sqlite3.IntegrityError``."""
        self.conn.execute(
            "INSERT INTO users (id, display_name, created_at, first_name, last_name, username, "
            "username_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                user.id,
                user.display_name,
                to_db_datetime(user.created_at),
                user.first_name,
                user.last_name,
                user.username,
                username_key,
            ),
        )

    def find_user_by_username_key(self, username_key: str) -> User | None:
        row = self.conn.execute(
            "SELECT * FROM users WHERE username_key = ?", (username_key,)
        ).fetchone()
        return self._user(row) if row else None

    def update_user_names(self, user_id: str, first: str, last: str, display: str) -> None:
        self.conn.execute(
            "UPDATE users SET first_name = ?, last_name = ?, display_name = ? WHERE id = ?",
            (first, last, display, user_id),
        )

    def rename_project(self, user_id: str, project_id: str, title: str, now: datetime) -> None:
        """D-76 : titre confirme par l'utilisateur ; la version n'augmente pas (le titre ne
        change ni le plan ni les propositions en attente)."""
        self.conn.execute(
            "UPDATE projects SET title = ?, title_pending = 0, updated_at = ? "
            "WHERE id = ? AND user_id = ?",
            (title, to_db_datetime(now), project_id, user_id),
        )

    def set_project_idea(self, user_id: str, project_id: str, idea: str, now: datetime) -> None:
        self.conn.execute(
            "UPDATE projects SET idea = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (idea, to_db_datetime(now), project_id, user_id),
        )

    def last_event_times(self, user_id: str) -> dict[str, str]:
        """Dernier evenement journalise par projet (texte ISO UTC)."""
        rows = self.conn.execute(
            "SELECT project_id, MAX(created_at) AS last FROM activity_events "
            "WHERE user_id = ? AND project_id IS NOT NULL GROUP BY project_id",
            (user_id,),
        ).fetchall()
        return {row["project_id"]: row["last"] for row in rows}

    def get_user(self, user_id: str) -> User | None:
        row = self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._user(row) if row else None

    def list_users(self) -> list[User]:
        rows = self.conn.execute("SELECT * FROM users ORDER BY display_name, id").fetchall()
        return [self._user(row) for row in rows]

    def get_preferences(self, user_id: str) -> Preferences | None:
        row = self.conn.execute(
            "SELECT * FROM preferences WHERE user_id = ?", (user_id,)
        ).fetchone()
        return self._preferences(row) if row else None

    def save_preferences(self, prefs: Preferences) -> None:
        self.conn.execute(
            """
            INSERT INTO preferences (user_id, response_length, max_visible_tasks,
                one_question_at_a_time, deadlines_enabled, cadence, display_timezone, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (user_id) DO UPDATE SET
                response_length = excluded.response_length,
                max_visible_tasks = excluded.max_visible_tasks,
                one_question_at_a_time = excluded.one_question_at_a_time,
                deadlines_enabled = excluded.deadlines_enabled,
                cadence = excluded.cadence,
                display_timezone = excluded.display_timezone,
                updated_at = excluded.updated_at
            """,
            (
                prefs.user_id,
                prefs.response_length.value,
                prefs.max_visible_tasks,
                int(prefs.one_question_at_a_time),
                int(prefs.deadlines_enabled),
                prefs.cadence.value,
                prefs.display_timezone,
                to_db_datetime(prefs.updated_at),
            ),
        )

    # --- projets --------------------------------------------------------------------
    def _project_values(self, project: Project) -> tuple[Any, ...]:
        return (
            project.id,
            project.user_id,
            project.title,
            project.idea,
            project.target_outcome,
            _dumps(project.constraints),
            _dumps(project.facts),
            _dumps(project.assumptions),
            project.available_minutes_per_day,
            to_db_date(project.horizon_date),
            project.status.value,
            project.next_task_number,
            project.version,
            to_db_datetime(project.created_at),
            to_db_datetime(project.updated_at),
            int(project.title_pending),
            to_db_datetime(project.paused_at),
            project.pause_note,
        )

    def insert_project(self, project: Project) -> None:
        self.conn.execute(
            f"INSERT INTO projects ({_PROJECT_COLUMNS}) VALUES ({', '.join('?' * 18)})",
            self._project_values(project),
        )

    def update_project(self, project: Project) -> None:
        values = self._project_values(project)
        self.conn.execute(
            """
            UPDATE projects SET title = ?, idea = ?, target_outcome = ?, constraints_json = ?,
                facts_json = ?, assumptions_json = ?, available_minutes_per_day = ?,
                horizon_date = ?, status = ?, next_task_number = ?, version = ?,
                created_at = ?, updated_at = ?, title_pending = ?, paused_at = ?,
                pause_note = ?
            WHERE id = ? AND user_id = ?
            """,
            (*values[2:], project.id, project.user_id),
        )

    def get_project(self, user_id: str, project_id: str) -> Project:
        row = self.conn.execute(
            f"SELECT {_PROJECT_COLUMNS} FROM projects WHERE id = ? AND user_id = ?",
            (project_id, user_id),
        ).fetchone()
        if row is None:
            raise _not_found("Projet")
        return self._project(row)

    def list_projects(self, user_id: str) -> list[Project]:
        rows = self.conn.execute(
            f"SELECT {_PROJECT_COLUMNS} FROM projects WHERE user_id = ? ORDER BY created_at, rowid",
            (user_id,),
        ).fetchall()
        return [self._project(row) for row in rows]

    def delete_project(self, user_id: str, project_id: str) -> None:
        self.conn.execute(
            "DELETE FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id)
        )

    def load_snapshot(self, user_id: str, project_id: str) -> ProjectSnapshot:
        project = self.get_project(user_id, project_id)
        phases = {
            row["id"]: self._phase(row)
            for row in self.conn.execute(
                "SELECT * FROM phases WHERE project_id = ?", (project_id,)
            ).fetchall()
        }
        tasks = {
            row["id"]: self._task(row)
            for row in self.conn.execute(
                f"SELECT {_TASK_COLUMNS} FROM tasks WHERE project_id = ?", (project_id,)
            ).fetchall()
        }
        dependencies = {
            (row["task_id"], row["depends_on_task_id"])
            for row in self.conn.execute(
                """
                SELECT d.task_id, d.depends_on_task_id FROM task_dependencies d
                JOIN tasks t ON t.id = d.task_id WHERE t.project_id = ?
                """,
                (project_id,),
            ).fetchall()
        }
        return ProjectSnapshot(project, phases, tasks, dependencies)

    def save_snapshot(self, old: ProjectSnapshot, new: ProjectSnapshot) -> None:
        """Ecrit la difference entre deux etats d'un meme projet."""
        if new.project != old.project:
            self.update_project(new.project)
        for phase in new.phases.values():
            if phase.id not in old.phases:
                self.conn.execute(
                    "INSERT INTO phases (id, project_id, title, exit_criterion, position) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (phase.id, phase.project_id, phase.title, phase.exit_criterion, phase.position),
                )
            elif phase != old.phases[phase.id]:
                self.conn.execute(
                    "UPDATE phases SET title = ?, exit_criterion = ?, position = ? WHERE id = ?",
                    (phase.title, phase.exit_criterion, phase.position, phase.id),
                )
        for task in new.tasks.values():
            if task.id not in old.tasks:
                self.insert_task(task)
            elif task != old.tasks[task.id]:
                self.update_task(task)
        for edge in old.dependencies - new.dependencies:
            self.conn.execute(
                "DELETE FROM task_dependencies WHERE task_id = ? AND depends_on_task_id = ?", edge
            )
        for task_id in old.tasks.keys() - new.tasks.keys():
            self.conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        for phase_id in old.phases.keys() - new.phases.keys():
            self.conn.execute("DELETE FROM phases WHERE id = ?", (phase_id,))
        for edge in new.dependencies - old.dependencies:
            self.conn.execute(
                "INSERT INTO task_dependencies (task_id, depends_on_task_id) VALUES (?, ?)", edge
            )

    # --- taches ---------------------------------------------------------------------
    @staticmethod
    def _task_values(task: Task) -> tuple[Any, ...]:
        return (
            task.id,
            task.project_id,
            task.phase_id,
            task.number,
            task.title,
            task.description,
            task.acceptance_criteria,
            task.status.value,
            task.blocked_reason,
            task.priority,
            task.estimate_minutes,
            to_db_date(task.due_date),
            task.position,
            to_db_datetime(task.completed_at),
            task.version,
            to_db_datetime(task.created_at),
            to_db_datetime(task.updated_at),
        )

    def insert_task(self, task: Task) -> None:
        self.conn.execute(
            f"INSERT INTO tasks ({_TASK_COLUMNS}) VALUES ({', '.join('?' * 17)})",
            self._task_values(task),
        )

    def update_task(self, task: Task) -> None:
        values = self._task_values(task)
        self.conn.execute(
            """
            UPDATE tasks SET phase_id = ?, number = ?, title = ?, description = ?,
                acceptance_criteria = ?, status = ?, blocked_reason = ?, priority = ?,
                estimate_minutes = ?, due_date = ?, position = ?, completed_at = ?, version = ?,
                created_at = ?, updated_at = ?
            WHERE id = ? AND project_id = ?
            """,
            (*values[2:], task.id, task.project_id),
        )

    def get_task(self, user_id: str, task_id: str) -> Task:
        row = self.conn.execute(
            f"""
            SELECT {", ".join("t." + column.strip() for column in _TASK_COLUMNS.split(","))}
            FROM tasks t JOIN projects p ON p.id = t.project_id
            WHERE t.id = ? AND p.user_id = ?
            """,
            (task_id, user_id),
        ).fetchone()
        if row is None:
            raise _not_found("Tâche")
        return self._task(row)

    # --- fils de conversation -------------------------------------------------------
    def get_thread(self, user_id: str, project_id: str) -> ConversationThread | None:
        row = self.conn.execute(
            "SELECT * FROM conversation_threads WHERE user_id = ? AND project_id = ?",
            (user_id, project_id),
        ).fetchone()
        return self._thread(row) if row else None

    def insert_thread(self, thread: ConversationThread) -> None:
        self.conn.execute(
            "INSERT INTO conversation_threads (id, user_id, project_id, created_at) "
            "VALUES (?, ?, ?, ?)",
            (thread.id, thread.user_id, thread.project_id, to_db_datetime(thread.created_at)),
        )

    def list_threads(self, user_id: str, project_id: str | None = None) -> list[ConversationThread]:
        if project_id is None:
            rows = self.conn.execute(
                "SELECT * FROM conversation_threads WHERE user_id = ? ORDER BY created_at, rowid",
                (user_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM conversation_threads WHERE user_id = ? AND project_id = ?",
                (user_id, project_id),
            ).fetchall()
        return [self._thread(row) for row in rows]

    # --- actions en attente ---------------------------------------------------------
    def insert_action(self, action: PendingAction) -> None:
        self.conn.execute(
            """
            INSERT INTO pending_actions (id, user_id, project_id, action_type, payload_json,
                preview_json, expected_versions_json, status, idempotency_key, created_at,
                expires_at, decided_at, result_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action.id,
                action.user_id,
                action.project_id,
                action.action_type.value,
                _dumps(action.payload),
                _dumps(action.preview),
                _dumps(action.expected_versions),
                action.status.value,
                action.idempotency_key,
                to_db_datetime(action.created_at),
                to_db_datetime(action.expires_at),
                to_db_datetime(action.decided_at),
                _dumps(action.result) if action.result is not None else None,
            ),
        )

    def get_action(self, user_id: str, action_id: str) -> PendingAction:
        row = self.conn.execute(
            "SELECT * FROM pending_actions WHERE id = ? AND user_id = ?", (action_id, user_id)
        ).fetchone()
        if row is None:
            raise _not_found("Proposition")
        return self._action(row)

    def find_pending(self, user_id: str, project_id: str | None) -> PendingAction | None:
        row = self.conn.execute(
            """
            SELECT * FROM pending_actions
            WHERE user_id = ? AND COALESCE(project_id, '') = COALESCE(?, '') AND status = 'pending'
            """,
            (user_id, project_id),
        ).fetchone()
        return self._action(row) if row else None

    def decide_action(
        self,
        action_id: str,
        status: ActionStatus,
        decided_at: datetime,
        result: dict[str, Any] | None,
    ) -> bool:
        """Transition conditionnelle depuis ``pending`` ; ``False`` si deja decidee."""
        cursor = self.conn.execute(
            """
            UPDATE pending_actions SET status = ?, decided_at = ?, result_json = ?
            WHERE id = ? AND status = 'pending'
            """,
            (
                status.value,
                to_db_datetime(decided_at),
                _dumps(result) if result is not None else None,
                action_id,
            ),
        )
        return cursor.rowcount == 1

    def set_action_result(self, action_id: str, result: dict[str, Any]) -> None:
        self.conn.execute(
            "UPDATE pending_actions SET result_json = ? WHERE id = ?", (_dumps(result), action_id)
        )

    def list_actions(self, user_id: str) -> list[PendingAction]:
        rows = self.conn.execute(
            "SELECT * FROM pending_actions WHERE user_id = ? ORDER BY rowid", (user_id,)
        ).fetchall()
        return [self._action(row) for row in rows]

    def delete_project_actions(self, project_id: str, keep_action_id: str) -> None:
        self.conn.execute(
            "DELETE FROM pending_actions WHERE project_id = ? AND id <> ?",
            (project_id, keep_action_id),
        )

    # --- journal --------------------------------------------------------------------
    def insert_event(self, event: ActivityEvent) -> None:
        self.conn.execute(
            """
            INSERT INTO activity_events (id, user_id, project_id, task_id, pending_action_id,
                type, payload_json, reverts_event_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.user_id,
                event.project_id,
                event.task_id,
                event.pending_action_id,
                event.type.value,
                _dumps(event.payload),
                event.reverts_event_id,
                to_db_datetime(event.created_at),
            ),
        )

    def get_event(self, user_id: str, event_id: str) -> ActivityEvent:
        row = self.conn.execute(
            "SELECT * FROM activity_events WHERE id = ? AND user_id = ?", (event_id, user_id)
        ).fetchone()
        if row is None:
            raise _not_found("Événement")
        return self._event(row)

    def list_events(self, user_id: str, project_id: str | None = None) -> list[ActivityEvent]:
        if project_id is None:
            rows = self.conn.execute(
                "SELECT * FROM activity_events WHERE user_id = ? ORDER BY rowid", (user_id,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM activity_events WHERE user_id = ? AND project_id = ? ORDER BY rowid",
                (user_id, project_id),
            ).fetchall()
        return [self._event(row) for row in rows]

    def latest_status_event(self, task_id: str) -> ActivityEvent | None:
        row = self.conn.execute(
            """
            SELECT * FROM activity_events WHERE task_id = ? AND type IN (?, ?)
            ORDER BY rowid DESC LIMIT 1
            """,
            (task_id, EventType.TASK_STATUS_CHANGED.value, EventType.TASK_STATUS_REVERTED.value),
        ).fetchone()
        return self._event(row) if row else None

    # --- suppression complete (E-02) ------------------------------------------------
    def delete_user_content(self, user_id: str, keep_action_id: str) -> None:
        # Recherche (R1) : missions, requetes, sources et constats (cascade).
        self.conn.execute("DELETE FROM research_missions WHERE user_id = ?", (user_id,))
        self.conn.execute("DELETE FROM activity_events WHERE user_id = ?", (user_id,))
        self.conn.execute(
            "DELETE FROM pending_actions WHERE user_id = ? AND id <> ?", (user_id, keep_action_id)
        )
        self.conn.execute("DELETE FROM conversation_threads WHERE user_id = ?", (user_id,))
        self.conn.execute("DELETE FROM projects WHERE user_id = ?", (user_id,))
        self.conn.execute("DELETE FROM preferences WHERE user_id = ?", (user_id,))

    def count_user_content(self, user_id: str) -> dict[str, int]:
        projects = self.conn.execute(
            "SELECT COUNT(*) FROM projects WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        tasks = self.conn.execute(
            "SELECT COUNT(*) FROM tasks t JOIN projects p ON p.id = t.project_id "
            "WHERE p.user_id = ?",
            (user_id,),
        ).fetchone()[0]
        return {"projects": int(projects), "tasks": int(tasks)}
