"""Services de lecture et ecritures directes (DOMAIN_CONTRACTS section 14).

Ecritures directes autorisees (R-CONF-01) : statut d'une tache, preferences saisies dans
l'ecran dedie, creation d'un projet vide. Toute autre ecriture passe par
``PendingActionService``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from neurocoach.application.base import BaseService, make_event
from neurocoach.domain.dependencies import unmet_dependencies
from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.models import (
    ActivityEvent,
    ConversationThread,
    EventType,
    Preferences,
    Project,
    Task,
    TaskStatus,
    User,
    build,
    new_id,
    updated,
)
from neurocoach.domain.plans import ProjectSnapshot, jsonable
from neurocoach.domain.priority import NextActions, select_next_actions
from neurocoach.domain.profiles import (
    FALLBACK_TITLE,
    PLACEHOLDER_TITLE,
    suggest_title,
    username_key,
    validate_profile,
)
from neurocoach.domain.progress import (
    ProgressSummary,
    WorkloadAlert,
    summarize_progress,
    workload_alert,
)
from neurocoach.domain.transitions import apply_transition, revert_transition
from neurocoach.infra.repositories import from_db_datetime

MAX_PAGE_SIZE = 50
USERNAME_TAKEN = "Ce nom d'utilisateur est déjà pris. Choisissez-en un autre."
_PREFERENCE_FIELDS = (
    "response_length",
    "max_visible_tasks",
    "one_question_at_a_time",
    "deadlines_enabled",
    "cadence",
    "display_timezone",
)


@dataclass(frozen=True)
class StatusChange:
    task: Task
    event_id: str | None
    warnings: list[str] = field(default_factory=list)
    unmet_dependencies: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.event_id is not None


class CoachService(BaseService):
    def check_deadlines(self, user_id: str) -> int:
        """Enregistre les rappels et la pause dans la même transaction SQLite."""
        now = self.clock.now()
        with self._write() as repo:
            prefs = self._preferences(repo, user_id, now)
            if not prefs.deadlines_enabled:
                return 0
            today = self._today(prefs, now)
            delivered = {
                (event.task_id, event.payload.get("due"), event.payload.get("kind"))
                for event in repo.list_events(user_id)
                if event.type is EventType.DEADLINE_NOTICE
            }
            count = 0
            for project in repo.list_projects(user_id):
                if project.paused_at:
                    continue
                overdue = []
                for task in repo.load_snapshot(user_id, project.id).ordered_tasks():
                    if not task.due_date or task.status is TaskStatus.DONE:
                        continue
                    days = (task.due_date - today).days
                    if days > 1:
                        continue
                    due = task.due_date.isoformat()
                    kind = "overdue" if days < 0 else "reminder"
                    if (task.id, due, kind) in delivered:
                        continue
                    if days < 0:
                        overdue.append(task.ref)
                    text = (
                        f"L'échéance du {task.due_date:%d/%m/%Y} est passée pour « {task.title} ». "
                        "Le projet est en pause. À votre retour, indiquez où vous en êtes."
                        if days < 0
                        else f"« {task.title} » arrive à échéance le {task.due_date:%d/%m/%Y}. "
                        "Indiquez si la tâche est terminée ou si vous avez besoin de plus de temps."
                    )
                    repo.insert_event(
                        make_event(
                            user_id,
                            EventType.DEADLINE_NOTICE,
                            now=now,
                            project_id=project.id,
                            task_id=task.id,
                            payload={"due": due, "kind": kind, "text": text},
                        )
                    )
                    count += 1
                if overdue:
                    note = "Échéance dépassée sans validation : " + ", ".join(overdue)
                    repo.update_project(
                        updated(project, paused_at=now, pause_note=note, updated_at=now)
                    )
                    repo.insert_event(
                        make_event(
                            user_id,
                            EventType.PROJECT_PAUSED,
                            now=now,
                            project_id=project.id,
                            payload={"note": note, "automatic": True},
                        )
                    )
            return count

    def deadline_notices(self, user_id: str, project_id: str | None = None) -> list[ActivityEvent]:
        return [
            event
            for event in self.list_events(user_id, project_id)
            if event.type is EventType.DEADLINE_NOTICE
        ]

    # --- utilisateurs et preferences ------------------------------------------------
    def ensure_user(self, user_id: str, display_name: str, *, username: str | None = None) -> User:
        """Cree l'utilisateur fictif et ses preferences par defaut s'ils n'existent pas."""
        now = self.clock.now()
        with self._write() as repo:
            user = repo.get_user(user_id)
            if user is None:
                key = username_key(username) if username else None
                if key and repo.find_user_by_username_key(key) is not None:
                    key = username = None  # nom deja pris : l'espace reste rouvrable par son id
                user = build(
                    User,
                    id=user_id,
                    display_name=display_name,
                    created_at=now,
                    first_name=display_name.split(" ")[0] if username else None,
                    username=username,
                )
                repo.insert_user(user, key)
            if repo.get_preferences(user_id) is None:
                repo.save_preferences(self._default_preferences(user_id, now))
            return user

    def list_users(self) -> list[User]:
        with self._read() as repo:
            return repo.list_users()

    # --- profils locaux (D-76) : pas une authentification -------------------------------
    def register_user(self, first_name: str, last_name: str, username: str) -> User:
        """Cree un profil et ses preferences. Le nom d'utilisateur est unique sans tenir compte
        des majuscules ni des espaces de bord ; un doublon est refuse avec un message clair."""
        profile = validate_profile(first_name, last_name, username)
        now = self.clock.now()
        try:
            with self._write() as repo:
                if repo.find_user_by_username_key(profile.username_key) is not None:
                    raise DomainError(ErrorCode.VALIDATION_ERROR, USERNAME_TAKEN)
                user = build(
                    User,
                    id=new_id("usr"),
                    display_name=profile.display_name,
                    created_at=now,
                    first_name=profile.first_name,
                    last_name=profile.last_name,
                    username=profile.username,
                )
                repo.insert_user(user, profile.username_key)
                repo.save_preferences(self._default_preferences(user.id, now))
                repo.insert_event(make_event(user.id, EventType.PROFILE_CREATED, now=now))
                return user
        except DomainError as exc:
            if isinstance(exc.__cause__, sqlite3.IntegrityError):
                # Deux inscriptions simultanees : l'index unique tranche.
                raise DomainError(ErrorCode.VALIDATION_ERROR, USERNAME_TAKEN) from exc
            raise

    def find_user(self, username: str) -> User | None:
        """Espace local correspondant a ce nom d'utilisateur (casse et espaces ignores)."""
        key = username_key(username or "")
        if not key:
            return None
        with self._read() as repo:
            return repo.find_user_by_username_key(key)

    def get_user(self, user_id: str) -> User | None:
        with self._read() as repo:
            return repo.get_user(user_id)

    def update_profile(self, user_id: str, first_name: str, last_name: str) -> User:
        """Prenom et nom modifiables ; le nom d'utilisateur ne change pas."""
        with self._read() as repo:
            current = repo.get_user(user_id)
        if current is None:
            raise DomainError(ErrorCode.NOT_FOUND, "Profil introuvable.")
        profile = validate_profile(first_name, last_name, current.username or "espace")
        now = self.clock.now()
        with self._write() as repo:
            repo.update_user_names(
                user_id, profile.first_name, profile.last_name, profile.display_name
            )
            repo.insert_event(make_event(user_id, EventType.PROFILE_UPDATED, now=now))
            updated_user = repo.get_user(user_id)
            assert updated_user is not None
            return updated_user

    def get_preferences(self, user_id: str) -> Preferences:
        with self._read() as repo:
            return self._preferences(repo, user_id, self.clock.now())

    def update_preferences(self, user_id: str, **changes: Any) -> Preferences:
        """PF-01 : appele uniquement depuis l'ecran des preferences."""
        unknown = set(changes) - set(_PREFERENCE_FIELDS)
        if unknown:
            raise DomainError(
                ErrorCode.VALIDATION_ERROR, f"Préférence inconnue : {sorted(unknown)}."
            )
        now = self.clock.now()
        with self._write() as repo:
            current = self._preferences(repo, user_id, now)
            candidate = updated(current, **changes)
            diff = {
                name: jsonable(getattr(candidate, name))
                for name in changes
                if getattr(candidate, name) != getattr(current, name)
            }
            if not diff:
                return current
            saved = updated(candidate, updated_at=now)
            repo.save_preferences(saved)
            repo.insert_event(
                make_event(
                    user_id, EventType.PREFERENCES_UPDATED, now=now, payload={"changed": diff}
                )
            )
            return saved

    # --- projets --------------------------------------------------------------------
    def create_project(self, user_id: str, title: str, idea: str = "") -> Project:
        """R-CONF-01c : projet vide (brouillon) dont le titre est saisi par l'utilisateur."""
        now = self.clock.now()
        with self._write() as repo:
            self._preferences(repo, user_id, now)
            project = build(
                Project,
                id=new_id("prj"),
                user_id=user_id,
                title=title,
                idea=idea,
                created_at=now,
                updated_at=now,
            )
            repo.insert_project(project)
            repo.insert_thread(
                ConversationThread(
                    id=new_id("thr"), user_id=user_id, project_id=project.id, created_at=now
                )
            )
            repo.insert_event(
                make_event(user_id, EventType.PROJECT_CREATED, now=now, project_id=project.id)
            )
            return project

    def start_project(
        self, user_id: str, *, unused: Callable[[Project], bool] | None = None
    ) -> Project:
        """D-76 : projet ouvert depuis « Créer votre projet », avant tout titre. Un projet
        commence et encore vide (titre provisoire, aucune idee) est repris plutot que double.
        D-82 : ``unused`` confirme qu'aucun message n'y a ete echange (l'idee n'est plus
        enregistree avant d'etre comprise : sans ce controle, un projet en pleine conversation
        etait repris au lieu d'en creer un nouveau)."""
        with self._read() as repo:
            for project in reversed(repo.list_projects(user_id)):
                if (
                    project.title_pending
                    and not project.idea
                    and project.status.value == "draft"
                    and (unused is None or unused(project))
                ):
                    return project
        now = self.clock.now()
        with self._write() as repo:
            self._preferences(repo, user_id, now)
            project = build(
                Project,
                id=new_id("prj"),
                user_id=user_id,
                title=PLACEHOLDER_TITLE,
                created_at=now,
                updated_at=now,
                title_pending=True,
            )
            repo.insert_project(project)
            repo.insert_thread(
                ConversationThread(
                    id=new_id("thr"), user_id=user_id, project_id=project.id, created_at=now
                )
            )
            repo.insert_event(
                make_event(user_id, EventType.PROJECT_CREATED, now=now, project_id=project.id)
            )
            return project

    def rename_project(self, user_id: str, project_id: str, title: str) -> Project:
        """Titre choisi ou accepte par l'utilisateur (clic) ; journalise."""
        clean = " ".join((title or "").split())
        if len(clean.split()) > 7:
            raise DomainError(ErrorCode.VALIDATION_ERROR, "Le titre doit tenir en 7 mots maximum.")
        if not 3 <= len(clean) <= 120:
            raise DomainError(
                ErrorCode.VALIDATION_ERROR, "Le titre doit faire entre 3 et 120 caractères."
            )
        now = self.clock.now()
        with self._write() as repo:
            before = repo.get_project(user_id, project_id)
            repo.rename_project(user_id, project_id, clean, now)
            repo.insert_event(
                make_event(
                    user_id,
                    EventType.PROJECT_RENAMED,
                    now=now,
                    project_id=project_id,
                    payload={"before": before.title, "after": clean},
                )
            )
            return repo.get_project(user_id, project_id)

    def record_idea(self, user_id: str, project_id: str, text: str) -> Project:
        """Premier message d'un projet commence par la conversation : devient son idee (elle
        oriente la clarification et le titre propose). Une idee existante n'est pas remplacee."""
        with self._write() as repo:
            project = repo.get_project(user_id, project_id)
            idea = " ".join((text or "").split())[:1000]
            # D-77 : une idee generique (« créer mon propre business ») est remplacee par la
            # premiere description concrete ; une idee concrete n'est jamais remplacee.
            vague = not project.idea or suggest_title(project.idea) == FALLBACK_TITLE
            if idea and vague and (not project.idea or suggest_title(idea) != FALLBACK_TITLE):
                repo.set_project_idea(user_id, project_id, idea, self.clock.now())
                project = repo.get_project(user_id, project_id)
            return project

    def update_idea(self, user_id: str, project_id: str, idea: str) -> Project:
        """D-78 : sujet du projet tel que le coach l'a compris au dernier message (une
        precision ou une correction de l'utilisateur remplace l'ancienne idee). Projets sans
        plan seulement ; aucun evenement (ce n'est pas une decision de l'utilisateur)."""
        clean = " ".join((idea or "").split())[:1000]
        with self._write() as repo:
            project = repo.get_project(user_id, project_id)
            if clean and project.status.value == "draft" and clean != project.idea:
                repo.set_project_idea(user_id, project_id, clean, self.clock.now())
                project = repo.get_project(user_id, project_id)
            return project

    def last_activity(self, user_id: str) -> dict[str, datetime]:
        """Date du dernier evenement journalise, par projet (conversation non comprise)."""
        with self._read() as repo:
            return {pid: from_db_datetime(at) for pid, at in repo.last_event_times(user_id).items()}

    def list_projects(self, user_id: str) -> list[Project]:
        with self._read() as repo:
            return repo.list_projects(user_id)

    def get_project(self, user_id: str, project_id: str) -> Project:
        with self._read() as repo:
            return repo.get_project(user_id, project_id)

    def get_snapshot(self, user_id: str, project_id: str) -> ProjectSnapshot:
        with self._read() as repo:
            return repo.load_snapshot(user_id, project_id)

    def get_conversation_thread(self, user_id: str, project_id: str) -> ConversationThread:
        """D-21 : un fil par couple (utilisateur, projet)."""
        now = self.clock.now()
        with self._write() as repo:
            repo.get_project(user_id, project_id)
            thread = repo.get_thread(user_id, project_id)
            if thread is None:
                thread = ConversationThread(
                    id=new_id("thr"), user_id=user_id, project_id=project_id, created_at=now
                )
                repo.insert_thread(thread)
            return thread

    # --- lectures -------------------------------------------------------------------
    def list_tasks(
        self,
        user_id: str,
        project_id: str,
        *,
        status: TaskStatus | str | None = None,
        phase_id: str | None = None,
        limit: int = MAX_PAGE_SIZE,
        offset: int = 0,
    ) -> list[Task]:
        if not 1 <= limit <= MAX_PAGE_SIZE or offset < 0:
            raise DomainError(ErrorCode.VALIDATION_ERROR, "Pagination invalide.")
        wanted = TaskStatus(status) if status is not None else None
        snapshot = self.get_snapshot(user_id, project_id)
        tasks = [
            task
            for task in snapshot.ordered_tasks()
            if (wanted is None or task.status is wanted)
            and (phase_id is None or task.phase_id == phase_id)
        ]
        return tasks[offset : offset + limit]

    def get_progress(self, user_id: str, project_id: str) -> ProgressSummary:
        now = self.clock.now()
        with self._read() as repo:
            snapshot = repo.load_snapshot(user_id, project_id)
            today = self._today(self._preferences(repo, user_id, now), now)
        return summarize_progress(snapshot.phases.values(), snapshot.tasks.values(), today=today)

    def get_workload_alert(self, user_id: str, project_id: str) -> WorkloadAlert | None:
        now = self.clock.now()
        with self._read() as repo:
            snapshot = repo.load_snapshot(user_id, project_id)
            today = self._today(self._preferences(repo, user_id, now), now)
        return workload_alert(
            snapshot.tasks.values(),
            available_minutes_per_day=snapshot.project.available_minutes_per_day,
            horizon_date=snapshot.project.horizon_date,
            today=today,
        )

    def get_next_actions(self, user_id: str, project_id: str) -> NextActions:
        now = self.clock.now()
        with self._read() as repo:
            snapshot = repo.load_snapshot(user_id, project_id)
            prefs = self._preferences(repo, user_id, now)
        return select_next_actions(
            snapshot.phases.values(),
            snapshot.tasks,
            snapshot.dependencies,
            today=self._today(prefs, now),
            max_visible=prefs.max_visible_tasks,
            deadlines_enabled=prefs.deadlines_enabled,
            available_minutes_per_day=snapshot.project.available_minutes_per_day,
        )

    def list_events(self, user_id: str, project_id: str | None = None) -> list[ActivityEvent]:
        with self._read() as repo:
            if project_id is not None:
                repo.get_project(user_id, project_id)
            return repo.list_events(user_id, project_id)

    # --- statut : ecriture directe, journalisee et annulable --------------------------
    def set_task_status(
        self, user_id: str, task_id: str, status: TaskStatus | str, reason: str | None = None
    ) -> StatusChange:
        now = self.clock.now()
        with self._write() as repo:
            task = repo.get_task(user_id, task_id)
            outcome = apply_transition(task, status, reason=reason, now=now)
            if not outcome.changed:
                return StatusChange(task=task, event_id=None)
            snapshot = repo.load_snapshot(user_id, task.project_id)
            warnings: list[str] = []
            unmet_refs: list[str] = []
            if outcome.to_status in (TaskStatus.IN_PROGRESS, TaskStatus.DONE):
                unmet = unmet_dependencies(task.id, snapshot.tasks, snapshot.dependencies)
                unmet_refs = [snapshot.tasks[dep].ref for dep in unmet if dep in snapshot.tasks]
                if unmet_refs:
                    warnings.append("UNMET_DEPENDENCIES")  # T-05
            repo.update_task(outcome.task)
            event = make_event(
                user_id,
                EventType.TASK_STATUS_CHANGED,
                now=now,
                project_id=task.project_id,
                task_id=task.id,
                payload={
                    "task_ref": task.ref,
                    "from": outcome.from_status.value,
                    "to": outcome.to_status.value,
                    "reason": outcome.task.blocked_reason,
                    "previous_reason": outcome.previous_reason,
                    "previous_completed_at": jsonable(outcome.previous_completed_at),
                },
            )
            repo.insert_event(event)
            return StatusChange(outcome.task, event.id, warnings, unmet_refs)

    def undo_status_change(self, user_id: str, event_id: str) -> Task:
        """U-01 a U-04 : annule le dernier changement de statut d'une tache."""
        now = self.clock.now()
        with self._write() as repo:
            event = repo.get_event(user_id, event_id)
            if event.type is EventType.TASK_STATUS_REVERTED:
                raise DomainError(
                    ErrorCode.INVALID_TRANSITION, "Une annulation ne peut pas être annulée."
                )
            if event.type is not EventType.TASK_STATUS_CHANGED:
                raise DomainError(ErrorCode.VALIDATION_ERROR, "Cet événement n'est pas annulable.")
            if event.task_id is None:
                raise DomainError(ErrorCode.NOT_FOUND, "Tâche introuvable.")
            latest = repo.latest_status_event(event.task_id)
            if latest is None or latest.id != event.id:
                raise DomainError(
                    ErrorCode.INVALID_TRANSITION,
                    "Seul le dernier changement de statut peut être annulé.",
                )
            task = repo.get_task(user_id, event.task_id)
            if task.status.value != event.payload["to"]:
                raise DomainError(ErrorCode.INVALID_TRANSITION, "Le statut a changé depuis.")
            previous_completed: datetime | None = from_db_datetime(
                event.payload.get("previous_completed_at")
            )
            reverted = revert_transition(
                task,
                from_status=TaskStatus(event.payload["from"]),
                previous_reason=event.payload.get("previous_reason"),
                previous_completed_at=previous_completed,
                now=now,
            )
            repo.update_task(reverted)
            repo.insert_event(
                make_event(
                    user_id,
                    EventType.TASK_STATUS_REVERTED,
                    now=now,
                    project_id=task.project_id,
                    task_id=task.id,
                    reverts_event_id=event.id,
                    payload={
                        "task_ref": task.ref,
                        "from": task.status.value,
                        "to": reverted.status.value,
                    },
                )
            )
            return reverted
