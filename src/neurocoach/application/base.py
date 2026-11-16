"""Socle commun des services : unite de travail, reglages, fabrique d'evenements."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from neurocoach.application.ports import ConversationStore, NullConversationStore
from neurocoach.domain.clock import Clock, local_today
from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.models import ActivityEvent, EventType, Preferences, new_id
from neurocoach.infra.db import Database
from neurocoach.infra.repositories import SqliteRepository


@dataclass(frozen=True)
class ServiceSettings:
    pending_action_ttl_minutes: int = 15
    default_timezone: str = "Europe/Paris"


@contextmanager
def unit_of_work(db: Database, *, write: bool) -> Iterator[SqliteRepository]:
    """Transaction atomique ; toute erreur SQLite devient STORAGE_ERROR (I-09, US-08)."""
    try:
        with db.transaction(write=write) as conn:
            yield SqliteRepository(conn)
    except sqlite3.Error as exc:
        raise DomainError(ErrorCode.STORAGE_ERROR) from exc


def make_event(
    user_id: str,
    event_type: EventType,
    *,
    now: datetime,
    project_id: str | None = None,
    task_id: str | None = None,
    pending_action_id: str | None = None,
    payload: dict[str, Any] | None = None,
    reverts_event_id: str | None = None,
) -> ActivityEvent:
    return ActivityEvent(
        id=new_id("evt"),
        user_id=user_id,
        project_id=project_id,
        task_id=task_id,
        pending_action_id=pending_action_id,
        type=event_type,
        payload=payload or {},
        reverts_event_id=reverts_event_id,
        created_at=now,
    )


class BaseService:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        settings: ServiceSettings | None = None,
        conversations: ConversationStore | None = None,
    ) -> None:
        self.db = db
        self.clock = clock
        self.settings = settings or ServiceSettings()
        self.conversations = conversations or NullConversationStore()

    def _write(self) -> Any:
        return unit_of_work(self.db, write=True)

    def _read(self) -> Any:
        return unit_of_work(self.db, write=False)

    def _default_preferences(self, user_id: str, now: datetime) -> Preferences:
        return Preferences(
            user_id=user_id, display_timezone=self.settings.default_timezone, updated_at=now
        )

    def _preferences(self, repo: SqliteRepository, user_id: str, now: datetime) -> Preferences:
        if repo.get_user(user_id) is None:
            raise DomainError(ErrorCode.NOT_FOUND, "Utilisateur introuvable.")
        return repo.get_preferences(user_id) or self._default_preferences(user_id, now)

    def _today(self, prefs: Preferences, now: datetime) -> date:
        return local_today(now, prefs.display_timezone)
