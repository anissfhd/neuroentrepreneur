"""Configuration : valeurs par defaut, environnement, fichier .env."""

from __future__ import annotations

from pathlib import Path

import pytest

from neurocoach.config import ConfigurationError, Settings


def test_defaults_use_fake_llm_and_no_secret(tmp_path):
    settings = Settings.from_env({}, dotenv_path=tmp_path / "absent.env")
    assert settings.llm_provider == "fake"
    assert settings.pending_action_ttl_minutes == 15
    assert settings.default_timezone == "Europe/Paris"
    assert settings.business_db_path == Path("data") / "neurocoach.sqlite"
    assert settings.checkpoint_db_path == Path("data") / "checkpoints.sqlite"


def test_environment_overrides_dotenv(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "NEUROCOACH_PENDING_ACTION_TTL_MINUTES=5\nNEUROCOACH_DEFAULT_TIMEZONE=UTC\n",
        encoding="utf-8",
    )
    settings = Settings.from_env(
        {"NEUROCOACH_PENDING_ACTION_TTL_MINUTES": "20", "NEUROCOACH_LLM_MODEL": ""},
        dotenv_path=env_file,
    )
    assert settings.pending_action_ttl_minutes == 20
    assert settings.default_timezone == "UTC"
    assert settings.llm_model == ""


@pytest.mark.parametrize(
    "environ",
    [
        {"NEUROCOACH_LLM_PROVIDER": "inconnu"},
        {"NEUROCOACH_DEFAULT_TIMEZONE": "Nulle/Part"},
        {"NEUROCOACH_PENDING_ACTION_TTL_MINUTES": "0"},
    ],
)
def test_invalid_configuration_is_reported(environ, tmp_path):
    with pytest.raises(ConfigurationError):
        Settings.from_env(environ, dotenv_path=tmp_path / "absent.env")
