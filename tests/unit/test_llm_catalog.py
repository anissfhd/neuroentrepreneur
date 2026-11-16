"""Etape M1 : catalogue des modeles, configuration par role et validation, hors ligne.

Aucun client n'est construit sauf mention contraire (construction seule, sans reseau), et
aucun appel n'est fait. Les cles de test sont fabriquees a l'execution, jamais ecrites ici.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

from neurocoach.config import ConfigurationError, Settings
from neurocoach.llm_catalog import (
    CATALOG_PATH,
    ROLES,
    Catalog,
    load_catalog,
    raise_on_errors,
    resolve_roles,
    unknown_llm_variables,
    validate_roles,
)

ROOT = Path(__file__).resolve().parents[2]
TODAY = date(2026, 11, 10)
HAS_OPENAI = importlib.util.find_spec("langchain_openai") is not None
# Configuration actuelle du porteur du projet (noms et valeurs non secrets de .env).
CURRENT_ENV = {
    "NEUROCOACH_LLM_PROVIDER": "openai",
    "NEUROCOACH_LLM_MODEL": "gpt-5-mini",
    "NEUROCOACH_LLM_TIMEOUT_SECONDS": "30",
    "NEUROCOACH_LLM_MAX_OUTPUT_TOKENS": "4000",
    "NEUROCOACH_LLM_EFFORT": "",
    "NEUROCOACH_DEFAULT_TIMEZONE": "Europe/Paris",
}
LEGACY_FIELDS = {
    "llm_provider": "openai",
    "llm_model": "gpt-5-mini",
    "llm_timeout_seconds": 30.0,
    "llm_max_output_tokens": 4000,
    "llm_effort": None,
    "llm_max_retries": 1,
    "default_timezone": "Europe/Paris",
}


def _settings(tmp_path: Path, **extra: str) -> Settings:
    return Settings.from_env({**CURRENT_ENV, **extra}, dotenv_path=tmp_path / "absent")


def _messages(issues, severity=None):
    return [i.message for i in issues if severity is None or i.severity == severity]


def _catalog(tmp_path: Path, body: str) -> Catalog:
    path = tmp_path / "models.toml"
    path.write_text(body, encoding="utf-8")
    return load_catalog(path)


ENTRY = """
[[models]]
id = "{id}"
provider = "openai"
status = "{status}"
{extra}
verified_on = {verified}
sources = ["https://example.org/officiel"]
"""


def _entry(id="m", status="available", extra="", verified="2026-11-10"):
    return ENTRY.format(id=id, status=status, extra=extra, verified=verified)


# --- catalogue -----------------------------------------------------------------------------


def test_the_shipped_catalog_is_valid_and_matches_the_official_checks():
    catalog = load_catalog()
    assert catalog.ids() == ["gpt-5-mini", "gpt-5.6-terra", "gpt-5.6-luna"]
    mini = catalog.get("gpt-5-mini")
    assert mini.status == "deprecated"
    assert mini.retirement_date == date(2026, 12, 11)
    assert mini.replacement == "gpt-5.6-terra"
    assert catalog.get("gpt-5-mini-2025-08-07") is mini  # instantane date
    assert (mini.price_input, mini.price_cached_input, mini.price_output) == (0.25, 0.025, 2.0)
    # Niveaux d'effort absents de la page officielle : non verifies, jamais bloquants.
    assert not mini.confirmed("efforts") and mini.efforts == () and "low" in mini.observed_efforts
    for name in ("gpt-5.6-terra", "gpt-5.6-luna"):
        spec = catalog.get(name)
        assert spec.status == "available" and spec.retirement_date is None
        assert spec.efforts == ("none", "low", "medium", "high", "xhigh", "max")
        assert spec.confirmed("efforts") and spec.default_effort == "medium"
    assert catalog.get("gpt-5.6-terra").price_output == 12.0
    assert catalog.get("gpt-5.6-luna").price_output == 1.2
    for spec in catalog.models:
        assert spec.verified_on == TODAY
        assert all(url.startswith("https://developers.openai.com/") for url in spec.sources)


def test_the_catalog_is_packaged():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"llm_models.toml"' in text
    assert CATALOG_PATH.is_file()


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('catalog_version = "x"\n' + _entry() + _entry(), "en double"),
        ('catalog_version = "x"\n' + _entry(extra='replacement = "absent"'), "remplacement"),
        ('catalog_version = "x"\n' + _entry(status="retired"), "date de retrait"),
        (
            'catalog_version = "x"\n' + _entry(extra='unverified = ["couleur"]'),
            "unverified",
        ),
        ('catalog_version = "x"\n' + _entry(extra="price_output = -1"), "price_output"),
        ('catalog_version = "x"\n' + _entry(extra='mystere = "?"'), "mystere"),
        ('catalog_version = "x"\n' + _entry().replace("https://", "http://"), "https"),
        ('catalog_version = "x"\n[[models]]\nid = ', "illisible"),
        ('catalog_version = "x"\n', "models"),
    ],
)
def test_an_invalid_catalog_is_refused_with_a_clear_message(tmp_path, body, message):
    with pytest.raises(ConfigurationError) as error:
        _catalog(tmp_path, body)
    assert message in str(error.value)
    assert str(error.value).startswith("Catalogue des modèles")


def test_a_missing_catalog_is_reported(tmp_path):
    with pytest.raises(ConfigurationError, match="introuvable"):
        load_catalog(tmp_path / "absent.toml")


# --- compatibilite avec la configuration existante -----------------------------------------


def test_current_configuration_is_read_exactly_as_before(tmp_path):
    settings = _settings(tmp_path)
    assert {name: getattr(settings, name) for name in LEGACY_FIELDS} == LEGACY_FIELDS


def test_without_role_variables_every_role_inherits_gpt_5_mini(tmp_path):
    roles = resolve_roles(_settings(tmp_path))
    assert list(roles) == list(ROLES)
    for assignment in roles.values():
        assert (assignment.provider, assignment.model, assignment.effort) == (
            "openai",
            "gpt-5-mini",
            None,
        )
        assert assignment.inherited == {"provider", "model", "effort"}
        assert assignment.describe().count("(hérité)") == 3


def test_current_configuration_has_no_error_only_the_retirement_notice(tmp_path):
    issues = validate_roles(_settings(tmp_path), today=TODAY)
    assert _messages(issues, "erreur") == []
    warnings = _messages(issues, "avertissement")
    assert len(warnings) == 1  # un seul message pour les trois roles
    assert "gpt-5-mini" in warnings[0] and "11/12/2026" in warnings[0]
    assert "dans 31 jours" in warnings[0] and "Aucune bascule automatique" in warnings[0]
    raise_on_errors(issues)  # ne leve rien


def test_role_variables_override_only_what_they_set(tmp_path):
    settings = _settings(
        tmp_path,
        NEUROCOACH_LLM_EFFORT="low",
        NEUROCOACH_LLM_MODEL_STRATEGY="gpt-5.6-terra",
        NEUROCOACH_LLM_EFFORT_SIMPLE="medium",
        NEUROCOACH_LLM_MODEL_SIMPLE="gpt-5.6-luna",
    )
    roles = resolve_roles(settings)
    assert (roles["coaching"].model, roles["coaching"].effort) == ("gpt-5-mini", "low")
    assert (roles["strategy"].model, roles["strategy"].effort) == ("gpt-5.6-terra", "low")
    assert roles["strategy"].inherited == {"provider", "effort"}
    assert (roles["simple"].model, roles["simple"].effort) == ("gpt-5.6-luna", "medium")
    assert _messages(validate_roles(settings, today=TODAY), "erreur") == []


@pytest.mark.skipif(not HAS_OPENAI, reason="extra openai absent")
def test_the_application_still_uses_gpt_5_mini_whatever_the_role_variables(tmp_path, monkeypatch):
    """M1 : aucune variable de role n'est utilisee par l'application (routage = M2)."""
    from neurocoach.agent.llm import build_llm_provider

    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_LLM")  # construction seule, aucun appel
    settings = _settings(
        tmp_path,
        NEUROCOACH_LLM_MODEL_COACHING="gpt-5.6-terra",
        NEUROCOACH_LLM_PROVIDER_COACHING="openai",
        NEUROCOACH_LLM_EFFORT_COACHING="high",
    )
    key = "sk-" + "TESTCATALOGUE" * 4
    provider = build_llm_provider(settings, {"OPENAI_API_KEY": key}, dotenv_path=tmp_path / "x")
    assert provider.model.model_name == "gpt-5-mini"
    assert provider.model.reasoning_effort is None
    assert provider.model.max_tokens == 4000


# --- configurations invalides ---------------------------------------------------------------


def test_an_unknown_role_model_is_an_error_listing_the_declared_models(tmp_path):
    settings = _settings(tmp_path, NEUROCOACH_LLM_MODEL_COACHING="gpt-5-minii")
    errors = _messages(validate_roles(settings, today=TODAY), "erreur")
    assert errors == [
        "Modèle inconnu pour le rôle coaching entrepreneurial : gpt-5-minii. Modèles déclarés : "
        "gpt-5-mini, gpt-5.6-terra, gpt-5.6-luna (src/neurocoach/llm_models.toml)."
    ]
    with pytest.raises(ConfigurationError, match="gpt-5-minii"):
        raise_on_errors(validate_roles(settings, today=TODAY))


def test_an_unknown_legacy_model_is_never_blocked(tmp_path):
    """Compatibilite stricte : une configuration existante hors catalogue fonctionne comme avant."""
    settings = _settings(
        tmp_path, NEUROCOACH_LLM_PROVIDER="anthropic", NEUROCOACH_LLM_MODEL="claude-opus-5-5"
    )
    issues = validate_roles(settings, today=TODAY)
    assert _messages(issues, "erreur") == []
    assert any("Modèle inconnu" in m for m in _messages(issues, "avertissement"))


def test_a_provider_mismatch_is_explained(tmp_path):
    settings = _settings(
        tmp_path,
        NEUROCOACH_LLM_PROVIDER_STRATEGY="anthropic",
        NEUROCOACH_LLM_MODEL_STRATEGY="gpt-5.6-terra",
    )
    errors = _messages(validate_roles(settings, today=TODAY), "erreur")
    assert errors == [
        "gpt-5.6-terra est un modèle openai, mais le rôle stratégie et recherche business est "
        "configuré pour anthropic."
    ]


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("NEUROCOACH_LLM_PROVIDER_COACHING", "mistral"),
        ("NEUROCOACH_LLM_EFFORT_SIMPLE", "max"),
    ],
)
def test_invalid_role_values_are_refused_at_reading(tmp_path, name, value):
    with pytest.raises(ConfigurationError, match="Configuration invalide"):
        _settings(tmp_path, **{name: value})


def test_an_effort_refused_by_a_confirmed_catalog_is_an_error(tmp_path):
    catalog = _catalog(
        tmp_path, 'catalog_version = "x"\n' + _entry(id="gpt-5-mini", extra='efforts = ["none"]')
    )
    settings = _settings(tmp_path, NEUROCOACH_LLM_EFFORT_COACHING="high")
    errors = _messages(validate_roles(settings, catalog, today=TODAY), "erreur")
    assert errors == ["L'effort « high » n'est pas accepté par gpt-5-mini (accepté : none)."]


def test_an_unverified_effort_never_blocks_the_active_model(tmp_path):
    settings = _settings(tmp_path, NEUROCOACH_LLM_EFFORT_COACHING="high")
    issues = validate_roles(settings, today=TODAY)
    assert _messages(issues, "erreur") == []
    assert any("non confirmé" in m for m in _messages(issues, "avertissement"))
    observed = _settings(tmp_path, NEUROCOACH_LLM_EFFORT="low")  # utilise en campagne reelle
    assert not any("non confirmé" in m for m in _messages(validate_roles(observed, today=TODAY)))


def test_a_retired_model_blocks_a_role_but_not_the_legacy_setting(tmp_path):
    body = 'catalog_version = "x"\n' + _entry(
        id="vieux", status="retired", extra="retirement_date = 2026-01-01"
    )
    catalog = _catalog(tmp_path, body)
    role = _settings(tmp_path, NEUROCOACH_LLM_MODEL_COACHING="vieux")
    assert any(
        "vieux est retiré depuis le 01/01/2026" in m
        for m in _messages(validate_roles(role, catalog, today=TODAY), "erreur")
    )
    legacy = _settings(tmp_path, NEUROCOACH_LLM_MODEL="vieux")
    assert _messages(validate_roles(legacy, catalog, today=TODAY), "erreur") == []


def test_past_retirement_date_and_stale_entry_only_warn(tmp_path):
    body = 'catalog_version = "x"\n' + _entry(
        id="gpt-5-mini", extra="retirement_date = 2026-11-01", verified="2026-01-01"
    )
    issues = validate_roles(_settings(tmp_path), _catalog(tmp_path, body), today=TODAY)
    assert _messages(issues, "erreur") == []
    warnings = _messages(issues, "avertissement")
    assert any("Date de retrait de gpt-5-mini dépassée" in m for m in warnings)
    assert any("vérifiée il y a 313 jours" in m for m in warnings)


def test_no_silent_switch_is_ever_proposed(tmp_path):
    """La validation signale ; elle ne remplace jamais un modele par un autre."""
    settings = _settings(tmp_path)
    before = resolve_roles(settings)
    validate_roles(settings, today=date(2026, 12, 20))  # apres le retrait
    assert resolve_roles(settings) == before
    assert all(a.model == "gpt-5-mini" for a in before.values())


def test_fake_provider_needs_no_catalog(tmp_path):
    fake = Settings.from_env({}, dotenv_path=tmp_path / "absent")
    assert validate_roles(fake, today=TODAY) == []
    tuned = Settings.from_env(
        {"NEUROCOACH_LLM_MODEL_COACHING": "gpt-5.6-terra"}, dotenv_path=tmp_path / "absent"
    )
    assert _messages(validate_roles(tuned, today=TODAY)) == [
        "Rôle coaching entrepreneurial : modèle ou effort ignorés avec le faux fournisseur."
    ]


def test_typos_in_llm_variables_are_reported_but_never_blocking():
    names = {
        "NEUROCOACH_LLM_MODEL",
        "NEUROCOACH_LLM_MODEL_COACHNG",
        "NEUROCOACH_LLM_EFFORT_STRATEGY",
        "NEUROCOACH_RUN_REAL_LLM",
        "OPENAI_API_KEY",
    }
    assert unknown_llm_variables(names) == ["NEUROCOACH_LLM_MODEL_COACHNG"]


# --- check-llm (hors ligne) ------------------------------------------------------------------


def _check_llm():
    spec = importlib.util.spec_from_file_location("check_llm", ROOT / "scripts" / "check_llm.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_llm"] = module
    spec.loader.exec_module(module)
    return module


def _env_file(tmp_path: Path, **extra: str) -> Path:
    path = tmp_path / ".env"
    values = {**CURRENT_ENV, "OPENAI_API_KEY": "sk-" + "TESTCATALOGUE" * 4, **extra}
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    return path


@pytest.mark.skipif(not HAS_OPENAI, reason="extra openai absent")
def test_check_llm_shows_roles_and_the_retirement_notice(tmp_path):
    check_llm = _check_llm()
    infos, warnings, errors, _ = check_llm.check({}, dotenv_path=_env_file(tmp_path), root=tmp_path)
    assert errors == []
    assert any(line.startswith("Rôle coaching entrepreneurial : openai (hérité)") for line in infos)
    assert "Routage par rôle : configuration commune pour tous les rôles." in infos
    assert any("sera retiré le 11/12/2026" in w for w in warnings)
    assert not any("TESTCATALOGUE" in line for line in infos + warnings + errors)


@pytest.mark.skipif(not HAS_OPENAI, reason="extra openai absent")
def test_check_llm_blocks_an_invalid_role_and_reports_typos(tmp_path):
    check_llm = _check_llm()
    env_file = _env_file(tmp_path, NEUROCOACH_LLM_MODEL_STRATEGY="gpt-9", NEUROCOACH_LLM_MODL="x")
    _, warnings, errors, _ = check_llm.check({}, dotenv_path=env_file, root=tmp_path)
    assert any("Modèle inconnu pour le rôle stratégie" in e for e in errors)
    assert any("NEUROCOACH_LLM_MODL" in w for w in warnings)


# --- protections contre les appels reels -----------------------------------------------------


def test_dry_run_neutralises_role_providers_from_dotenv(tmp_path, monkeypatch):
    """Une variable de role ne peut pas reintroduire un fournisseur reel dans un essai a blanc."""
    spec = importlib.util.spec_from_file_location(
        "evaluate_llm", ROOT / "scripts" / "evaluate_llm.py"
    )
    evaluate = importlib.util.module_from_spec(spec)
    sys.modules["evaluate_llm"] = evaluate
    spec.loader.exec_module(evaluate)
    (tmp_path / ".env").write_text(
        "NEUROCOACH_LLM_PROVIDER=openai\nNEUROCOACH_LLM_MODEL=gpt-5-mini\n"
        "NEUROCOACH_LLM_PROVIDER_COACHING=openai\nNEUROCOACH_LLM_MODEL_COACHING=gpt-5.6-terra\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NEUROCOACH_LLM_PROVIDER")
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_LLM")
    parser = evaluate.argparse.ArgumentParser()
    evaluate.add_safety_arguments(parser)
    settings = evaluate.select_settings(parser.parse_args([]), parser, Settings.from_env())
    assert {a.provider for a in resolve_roles(settings).values()} == {"fake"}
    assert {a.model for a in resolve_roles(settings).values()} == {""}


def test_catalog_and_validation_never_build_a_client(tmp_path, monkeypatch):
    import neurocoach.agent.llm as llm

    def forbidden(*args, **kwargs):
        raise AssertionError("aucun client ne doit etre construit")

    monkeypatch.setattr(llm, "build_llm_provider", forbidden)
    settings = _settings(tmp_path, NEUROCOACH_LLM_MODEL_COACHING="gpt-5.6-terra")
    validate_roles(settings, today=TODAY)
    resolve_roles(settings)
    load_catalog()


def test_the_kill_switch_stops_a_real_role_before_any_client(tmp_path):
    """M2 : un role reel explicite est utilise, mais le verrou des tests reste prioritaire."""
    from neurocoach.bootstrap import build_coach_runtime

    settings = Settings.from_env(
        {
            "NEUROCOACH_DATA_DIR": str(tmp_path / "data"),
            "NEUROCOACH_LLM_PROVIDER_COACHING": "openai",
            "NEUROCOACH_LLM_MODEL_COACHING": "gpt-5.6-terra",
        },
        dotenv_path=tmp_path / "absent",
    )
    with pytest.raises(ConfigurationError, match="Rôle coaching entrepreneurial : Appels réels"):
        build_coach_runtime(settings)
