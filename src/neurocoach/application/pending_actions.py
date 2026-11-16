"""Cycle de vie des actions en attente (DOMAIN_CONTRACTS section 5).

Une ecriture soumise a confirmation n'est appliquee que par ``confirm``, en une seule
transaction : reservation conditionnelle, ecritures, journal (I-07 a I-09).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from neurocoach.application.base import BaseService, make_event
from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.models import (
    ActionStatus,
    ActionType,
    EventType,
    PendingAction,
    TaskStatus,
    new_id,
)
from neurocoach.domain.plans import (
    DEADLINES_DISABLED_DETAIL,
    DEADLINES_DISABLED_SINCE_DETAIL,
    AddPhase,
    AddTask,
    BriefUpdate,
    Change,
    ChangeCommand,
    PlanDraft,
    PlanEdits,
    apply_action_command,
    has_deadlines,
    jsonable,
    plan_create_command,
    revise_plan_command,
    strip_deadlines,
)
from neurocoach.domain.transitions import apply_transition
from neurocoach.infra.repositories import SqliteRepository

# D-85 : actions d'etat, sans commande de plan : appliquees par leurs propres fonctions.
_STATE_ACTIONS = frozenset(
    {ActionType.PROJECT_PAUSE, ActionType.PROJECT_RESUME, ActionType.TASKS_COMPLETE}
)

_CONTENT_ACTIONS = frozenset(
    {
        ActionType.PLAN_CREATE,
        ActionType.PLAN_REPLAN,
        ActionType.TASK_CREATE,
        ActionType.TASK_UPDATE,
        ActionType.TASK_DELETE,
    }
)

_APPLIED_EVENT = {
    ActionType.PLAN_CREATE: EventType.PLAN_APPLIED,
    ActionType.PLAN_REPLAN: EventType.PLAN_REPLANNED,
    ActionType.TASK_CREATE: EventType.TASK_CREATED,
    ActionType.TASK_UPDATE: EventType.TASK_UPDATED,
    ActionType.TASK_DELETE: EventType.TASK_DELETED,
}

_FINAL_EVENT = {
    ActionStatus.CANCELLED: EventType.PENDING_ACTION_CANCELLED,
    ActionStatus.EXPIRED: EventType.PENDING_ACTION_EXPIRED,
    ActionStatus.SUPERSEDED: EventType.PENDING_ACTION_SUPERSEDED,
    ActionStatus.FAILED: EventType.PENDING_ACTION_FAILED,
}


@dataclass(frozen=True)
class ActionOutcome:
    action: PendingAction
    result: dict[str, Any]


class PendingActionService(BaseService):
    # --- creation -------------------------------------------------------------------
    def request_change(
        self,
        user_id: str,
        project_id: str,
        action_type: ActionType | str,
        command: ChangeCommand,
    ) -> PendingAction:
        """Valide, calcule l'apercu et cree l'action ; aucune ecriture metier (5.1)."""
        action_type = ActionType(action_type)
        if action_type not in _CONTENT_ACTIONS:
            raise DomainError(ErrorCode.VALIDATION_ERROR, "Utilisez la demande dédiée.")
        now = self.clock.now()
        with self._write() as repo:
            prefs = self._preferences(repo, user_id, now)
            removed = False
            if not prefs.deadlines_enabled and has_deadlines(command):
                # D-58 : quelle que soit l'origine (modele, revision, plan), aucune echeance
                # n'entre dans une proposition quand l'utilisateur les a desactivees.
                command, removed = strip_deadlines(command), True
                if not command.operations and command.brief is None:
                    raise DomainError(ErrorCode.VALIDATION_ERROR, DEADLINES_DISABLED_DETAIL)
            snapshot = repo.load_snapshot(user_id, project_id)
            result = apply_action_command(
                action_type, snapshot, command, now=now, today=self._today(prefs, now)
            )
            if not result.changes:
                detail = DEADLINES_DISABLED_DETAIL if removed else "Aucun changement à proposer."
                raise DomainError(ErrorCode.VALIDATION_ERROR, detail)
            return self._create(
                repo,
                user_id=user_id,
                project_id=project_id,
                action_type=action_type,
                payload={"command": command.model_dump(mode="json"), "deadlines_removed": removed},
                preview=result.changes,
                expected_versions=snapshot.versions(),
                now=now,
            )

    def request_plan(
        self,
        user_id: str,
        project_id: str,
        draft: PlanDraft,
        brief: BriefUpdate | None = None,
    ) -> PendingAction:
        """Convertit un brouillon de plan (echeances selon PF-05) puis cree ``plan.create``."""
        now = self.clock.now()
        with self._read() as repo:
            prefs = self._preferences(repo, user_id, now)
        command = plan_create_command(
            draft,
            today=self._today(prefs, now),
            deadlines_enabled=prefs.deadlines_enabled,
            brief=brief,
        )
        return self.request_change(user_id, project_id, ActionType.PLAN_CREATE, command)

    def plan_draft_view(self, user_id: str, action_id: str) -> list[dict[str, Any]]:
        """Contenu modifiable d'un plan propose : phases et taches designees par leur cle."""
        action = self._editable_plan(user_id, action_id)
        command = ChangeCommand.model_validate(action.payload["command"])
        phases: list[dict[str, Any]] = []
        for op in command.operations:
            if isinstance(op, AddPhase):
                phases.append({"key": op.key, "title": op.title, "tasks": []})
            elif isinstance(op, AddTask):
                phase = next(p for p in phases if p["key"] == op.phase)
                phase["tasks"].append(
                    {
                        "key": op.key,
                        "title": op.title,
                        "acceptance_criteria": op.acceptance_criteria,
                        "estimate_minutes": op.estimate_minutes,
                    }
                )
        return phases

    def revise_plan(self, user_id: str, action_id: str, edits: PlanEdits) -> PendingAction:
        """5.5 : nouvelle proposition corrigee ; l'ancienne est remplacee, rien n'est applique."""
        action = self._editable_plan(user_id, action_id)
        command = revise_plan_command(
            ChangeCommand.model_validate(action.payload["command"]), edits
        )
        assert action.project_id is not None
        return self.request_change(user_id, action.project_id, ActionType.PLAN_CREATE, command)

    def _editable_plan(self, user_id: str, action_id: str) -> PendingAction:
        action = self.get_action(user_id, action_id)
        if action.status is not ActionStatus.PENDING:
            raise DomainError(ErrorCode.ACTION_ALREADY_DECIDED, status=action.status.value)
        if action.action_type is not ActionType.PLAN_CREATE:
            raise DomainError(ErrorCode.VALIDATION_ERROR, "Seul un plan proposé peut être modifié.")
        if self.clock.now() >= action.expires_at:
            raise DomainError(ErrorCode.ACTION_EXPIRED)
        return action

    def request_project_deletion(self, user_id: str, project_id: str) -> PendingAction:
        now = self.clock.now()
        with self._write() as repo:
            snapshot = repo.load_snapshot(user_id, project_id)
            change = Change(
                op="delete",
                entity="project",
                ref=snapshot.project.title,
                before={"phases": len(snapshot.phases), "tasks": len(snapshot.tasks)},
            )
            return self._create(
                repo,
                user_id=user_id,
                project_id=project_id,
                action_type=ActionType.PROJECT_DELETE,
                payload={},
                preview=[change],
                expected_versions={"project": snapshot.project.version},
                now=now,
            )

    # --- D-85 : pause, reprise, taches terminees confirmees ensemble -------------------
    def request_pause(self, user_id: str, project_id: str, note: str | None) -> PendingAction:
        """Pause demandee dans la conversation : rien ne change avant le clic."""
        now = self.clock.now()
        with self._write() as repo:
            project = repo.get_project(user_id, project_id)
            if project.paused_at is not None:
                raise DomainError(ErrorCode.VALIDATION_ERROR, "Le projet est déjà en pause.")
            after = {"pause": "en pause", **({"note": note} if note else {})}
            change = Change(
                op="update", entity="project", ref=project.title,
                before={"pause": "en cours"}, after=after,
            )  # fmt: skip
            return self._create(
                repo,
                user_id=user_id,
                project_id=project_id,
                action_type=ActionType.PROJECT_PAUSE,
                payload={"note": note},
                preview=[change],
                expected_versions={"project": project.version, "paused": False},
                now=now,
            )

    def request_resume(self, user_id: str, project_id: str) -> PendingAction:
        now = self.clock.now()
        with self._write() as repo:
            project = repo.get_project(user_id, project_id)
            if project.paused_at is None:
                raise DomainError(ErrorCode.VALIDATION_ERROR, "Le projet n'est pas en pause.")
            change = Change(
                op="update", entity="project", ref=project.title,
                before={"pause": "en pause"}, after={"pause": "en cours"},
            )  # fmt: skip
            return self._create(
                repo,
                user_id=user_id,
                project_id=project_id,
                action_type=ActionType.PROJECT_RESUME,
                payload={},
                preview=[change],
                expected_versions={"project": project.version, "paused": True},
                now=now,
            )

    def request_tasks_done(
        self, user_id: str, project_id: str, task_ids: list[str]
    ) -> PendingAction:
        """Plusieurs taches que la personne dit avoir terminees : un seul clic les confirme."""
        now = self.clock.now()
        with self._write() as repo:
            snapshot = repo.load_snapshot(user_id, project_id)
            chosen = [snapshot.tasks[t] for t in dict.fromkeys(task_ids) if t in snapshot.tasks]
            chosen = [task for task in chosen if task.status is not TaskStatus.DONE]
            if not chosen:
                raise DomainError(ErrorCode.VALIDATION_ERROR, "Aucune tâche à terminer.")
            changes = [
                Change(
                    op="update",
                    entity="task",
                    ref=task.ref,
                    before={"title": task.title, "status": task.status.value},
                    after={"status": TaskStatus.DONE.value},
                )
                for task in sorted(chosen, key=lambda t: t.number)
            ]
            return self._create(
                repo,
                user_id=user_id,
                project_id=project_id,
                action_type=ActionType.TASKS_COMPLETE,
                payload={"task_ids": [task.id for task in chosen]},
                preview=changes,
                expected_versions=snapshot.versions(),
                now=now,
            )

    def request_user_data_deletion(self, user_id: str) -> PendingAction:
        now = self.clock.now()
        with self._write() as repo:
            self._preferences(repo, user_id, now)
            counts = repo.count_user_content(user_id)
            change = Change(op="delete", entity="user", ref="vos données", before=counts)
            return self._create(
                repo,
                user_id=user_id,
                project_id=None,
                action_type=ActionType.USER_DELETE_DATA,
                payload={},
                preview=[change],
                expected_versions={},
                now=now,
            )

    def _create(
        self,
        repo: SqliteRepository,
        *,
        user_id: str,
        project_id: str | None,
        action_type: ActionType,
        payload: dict[str, Any],
        preview: list[Change],
        expected_versions: dict[str, Any],
        now: datetime,
    ) -> PendingAction:
        previous = repo.find_pending(user_id, project_id)
        if previous is not None:  # I-12 : la nouvelle proposition remplace l'ancienne.
            self._decide(repo, previous, ActionStatus.SUPERSEDED, now, {"replaced": True})
        action = PendingAction(
            id=new_id("pac"),
            user_id=user_id,
            project_id=project_id,
            action_type=action_type,
            payload=payload,
            preview=[change.model_dump(mode="json") for change in preview],
            expected_versions=expected_versions,
            idempotency_key=uuid.uuid4().hex,
            created_at=now,
            expires_at=now + timedelta(minutes=self.settings.pending_action_ttl_minutes),
        )
        repo.insert_action(action)
        repo.insert_event(
            make_event(
                user_id,
                EventType.PENDING_ACTION_CREATED,
                now=now,
                project_id=project_id,
                pending_action_id=action.id,
                payload={"action_type": action_type.value},
            )
        )
        return action

    def _decide(
        self,
        repo: SqliteRepository,
        action: PendingAction,
        status: ActionStatus,
        now: datetime,
        result: dict[str, Any],
    ) -> bool:
        if not repo.decide_action(action.id, status, now, result):
            return False
        repo.insert_event(
            make_event(
                action.user_id,
                _FINAL_EVENT[status],
                now=now,
                project_id=action.project_id,
                pending_action_id=action.id,
                payload={"action_type": action.action_type.value, **result},
            )
        )
        return True

    # --- lecture --------------------------------------------------------------------
    def get_action(self, user_id: str, action_id: str) -> PendingAction:
        with self._read() as repo:
            return repo.get_action(user_id, action_id)

    def get_pending(self, user_id: str, project_id: str | None) -> PendingAction | None:
        with self._read() as repo:
            return repo.find_pending(user_id, project_id)

    # --- decision -------------------------------------------------------------------
    def cancel(self, user_id: str, action_id: str) -> PendingAction:
        """5.4 : annulation sans aucune ecriture metier ; sans effet si deja decidee."""
        now = self.clock.now()
        with self._write() as repo:
            action = repo.get_action(user_id, action_id)
            if action.status is ActionStatus.PENDING:
                self._decide(repo, action, ActionStatus.CANCELLED, now, {})
            return repo.get_action(user_id, action_id)

    def confirm(self, user_id: str, action_id: str) -> ActionOutcome:
        """5.3 : application atomique, a usage unique, avec expiration et versions."""
        now = self.clock.now()
        deferred: DomainError | None = None
        loaded = False
        try:
            with self._write() as repo:
                action = repo.get_action(user_id, action_id)
                loaded = True
                if action.status is not ActionStatus.PENDING:
                    raise DomainError(
                        ErrorCode.ACTION_ALREADY_DECIDED,
                        status=action.status.value,
                        result=action.result,
                    )
                if now >= action.expires_at:
                    self._decide(
                        repo, action, ActionStatus.EXPIRED, now, {"error": ErrorCode.ACTION_EXPIRED}
                    )
                    deferred = DomainError(ErrorCode.ACTION_EXPIRED)
                elif not self._versions_match(repo, action):
                    self._decide(
                        repo,
                        action,
                        ActionStatus.FAILED,
                        now,
                        {"error": ErrorCode.VERSION_CONFLICT},
                    )
                    deferred = DomainError(ErrorCode.VERSION_CONFLICT)
                else:
                    # Reservation conditionnelle avant toute ecriture (double clic, concurrence).
                    if not repo.decide_action(action.id, ActionStatus.APPLIED, now, None):
                        raise DomainError(ErrorCode.ACTION_ALREADY_DECIDED)
                    result = self._apply(repo, action, now)
                    repo.set_action_result(action.id, result)
                    final = repo.get_action(user_id, action_id)
        except DomainError as exc:
            if loaded and exc.code is not ErrorCode.ACTION_ALREADY_DECIDED:
                self._mark_failed(user_id, action_id, exc.code)
            raise
        except Exception as exc:
            if loaded:
                self._mark_failed(user_id, action_id, ErrorCode.STORAGE_ERROR)
            raise DomainError(ErrorCode.STORAGE_ERROR) from exc
        if deferred is not None:
            raise deferred
        return ActionOutcome(final, result)

    def _versions_match(self, repo: SqliteRepository, action: PendingAction) -> bool:
        expected = action.expected_versions
        if action.action_type is ActionType.USER_DELETE_DATA:
            return True
        if action.project_id is None:
            return False
        snapshot = repo.load_snapshot(action.user_id, action.project_id)
        if action.action_type is ActionType.PROJECT_DELETE:
            return snapshot.project.version == expected.get("project")
        if action.action_type in (ActionType.PROJECT_PAUSE, ActionType.PROJECT_RESUME):
            paused = snapshot.project.paused_at is not None
            return snapshot.project.version == expected.get("project") and paused == expected.get(
                "paused"
            )
        return snapshot.versions() == expected

    def _mark_failed(self, user_id: str, action_id: str, code: ErrorCode) -> None:
        now = self.clock.now()
        try:
            with self._write() as repo:
                action = repo.get_action(user_id, action_id)
                if action.status is ActionStatus.PENDING:
                    self._decide(repo, action, ActionStatus.FAILED, now, {"error": code.value})
        except DomainError:
            # L'erreur d'origine reste celle remontee a l'appelant.
            return

    def _apply(
        self, repo: SqliteRepository, action: PendingAction, now: datetime
    ) -> dict[str, Any]:
        user_id = action.user_id
        if action.action_type is ActionType.PROJECT_DELETE:
            return self._apply_project_deletion(repo, action, now)
        if action.action_type is ActionType.USER_DELETE_DATA:
            return self._apply_user_deletion(repo, action, now)
        if action.action_type in _STATE_ACTIONS:
            return self._apply_state(repo, action, now)

        assert action.project_id is not None
        prefs = self._preferences(repo, user_id, now)
        snapshot = repo.load_snapshot(user_id, action.project_id)
        command = ChangeCommand.model_validate(action.payload["command"])
        if not prefs.deadlines_enabled and has_deadlines(command):
            # Echeances desactivees entre la proposition et le clic : appliquer sans les dates
            # trahirait l'apercu confirme ; la proposition est refusee, rien n'est ecrit.
            raise DomainError(ErrorCode.VALIDATION_ERROR, DEADLINES_DISABLED_SINCE_DETAIL)
        result = apply_action_command(
            action.action_type, snapshot, command, now=now, today=self._today(prefs, now)
        )
        repo.save_snapshot(snapshot, result.snapshot)
        refs = [change.ref for change in result.changes if change.entity == "task"]
        single_task_id = None
        if action.action_type in (ActionType.TASK_CREATE, ActionType.TASK_UPDATE):
            created_or_updated = set(result.snapshot.tasks) - set(snapshot.tasks) or {
                task_id
                for task_id, task in result.snapshot.tasks.items()
                if snapshot.tasks.get(task_id) != task
            }
            single_task_id = sorted(created_or_updated)[0] if created_or_updated else None
        summary = {
            "changes": len(result.changes),
            "task_refs": refs,
            "project_version": result.snapshot.project.version,
        }
        repo.insert_event(
            make_event(
                user_id,
                _APPLIED_EVENT[action.action_type],
                now=now,
                project_id=action.project_id,
                task_id=single_task_id,
                pending_action_id=action.id,
                payload=summary,
            )
        )
        repo.insert_event(
            make_event(
                user_id,
                EventType.PENDING_ACTION_APPLIED,
                now=now,
                project_id=action.project_id,
                pending_action_id=action.id,
                payload={"action_type": action.action_type.value},
            )
        )
        return summary

    def _apply_state(
        self, repo: SqliteRepository, action: PendingAction, now: datetime
    ) -> dict[str, Any]:
        """D-85 : pause, reprise ou taches terminees, dans la transaction de confirmation."""
        assert action.project_id is not None
        user_id, project_id = action.user_id, action.project_id
        if action.action_type is ActionType.TASKS_COMPLETE:
            refs = []
            for task_id in action.payload["task_ids"]:
                task = repo.get_task(user_id, task_id)
                outcome = apply_transition(task, TaskStatus.DONE, reason=None, now=now)
                if not outcome.changed:
                    continue
                repo.update_task(outcome.task)
                # Meme evenement qu'un changement direct : chaque tache reste annulable.
                repo.insert_event(
                    make_event(
                        user_id,
                        EventType.TASK_STATUS_CHANGED,
                        now=now,
                        project_id=project_id,
                        task_id=task.id,
                        pending_action_id=action.id,
                        payload={
                            "task_ref": task.ref,
                            "from": outcome.from_status.value,
                            "to": outcome.to_status.value,
                            "reason": None,
                            "previous_reason": outcome.previous_reason,
                            "previous_completed_at": jsonable(outcome.previous_completed_at),
                        },
                    )
                )
                refs.append(task.ref)
            summary: dict[str, Any] = {"task_refs": refs, "changes": len(refs)}
        else:
            project = repo.get_project(user_id, project_id)
            pause = action.action_type is ActionType.PROJECT_PAUSE
            update = {
                "paused_at": now if pause else None,
                "pause_note": action.payload.get("note") if pause else None,
                "version": project.version + 1,
                "updated_at": now,
            }
            repo.update_project(project.model_copy(update=update))
            repo.insert_event(
                make_event(
                    user_id,
                    EventType.PROJECT_PAUSED if pause else EventType.PROJECT_RESUMED,
                    now=now,
                    project_id=project_id,
                    pending_action_id=action.id,
                    payload={"note": project.pause_note if not pause else update["pause_note"]},
                )
            )
            summary = {"paused": pause}
        repo.insert_event(
            make_event(
                user_id,
                EventType.PENDING_ACTION_APPLIED,
                now=now,
                project_id=project_id,
                pending_action_id=action.id,
                payload={"action_type": action.action_type.value},
            )
        )
        return summary

    def _apply_project_deletion(
        self, repo: SqliteRepository, action: PendingAction, now: datetime
    ) -> dict[str, Any]:
        assert action.project_id is not None
        project_id = action.project_id
        repo.get_project(action.user_id, project_id)
        threads = [thread.id for thread in repo.list_threads(action.user_id, project_id)]
        repo.delete_project_actions(project_id, keep_action_id=action.id)
        repo.delete_project(action.user_id, project_id)
        # Suppression des checkpoints avant le commit : un echec annule toute la transaction.
        self.conversations.delete_threads(threads)
        repo.insert_event(
            make_event(
                action.user_id,
                EventType.PROJECT_DELETED,
                now=now,
                pending_action_id=action.id,
                payload={"project_id": project_id, "threads_deleted": len(threads)},
            )
        )
        repo.insert_event(
            make_event(
                action.user_id,
                EventType.PENDING_ACTION_APPLIED,
                now=now,
                pending_action_id=action.id,
                payload={"action_type": action.action_type.value},
            )
        )
        return {"deleted_project_id": project_id, "threads_deleted": len(threads)}

    def _apply_user_deletion(
        self, repo: SqliteRepository, action: PendingAction, now: datetime
    ) -> dict[str, Any]:
        counts = repo.count_user_content(action.user_id)
        threads = [thread.id for thread in repo.list_threads(action.user_id)]
        repo.delete_user_content(action.user_id, keep_action_id=action.id)
        repo.save_preferences(self._default_preferences(action.user_id, now))
        self.conversations.delete_threads(threads)
        # E-02 : aucun evenement n'est conserve ; l'action appliquee est la seule trace.
        return {**counts, "threads_deleted": len(threads)}
