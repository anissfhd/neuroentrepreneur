"""Preparation des dialogues reels : la cle arrive au SDK, mais n'apparait nulle part.

Les cles ci-dessous sont fictives et construites a l'execution (aucune valeur dans le
source, que l'analyse des secrets signalerait).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from pydantic import SecretStr

from neurocoach.agent.llm import build_llm_provider
from neurocoach.config import Settings, read_provider_key
from neurocoach.domain.errors import DomainError, ErrorCode

ROOT = Path(__file__).resolve().parents[2]
FAKE_KEY = "sk-ant-" + "CLEFICTIVEDETEST" * 3
HAS_ANTHROPIC = importlib.util.find_spec("langchain_anthropic") is not None


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # requis par les dataclasses du script
    spec.loader.exec_module(module)
    return module


def _env_file(tmp_path: Path, **extra: str) -> Path:
    values = {
        "NEUROCOACH_LLM_PROVIDER": "anthropic",
        "NEUROCOACH_LLM_MODEL": "claude-opus-5-5",
        "ANTHROPIC_API_KEY": FAKE_KEY,
        **extra,
    }
    path = tmp_path / ".env"
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    return path


def test_key_is_read_from_dotenv_masked_and_never_stored_in_settings(tmp_path):
    """Defaut trouve avant les dialogues : dotenv_values n'exporte pas la cle vers le SDK."""
    env_file = _env_file(tmp_path)
    key = read_provider_key("anthropic", {}, dotenv_path=env_file)
    assert isinstance(key, SecretStr)
    assert key.get_secret_value() == FAKE_KEY
    assert FAKE_KEY not in repr(key) and FAKE_KEY not in str(key)
    settings = Settings.from_env({}, dotenv_path=env_file)
    assert FAKE_KEY not in repr(settings) and FAKE_KEY not in str(settings.model_dump())
    # L'environnement reste prioritaire ; une valeur vide ne compte pas.
    other = "sk-ant-" + "AUTRECLEFICTIVE" * 3
    assert read_provider_key("anthropic", {"ANTHROPIC_API_KEY": other}, dotenv_path=env_file)
    assert read_provider_key("anthropic", {"ANTHROPIC_API_KEY": ""}, dotenv_path=env_file)
    assert read_provider_key("anthropic", {}, dotenv_path=tmp_path / "absent") is None
    assert read_provider_key("fake", {}, dotenv_path=env_file) is None


@pytest.mark.skipif(not HAS_ANTHROPIC, reason="extra anthropic absent")
def test_provider_receives_the_key_and_effort_without_exposing_them(tmp_path, monkeypatch):
    # Construction seule, sans appel. Depuis M2, le verrou du processus n'est plus masque par
    # un environnement explicite : il faut le lever pour ce test.
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_LLM")
    env_file = _env_file(tmp_path, NEUROCOACH_LLM_EFFORT="low")
    settings = Settings.from_env({}, dotenv_path=env_file)
    provider = build_llm_provider(settings, {}, dotenv_path=env_file)
    model = provider.model
    assert model.anthropic_api_key.get_secret_value() == FAKE_KEY
    assert model.reasoning_effort == "low"
    assert model.max_tokens == 4000
    assert FAKE_KEY not in repr(model) and FAKE_KEY not in str(model.model_dump())


@pytest.mark.skipif(not HAS_ANTHROPIC, reason="extra anthropic absent")
def test_configuration_check_reports_the_key_as_defined_only(tmp_path):
    check_llm = _script("check_llm")
    env_file = _env_file(tmp_path)
    infos, warnings, errors, settings = check_llm.check({}, dotenv_path=env_file, root=tmp_path)
    text = "\n".join(infos + warnings + errors)
    assert errors == []
    assert "ANTHROPIC_API_KEY : définie (valeur masquée)" in infos
    assert FAKE_KEY not in text and FAKE_KEY[-12:] not in text
    assert settings.llm_model == "claude-opus-5-5"


def test_configuration_check_flags_missing_key_tracing_logs_and_low_ceiling(tmp_path):
    check_llm = _script("check_llm")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "NEUROCOACH_LLM_PROVIDER=anthropic\nNEUROCOACH_LLM_MAX_OUTPUT_TOKENS=1200\n",
        encoding="utf-8",
    )
    environ = {"LANGSMITH_TRACING": "true", "ANTHROPIC_LOG": "debug"}
    _, warnings, errors, _ = check_llm.check(environ, dotenv_path=env_file, root=tmp_path)
    assert any("ANTHROPIC_API_KEY absente" in e for e in errors)
    assert any("NEUROCOACH_LLM_MODEL est vide" in e for e in errors)
    assert any("LangSmith" in w for w in warnings)
    assert any("ANTHROPIC_LOG" in w for w in warnings)
    assert any("Plafond de sortie bas" in w for w in warnings)


def test_fake_provider_needs_nothing(tmp_path):
    check_llm = _script("check_llm")
    _, warnings, errors, settings = check_llm.check({}, dotenv_path=tmp_path / "absent")
    assert (warnings, errors, settings.llm_provider) == ([], [], "fake")


class _Refused(Exception):
    status_code = 401


def _failing_call():
    try:
        raise _Refused("invalid x-api-key " + FAKE_KEY)  # message jamais repris
    except _Refused as exc:
        raise DomainError(ErrorCode.LLM_UNAVAILABLE) from exc


def test_ping_failure_shows_only_the_error_type_and_status():
    check_llm = _script("check_llm")
    try:
        _failing_call()
    except DomainError as error:
        described = check_llm.describe_cause(error)
    assert described == "_Refused, HTTP 401"


def test_evaluation_report_records_provider_errors_without_their_message():
    evaluate = _script("evaluate_llm")

    class Inner:
        def generate_text(self, task, messages):
            _failing_call()

    recorder = evaluate.RecordingProvider(Inner())
    with pytest.raises(DomainError):
        recorder.generate_text("respond", [])
    text = "\n".join(evaluate.provider_section(recorder))
    assert "respond : LLM_UNAVAILABLE (_Refused, HTTP 401) (1 fois)" in text
    assert FAKE_KEY not in text and "invalid x-api-key" not in text
