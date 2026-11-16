"""Migrations, pragmas et contraintes de la base metier."""

from __future__ import annotations

import sqlite3

import pytest

from neurocoach.infra.db import Database

EXPECTED_TABLES = {
    "users",
    "preferences",
    "projects",
    "phases",
    "tasks",
    "task_dependencies",
    "pending_actions",
    "activity_events",
    "conversation_threads",
    "llm_config_events",  # M3 (D-64)
    # R1 du Business Researcher (D-68)
    "research_missions",
    "research_mission_projects",
    "research_queries",
    "research_sources",
    "research_findings",
    "research_finding_sources",
    "research_provider_usage",  # R2 (D-69)
    "research_analyses",  # R4 (D-71)
    "research_solutions",  # R6 (D-73)
}


@pytest.fixture
def db(tmp_path) -> Database:
    database = Database(tmp_path / "base.sqlite")
    database.migrate()
    return database


def test_empty_database_reaches_current_schema(db):
    assert db.schema_version() == 10
    conn = db.connect()
    try:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert tables >= EXPECTED_TABLES
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        conn.close()


def test_migrations_are_idempotent(db):
    assert db.migrate() == 10
    assert db.schema_version() == 10


def test_foreign_keys_are_enforced(db):
    with pytest.raises(sqlite3.IntegrityError), db.transaction(write=True) as conn:
        conn.execute(
            "INSERT INTO projects (id, user_id, title, status, next_task_number, version, "
            "created_at, updated_at) VALUES ('p', 'absent', 'Titre', 'draft', 1, 1, 'x', 'x')"
        )


def test_status_invariants_are_enforced_by_the_schema(db):
    with db.transaction(write=True) as conn:
        conn.execute("INSERT INTO users (id, display_name, created_at) VALUES ('u', 'U', 'x')")
        conn.execute(
            "INSERT INTO projects (id, user_id, title, status, next_task_number, version, "
            "created_at, updated_at) VALUES ('p', 'u', 'Titre', 'draft', 1, 1, 'x', 'x')"
        )
        conn.execute("INSERT INTO phases VALUES ('ph', 'p', 'Phase', NULL, 0)")
    with pytest.raises(sqlite3.IntegrityError), db.transaction(write=True) as conn:
        conn.execute(
            "INSERT INTO tasks (id, project_id, phase_id, number, title, acceptance_criteria, "
            "status, priority, position, completed_at, version, created_at, updated_at) "
            "VALUES ('t', 'p', 'ph', 1, 'Titre', 'Critère', 'done', 3, 0, NULL, 1, 'x', 'x')"
        )


def test_rollback_on_error_leaves_no_trace(db):
    with pytest.raises(RuntimeError), db.transaction(write=True) as conn:
        conn.execute("INSERT INTO users (id, display_name, created_at) VALUES ('u', 'U', 'x')")
        raise RuntimeError("panne simulée")
    with db.transaction(write=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


# --- D-76 : profils locaux, sans perte des donnees existantes -----------------------------


def _version_8_database(tmp_path) -> Database:
    """Base au schema 8 (avant la refonte), avec un espace de demonstration et un autre."""
    from importlib import resources

    from neurocoach.infra.db import MIGRATIONS_PACKAGE

    database = Database(tmp_path / "ancienne.sqlite")
    conn = database.connect()
    try:
        for script in sorted(
            (f for f in resources.files(MIGRATIONS_PACKAGE).iterdir() if f.name.endswith(".sql")),
            key=lambda f: f.name,
        ):
            number = int(script.name.split("_", 1)[0])
            if number > 8:
                break
            sql = script.read_text(encoding="utf-8")
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;")
        conn.executescript(
            "BEGIN;"
            "INSERT INTO users VALUES ('usr_0123456789abcdef', 'Alice (démo)', 'x');"
            "INSERT INTO users VALUES ('usr_fedcba9876543210', 'Camille', 'x');"
            "INSERT INTO projects (id, user_id, title, status, next_task_number, version, "
            "created_at, updated_at) VALUES ('p', 'usr_0123456789abcdef', 'Bougies', 'active', "
            "1, 3, 'x', 'x');"
            "COMMIT;"
        )
    finally:
        conn.close()
    return database


def test_profile_migration_keeps_existing_users_and_projects(tmp_path):
    database = _version_8_database(tmp_path)
    assert database.migrate() == 10
    with database.transaction(write=False) as conn:
        users = {
            row["id"]: (row["display_name"], row["username"], row["username_key"])
            for row in conn.execute("SELECT * FROM users")
        }
        project = conn.execute("SELECT * FROM projects").fetchone()
    assert users == {
        "usr_0123456789abcdef": ("Alice (démo)", "alice-demo", "alice-demo"),
        "usr_fedcba9876543210": ("Camille", "espace-fedcba98", "espace-fedcba98"),
    }
    assert (project["title"], project["version"], project["title_pending"]) == ("Bougies", 3, 0)
    # D-85 : la pause s'ajoute sans toucher aux projets existants (aucun n'est en pause).
    assert (project["paused_at"], project["pause_note"]) == (None, None)


def test_usernames_are_unique_regardless_of_case(db):
    with db.transaction(write=True) as conn:
        conn.execute(
            "INSERT INTO users (id, display_name, created_at, username, username_key) "
            "VALUES ('u1', 'A', 'x', 'Marie', 'marie')"
        )
    with pytest.raises(sqlite3.IntegrityError), db.transaction(write=True) as conn:
        conn.execute(
            "INSERT INTO users (id, display_name, created_at, username, username_key) "
            "VALUES ('u2', 'B', 'x', 'MARIE', 'marie')"
        )
