"""Etape M3 : configuration chargee, historique des modeles et diagnostic, hors ligne.

``build_llm_provider`` est remplace par un espion (aucun client reel) sauf mention contraire.
Les cles de test sont fabriquees a l'execution.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

import neurocoach.agent.llm as llm_module
from factories import ALICE, BRUNO
from neurocoach.agent.llm import FakeLLM
from neurocoach.bootstrap import build_coach_runtime
from neurocoach.config import Settings
from neurocoach.infra.db import Database
from neurocoach.infra.llm_history import (
    last_loaded,
    list_events,
    read_events,
    record_if_changed,
)
from neurocoach.llm_catalog import (
    RESTART_MESSAGE,
    load_catalog,
    loaded_config,
    loaded_lines,
    pending_changes,
)

ROOT = Path(__file__).resolve().parents[2]
CURRENT = {
    "NEUROCOACH_LLM_PROVIDER": "openai",
    "NEUROCOACH_LLM_MODEL": "gpt-5-mini",
    "NEUROCOACH_LLM_TIMEOUT_SECONDS": "30",
    "NEUROCOACH_LLM_MAX_OUTPUT_TOKENS": "4000",
}
MINI = ("openai", "gpt-5-mini", None)
TERRA = ("openai", "gpt-5.6-terra", None)
VAGUE = "Je veux vendre des bougies artisanales, mais je ne sais pas par où commencer."


def _key() -> str:
    return "sk-" + "TESTTRACABILITE" * 3


def _settings(data: Path, **extra: str) -> Settings:
    env = {**CURRENT, "NEUROCOACH_DATA_DIR": str(data), **extra}
    return Settings.from_env(env, dotenv_path=data / "absent")


class Spy:
    def __init__(self) -> None:
        self.requests: list[str] = []

    def __call__(self, settings, environ=None, *, dotenv_path=None):
        self.requests.append(settings.llm_model)
        return FakeLLM()


@pytest.fixture
def spy(monkeypatch):
    builder = Spy()
    monkeypatch.setattr(llm_module, "build_llm_provider", builder)
    return builder


def _start(settings: Settings):
    runtime = build_coach_runtime(settings)
    runtime.checkpointer.conn.close()
    return runtime


def _rows(settings: Settings) -> list[tuple]:
    return [(e.role, e.before, e.after) for e in list_events(Database(settings.business_db_path))]


# --- configuration chargee et configuration demandee ----------------------------------------


def test_the_loaded_configuration_is_exposed_by_the_runtime(tmp_path, spy):
    runtime = _start(_settings(tmp_path))
    assert runtime.llm_config.triples() == {"coaching": MINI, "strategy": MINI, "simple": MINI}
    assert loaded_lines(runtime.llm_config)[0] == (
        "coaching entrepreneurial : openai · gpt-5-mini · effort par défaut (chargé)"
    )


def test_an_injected_provider_has_no_loaded_configuration_and_no_history(tmp_path):
    settings = _settings(tmp_path)
    runtime = build_coach_runtime(settings, llm=FakeLLM())  # harnais, tests
    runtime.checkpointer.conn.close()
    assert runtime.llm_config is None
    assert _rows(settings) == []


def test_the_fingerprint_is_stable_and_only_follows_model_settings(tmp_path):
    base = loaded_config(_settings(tmp_path))
    assert loaded_config(_settings(tmp_path)).fingerprint == base.fingerprint
    unrelated = _settings(tmp_path, NEUROCOACH_PENDING_ACTION_TTL_MINUTES="30")
    assert loaded_config(unrelated).fingerprint == base.fingerprint
    for extra in (
        {"NEUROCOACH_LLM_MODEL_COACHING": "gpt-5.6-terra"},
        {"NEUROCOACH_LLM_EFFORT": "low"},
        {"NEUROCOACH_LLM_TIMEOUT_SECONDS": "60"},
    ):
        assert loaded_config(_settings(tmp_path, **extra)).fingerprint != base.fingerprint


def test_requested_and_loaded_configurations_are_compared_without_applying(tmp_path):
    loaded = loaded_config(_settings(tmp_path))
    assert pending_changes(loaded, _settings(tmp_path)) == []
    requested = _settings(
        tmp_path, NEUROCOACH_LLM_MODEL_COACHING="gpt-5.6-terra", NEUROCOACH_LLM_TIMEOUT_SECONDS="60"
    )
    assert pending_changes(loaded, requested) == [
        "coaching entrepreneurial : openai · gpt-5-mini · effort par défaut → "
        "openai · gpt-5.6-terra · effort par défaut",
        "paramètres communs modifiés (délai, plafond de sortie ou nouvelles tentatives)",
    ]
    assert loaded.triples()["coaching"] == MINI  # rien n'est applique


def test_a_catalog_update_is_reported_as_pending(tmp_path):
    body = (ROOT / "src" / "neurocoach" / "llm_models.toml").read_text(encoding="utf-8")
    path = tmp_path / "c.toml"
    path.write_text(body.replace('catalog_version = "2026-11-10"', 'catalog_version = "v2"'))
    loaded = loaded_config(_settings(tmp_path), load_catalog(path))
    assert pending_changes(loaded, _settings(tmp_path)) == [
        "catalogue des modèles mis à jour (v2 → 2026-11-10)"
    ]


def test_the_loaded_configuration_contains_no_secret(tmp_path):
    settings = Settings.from_env(
        {**CURRENT, "OPENAI_API_KEY": _key()}, dotenv_path=tmp_path / "absent"
    )
    loaded = loaded_config(settings)
    assert _key() not in repr(loaded) and "sk-" not in repr(loaded)


# --- interface : plus de substitution silencieuse ------------------------------------------


@pytest.fixture
def ui(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.chdir(tmp_path)  # le .env du depot ne doit pas s'appliquer
    monkeypatch.setenv("NEUROCOACH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NEUROCOACH_LLM_PROVIDER", "fake")
    test = AppTest.from_file(str(ROOT / "ui" / "app.py"), default_timeout=60)
    test.run()
    assert not test.exception, test.exception
    # D-76 : les modeles charges sont dans Parametres > Reglages avances, apres le profil.
    test.text_input(key="profile_first").input("Marie")
    test.text_input(key="profile_last").input("Dupont")
    test.text_input(key="profile_username").input("marie.d")
    test.button(key="create_space").click().run()
    test.button(key="nav_parametres").click().run()
    assert not test.exception, test.exception
    yield test
    import streamlit as st

    st.cache_resource.clear()


def _captions(at) -> list[str]:
    return [element.value for element in at.caption]


def test_the_ui_shows_the_loaded_models(ui):
    captions = _captions(ui)
    assert "coaching entrepreneurial : fake · (aucun) · effort par défaut (chargé)" in captions
    assert "Configuration demandée : identique à la configuration chargée." in captions
    assert not ui.warning


def test_a_configuration_change_is_announced_never_applied_silently(ui, monkeypatch):
    """Avant M3 : changer de fournisseur reconstruisait l'execution en silence."""
    monkeypatch.setenv("NEUROCOACH_LLM_PROVIDER", "openai")
    monkeypatch.setenv("NEUROCOACH_LLM_MODEL", "gpt-5.6-terra")
    ui.run()
    assert not ui.exception, ui.exception  # aucune construction de client reel
    warnings = [w.value for w in ui.warning]
    assert len(warnings) == 1 and warnings[0].startswith(RESTART_MESSAGE)
    assert "fake · (aucun) · effort par défaut → openai · gpt-5.6-terra" in warnings[0]
    # Le modele charge reste affiche comme tel : rien n'a change en memoire.
    assert "coaching entrepreneurial : fake · (aucun) · effort par défaut (chargé)" in _captions(ui)


def test_the_runtime_cache_key_no_longer_includes_the_provider():
    source = (ROOT / "ui" / "app.py").read_text(encoding="utf-8")
    assert "def get_runtime(data_dir: str) -> CoachRuntime:" in source
    assert "get_runtime(str(settings.data_dir.resolve()))" in source


# --- historique persistant, sans doublon ---------------------------------------------------


def test_the_first_start_records_one_line_per_role(tmp_path, spy):
    settings = _settings(tmp_path)
    _start(settings)
    assert _rows(settings) == [
        ("coaching", None, MINI),
        ("strategy", None, MINI),
        ("simple", None, MINI),
    ]


def test_restarting_with_the_same_configuration_adds_nothing(tmp_path, spy):
    settings = _settings(tmp_path)
    for _ in range(3):
        _start(settings)
    assert len(_rows(settings)) == 3


def test_a_switch_and_its_rollback_are_both_traced(tmp_path, spy):
    data = tmp_path / "data"
    _start(_settings(data))
    _start(_settings(data, NEUROCOACH_LLM_MODEL_COACHING="gpt-5.6-terra"))
    _start(_settings(data))  # retour arriere
    rows = _rows(_settings(data))
    assert rows[3:] == [("coaching", MINI, TERRA), ("coaching", TERRA, MINI)]
    assert last_loaded(list_events(Database(_settings(data).business_db_path)))["coaching"] == MINI


def test_a_failed_start_records_nothing(tmp_path, spy):
    settings = _settings(tmp_path)
    _start(settings)
    with pytest.raises(Exception, match="Modèle inconnu"):
        build_coach_runtime(_settings(tmp_path, NEUROCOACH_LLM_MODEL_COACHING="gpt-9"))
    assert len(_rows(settings)) == 3


def test_history_is_persistent_append_only_and_readable_read_only(tmp_path, spy):
    settings = _settings(tmp_path)
    _start(settings)
    events = read_events(settings.business_db_path)
    assert [e.role for e in events] == ["coaching", "strategy", "simple"]
    conn = sqlite3.connect(settings.business_db_path)
    try:
        for sql in (
            "UPDATE llm_config_events SET model_after = 'x'",
            "DELETE FROM llm_config_events",
        ):
            with pytest.raises(sqlite3.DatabaseError, match="ajout seul"):
                conn.execute(sql)
    finally:
        conn.close()
    assert read_events(tmp_path / "absent.sqlite") is None
    legacy = tmp_path / "ancienne.sqlite"
    sqlite3.connect(legacy).close()  # base sans l'historique (avant M3)
    assert read_events(legacy) is None


def test_record_if_changed_is_idempotent(tmp_path):
    database = Database(tmp_path / "b.sqlite")
    database.migrate()
    now = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
    current = {"coaching": MINI, "strategy": MINI, "simple": MINI}
    assert len(record_if_changed(database, current, catalog_version="v", fingerprint="f", now=now))
    assert record_if_changed(database, current, catalog_version="v", fingerprint="f", now=now) == []


# --- aucun secret, aucune donnee d'utilisateur -------------------------------------------------


def test_history_stores_no_secret_no_user_and_no_conversation(tmp_path, spy, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", _key())
    settings = _settings(tmp_path, NEUROCOACH_LLM_MODEL_STRATEGY="gpt-5.6-terra")
    runtime = build_coach_runtime(settings)
    try:
        runtime.app.coach.ensure_user(ALICE, "Alice")
        project = runtime.app.coach.create_project(ALICE, "Projet secret Zéphyr", "")
        runtime.agent.send_message(ALICE, project.id, "Message confidentiel Zéphyr")
    finally:
        runtime.checkpointer.conn.close()
    conn = sqlite3.connect(settings.business_db_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(llm_config_events)")}
        dump = " ".join(
            str(value) for row in conn.execute("SELECT * FROM llm_config_events") for value in row
        )
    finally:
        conn.close()
    assert not columns & {"user_id", "project_id", "thread_id", "content", "api_key"}
    for forbidden in (_key(), "sk-", ALICE, project.id, "Zéphyr"):
        assert forbidden not in dump


def test_history_survives_a_user_data_deletion_and_is_not_per_user(tmp_path, spy):
    settings = _settings(tmp_path)
    runtime = build_coach_runtime(settings)
    try:
        for user in (ALICE, BRUNO):
            runtime.app.coach.ensure_user(user, "Utilisateur de test")
        erase = runtime.app.actions.request_user_data_deletion(ALICE)
        runtime.app.actions.confirm(ALICE, erase.id)
        assert runtime.app.coach.list_projects(BRUNO) == []
    finally:
        runtime.checkpointer.conn.close()
    assert len(_rows(settings)) == 3  # trace systeme, distincte des donnees des utilisateurs


# --- check-llm : diagnostic par role, historique, ping plafonne -----------------------------


def _check_llm():
    spec = importlib.util.spec_from_file_location("check_llm", ROOT / "scripts" / "check_llm.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_llm"] = module
    spec.loader.exec_module(module)
    return module


def _env_file(tmp_path: Path, **extra: str) -> Path:
    path = tmp_path / ".env"
    values = {
        **CURRENT,
        "NEUROCOACH_DATA_DIR": str(tmp_path / "data"),
        "OPENAI_API_KEY": _key(),
        **extra,
    }
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    return path


def test_history_command_lists_changes_in_paris_time(tmp_path, spy, capsys):
    env_file = _env_file(tmp_path)
    database = Database(Settings.from_env({}, dotenv_path=env_file).business_db_path)
    database.migrate()
    record_if_changed(
        database,
        {"coaching": MINI},
        catalog_version="v",
        fingerprint="f",
        now=datetime(2026, 11, 10, 8, 0, tzinfo=UTC),
    )
    record_if_changed(
        database,
        {"coaching": TERRA},
        catalog_version="v",
        fingerprint="g",
        now=datetime(2026, 11, 12, 15, 30, tzinfo=UTC),
    )
    assert _check_llm().main(["--history"], env_file=env_file, root=tmp_path) == 0
    out = capsys.readouterr().out
    assert "10/11/2026 09:00 · coaching entrepreneurial : (première configuration) → " in out
    assert "12/11/2026 16:30 · coaching entrepreneurial : openai · gpt-5-mini" in out
    assert "→ openai · gpt-5.6-terra · effort par défaut" in out
    assert _key() not in out


def test_history_command_without_a_database(tmp_path, capsys):
    assert _check_llm().main(["--history"], env_file=_env_file(tmp_path), root=tmp_path) == 0
    assert "Aucun historique" in capsys.readouterr().out
    assert not (tmp_path / "data").exists()  # lecture seule : rien n'est cree


@pytest.mark.skipif(importlib.util.find_spec("langchain_openai") is None, reason="extra openai")
def test_check_flags_a_requested_configuration_not_loaded_yet(tmp_path, spy):
    _start(_settings(tmp_path / "data"))
    env_file = _env_file(tmp_path, NEUROCOACH_LLM_MODEL_COACHING="gpt-5.6-terra")
    _, warnings, errors, _ = _check_llm().check({}, dotenv_path=env_file, root=tmp_path)
    assert errors == []
    assert any(
        w.startswith("Configuration demandée différente de la dernière chargée")
        and "ne sera active qu'au prochain démarrage" in w
        for w in warnings
    )


@pytest.fixture
def no_real_ping(monkeypatch):
    """Le ping est remplace : il note la configuration visee, sans aucun appel."""
    module = _check_llm()
    targets: list[str] = []

    def fake_ping(settings, environ, dotenv_path):
        targets.append(settings.llm_model)
        return "ping simulé"

    monkeypatch.setattr(module, "ping", fake_ping)
    monkeypatch.setattr(module, "build_role_providers", lambda *a, **k: FakeLLM())
    monkeypatch.delenv("NEUROCOACH_LLM_PROVIDER")  # le fournisseur du .env de test s'applique
    return module, targets


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--ping"], "précisez --role et --budget-usd"),
        (["--ping", "--role", "coaching"], "précisez --role et --budget-usd"),
        (["--ping", "--role", "coaching", "--budget-usd", "0.01"], "pire cas du test 0.0490 $"),
    ],
)
def test_a_role_ping_needs_a_role_and_a_sufficient_budget(
    tmp_path, no_real_ping, capsys, argv, expected
):
    module, targets = no_real_ping
    env_file = _env_file(tmp_path, NEUROCOACH_LLM_MODEL_COACHING="gpt-5.6-terra")
    assert module.main(argv, env_file=env_file, root=tmp_path) == 1
    assert expected in capsys.readouterr().out
    assert targets == []  # aucun envoi


def test_a_role_ping_within_budget_targets_that_role_only(tmp_path, no_real_ping, capsys):
    module, targets = no_real_ping
    env_file = _env_file(tmp_path, NEUROCOACH_LLM_MODEL_COACHING="gpt-5.6-terra")
    argv = ["--ping", "--role", "coaching", "--budget-usd", "0.06"]
    assert module.main(argv, env_file=env_file, root=tmp_path) == 0
    assert targets == ["gpt-5.6-terra"]
    assert "pire cas 0.0490 $" in capsys.readouterr().out


def test_a_role_ping_refuses_an_uncatalogued_model(tmp_path, no_real_ping, capsys):
    module, targets = no_real_ping
    env_file = _env_file(
        tmp_path,
        NEUROCOACH_LLM_PROVIDER="anthropic",
        NEUROCOACH_LLM_MODEL="claude-opus-5-5",
        ANTHROPIC_API_KEY=_key(),
    )
    argv = ["--ping", "--role", "coaching", "--budget-usd", "1"]
    assert module.main(argv, env_file=env_file, root=tmp_path) == 1
    assert "Tarifs inconnus pour claude-opus-5-5" in capsys.readouterr().out
    assert targets == []


def test_role_requires_ping():
    with pytest.raises(SystemExit):
        _check_llm().main(["--role", "coaching"])


def test_the_kill_switch_blocks_check_llm_before_any_ping(tmp_path, monkeypatch, capsys):
    module = _check_llm()
    called = []
    monkeypatch.setattr(module, "ping", lambda *a: called.append(a))
    monkeypatch.delenv("NEUROCOACH_LLM_PROVIDER")
    env_file = _env_file(tmp_path, NEUROCOACH_LLM_MODEL_COACHING="gpt-5.6-terra")
    argv = ["--ping", "--role", "coaching", "--budget-usd", "0.06"]
    assert module.main(argv, env_file=env_file, root=tmp_path) == 1  # verrou pose (conftest)
    assert "NEUROCOACH_FORBID_REAL_LLM=1" in capsys.readouterr().out
    assert called == []
