"""Base verrouillee par un autre processus : erreur claire, aucune ecriture partielle (US-08)."""

from __future__ import annotations

import sqlite3

import pytest

from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.models import TaskStatus


def test_locked_database_gives_a_clear_error_and_writes_nothing(app, alice_project, monkeypatch):
    monkeypatch.setattr(
        "neurocoach.infra.db.Database.connect",
        _short_timeout(app.database.connect),
    )
    user, task = alice_project.user_id, alice_project.tasks[0]
    blocker = sqlite3.connect(app.database.path, isolation_level=None)
    try:
        blocker.execute("BEGIN IMMEDIATE")  # verrou d'ecriture tenu par « un autre processus »
        with pytest.raises(DomainError) as error:
            app.coach.set_task_status(user, task.id, TaskStatus.DONE)
        assert error.value.code is ErrorCode.STORAGE_ERROR
        assert error.value.user_message.startswith("Enregistrement impossible")
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()
    monkeypatch.undo()
    assert app.coach.list_tasks(user, alice_project.project.id)[0].status is TaskStatus.TODO
    # Une fois le verrou libere, la meme operation reussit.
    assert app.coach.set_task_status(user, task.id, TaskStatus.DONE).changed


def _short_timeout(connect):
    def wrapped(*args, **kwargs):
        conn = connect()
        conn.execute("PRAGMA busy_timeout = 200")
        return conn

    return wrapped
