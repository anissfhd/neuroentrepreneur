"""Controle de la configuration du fournisseur LLM reel, sans jamais afficher de cle.

Usage :
  python scripts/check_llm.py          controles locaux par role, aucun appel reseau
  python scripts/check_llm.py --history
                                       historique des modeles charges (lecture seule)
  python scripts/check_llm.py --ping   + un seul petit appel reel (payant, quelques jetons)
                                       avec sortie structuree, comme l'application
  python scripts/check_llm.py --ping --role coaching --budget-usd 0.06
                                       idem pour un role ; refuse si le pire cas, calcule avec
                                       les tarifs du catalogue, depasse le budget

Codes de sortie : 0 pret, 1 probleme bloquant, 2 faux fournisseur (rien a verifier).
La cle n'est jamais affichee, ni sa longueur, ni un extrait : seulement « definie » ou
« absente ». Le resultat du --ping ne reprend que le code d'erreur de l'application.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import dotenv_values
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from langchain_core.callbacks import get_usage_metadata_callback  # noqa: E402

from neurocoach.agent.llm import (  # noqa: E402
    build_llm_provider,
    build_role_providers,
    format_usage,
    summarize_usage,
)
from neurocoach.config import (  # noqa: E402
    PROVIDER_KEYS,
    ConfigurationError,
    Settings,
    read_provider_key,
)
from neurocoach.domain.errors import DomainError  # noqa: E402
from neurocoach.infra.llm_history import last_loaded, read_events  # noqa: E402
from neurocoach.llm_catalog import (  # noqa: E402
    ROLE_LABELS,
    ROLES,
    default_catalog,
    describe_triple,
    loaded_config,
    resolve_roles,
    summary,
    unknown_llm_variables,
    validate_roles,
)

EXTRAS = {"anthropic": "langchain_anthropic", "openai": "langchain_openai"}
TRACING = ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING")
SDK_LOGS = ("ANTHROPIC_LOG", "OPENAI_LOG")
MIN_TOKENS_WITH_THINKING = 2000


class PingResult(BaseModel):
    ok: bool


def _flag_on(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def check(
    environ: Mapping[str, str] | None = None,
    *,
    dotenv_path: Path | None = None,
    root: Path = ROOT,
) -> tuple[list[str], list[str], list[str], Settings | None]:
    """Retourne (informations, avertissements, erreurs bloquantes, configuration)."""
    env = os.environ if environ is None else environ
    env_file = dotenv_path if dotenv_path is not None else root / ".env"
    infos: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []

    infos.append(f"Fichier .env : {'présent' if env_file.is_file() else 'absent'}")
    git = shutil.which("git")
    if env_file.is_file() and git and (root / ".git").exists():
        ignored = subprocess.run(
            [git, "check-ignore", "-q", str(env_file)], cwd=root, check=False
        ).returncode
        if ignored != 0:
            errors.append(".env n'est pas ignoré par Git : ne rien commiter avant correction.")
        else:
            infos.append(".env ignoré par Git : oui")

    try:
        settings = Settings.from_env(environ, dotenv_path=env_file)
    except ConfigurationError as exc:
        errors.append(str(exc))
        return infos, warnings, errors, None

    provider = settings.llm_provider
    infos.append(f"Fournisseur : {provider}")
    _roles_section(settings, env, env_file, infos, warnings, errors)
    if provider == "fake":
        return infos, warnings, errors, settings

    infos.append(f"Modèle : {settings.llm_model or '(non défini)'}")
    infos.append(
        f"Délai : {settings.llm_timeout_seconds:g} s ; plafond de sortie : "
        f"{settings.llm_max_output_tokens} jetons ; effort : {settings.llm_effort or 'par défaut'}"
    )
    if not settings.llm_model:
        errors.append("NEUROCOACH_LLM_MODEL est vide.")
    key_name = PROVIDER_KEYS[provider]
    key = read_provider_key(provider, environ, dotenv_path=env_file)
    infos.append(f"{key_name} : {'définie' if key is not None else 'absente'} (valeur masquée)")
    if key is None:
        errors.append(f"{key_name} absente : la renseigner dans .env.")
    if importlib.util.find_spec(EXTRAS[provider]) is None:
        errors.append(f'Extra manquant : pip install -e ".[{provider}]"')
    if settings.llm_max_output_tokens < MIN_TOKENS_WITH_THINKING:
        warnings.append(
            "Plafond de sortie bas : pour les modèles qui raisonnent (Claude récents, gpt-5), "
            "la réflexion compte dans ce plafond et peut tronquer la réponse structurée."
        )
    for name in TRACING:
        if _flag_on(env.get(name)):
            warnings.append(
                f"{name} est actif : les messages seraient envoyés à LangSmith. Le désactiver."
            )
    for name in SDK_LOGS:
        if env.get(name, "").strip().lower() in {"debug", "info"}:
            warnings.append(f"{name} est actif : le SDK écrirait les requêtes dans le journal.")
    return infos, warnings, errors, settings


def _roles_section(
    settings: Settings,
    env: Mapping[str, str],
    env_file: Path,
    infos: list[str],
    warnings: list[str],
    errors: list[str],
) -> None:
    """M1 : configuration effective par role et validation par le catalogue (hors ligne).

    Rien n'est affiche quand tout est herite du faux fournisseur, comme avant M1."""
    roles = resolve_roles(settings)
    customized = any(len(a.inherited) < 3 for a in roles.values())
    if settings.llm_provider != "fake" or customized:
        infos.extend(f"Rôle {line}" for line in summary(settings, roles))
        infos.append(
            "Routage par rôle : actif (variables de rôle définies)."
            if customized
            else "Routage par rôle : configuration commune pour tous les rôles."
        )
    today = datetime.now(ZoneInfo(settings.default_timezone)).date()
    for issue in validate_roles(settings, today=today):
        (errors if issue.severity == "erreur" else warnings).append(issue.message)
    names = set(env) | (set(dotenv_values(env_file)) if env_file.is_file() else set())
    for name in unknown_llm_variables(names):
        warnings.append(f"Variable inconnue, ignorée : {name} (faute de frappe ?).")
    if settings.llm_provider != "fake" or customized:
        infos.extend(_catalog_lines(settings))
    loaded = _last_loaded_by_app(settings)
    if loaded:
        wanted = loaded_config(settings).triples()
        differing = [role for role in ROLES if loaded.get(role) != wanted[role]]
        if differing:
            warnings.append(
                "Configuration demandée différente de la dernière chargée par l'application ("
                + ", ".join(
                    f"{ROLE_LABELS[r]} : {describe_triple(*loaded[r]) if r in loaded else '—'}"
                    f" → {describe_triple(*wanted[r])}"
                    for r in differing
                )
                + ") : elle ne sera active qu'au prochain démarrage."
            )
        else:
            infos.append("Dernière configuration chargée par l'application : identique.")


def _catalog_lines(settings: Settings) -> list[str]:
    """Fiche du catalogue de chaque modele utilise (une ligne par modele)."""
    catalog = default_catalog()
    lines = []
    for model in dict.fromkeys(a.model for a in resolve_roles(settings).values() if a.model):
        spec = catalog.get(model)
        if spec is None:
            lines.append(f"Catalogue : {model} absent (configuration historique, non bloquante).")
            continue
        status = {"available": "disponible", "deprecated": "déprécié", "retired": "retiré"}
        retirement = f", retrait le {spec.retirement_date:%d/%m/%Y}" if spec.retirement_date else ""
        prices = (
            f"{_fr(spec.price_input)} $ / {_fr(spec.price_output)} $ par million (entrée / sortie)"
            if spec.price_input is not None and spec.price_output is not None
            else "tarifs inconnus"
        )
        unverified = f" ; non vérifié : {', '.join(spec.unverified)}" if spec.unverified else ""
        lines.append(
            f"Catalogue {spec.id} : {status[spec.status]}{retirement} ; {prices} ; vérifié le "
            f"{spec.verified_on:%d/%m/%Y}{unverified}."
        )
    return lines


def _fr(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def _last_loaded_by_app(settings: Settings) -> dict | None:
    events = read_events(settings.business_db_path)
    return last_loaded(events) if events else None


def history_lines(settings: Settings) -> list[str]:
    """Historique lisible, heures dans le fuseau configure. Aucun secret n'y est stocke."""
    events = read_events(settings.business_db_path)
    if not events:
        return ["Aucun historique : l'application n'a pas encore démarré avec cette base."]
    zone = ZoneInfo(settings.default_timezone)
    lines = []
    for event in events:
        when = datetime.fromisoformat(event.recorded_at).astimezone(zone)
        before = describe_triple(*event.before) if event.before else "(première configuration)"
        lines.append(
            f"{when:%d/%m/%Y %H:%M} · {ROLE_LABELS[event.role]} : {before} → "
            f"{describe_triple(*event.after)}"
        )
    return lines


PING_INPUT_TOKENS = 500  # majoration large du petit message de test


def ping_worst_case(settings: Settings, role: str) -> tuple[Settings, float]:
    """Configuration du role et pire cas du --ping, avec les tarifs CONFIRMES du catalogue."""
    assignment = resolve_roles(settings)[role]
    spec = default_catalog().get(assignment.model)
    if spec is None or spec.price_input is None or spec.price_output is None:
        raise ConfigurationError(
            f"Tarifs inconnus pour {assignment.model or '(aucun modèle)'} : impossible de borner "
            "le coût du test, rien n'est envoyé."
        )
    if not (spec.confirmed("price_input") and spec.confirmed("price_output")):
        raise ConfigurationError(f"Tarifs de {spec.id} non vérifiés : rien n'est envoyé.")
    worst = (
        PING_INPUT_TOKENS * spec.price_input + settings.llm_max_output_tokens * spec.price_output
    ) / 1e6
    role_settings = settings.model_copy(
        update={
            "llm_provider": assignment.provider,
            "llm_model": assignment.model,
            "llm_effort": assignment.effort,
        }
    )
    return role_settings, worst


def describe_cause(exc: BaseException) -> str:
    """Type et statut HTTP de l'erreur d'origine, sans son message (qui pourrait citer la
    requete) : par exemple « AuthenticationError, HTTP 401 »."""
    cause = exc.__cause__ or exc
    status = getattr(cause, "status_code", None)
    return type(cause).__name__ + (f", HTTP {status}" if status else "")


def ping(settings: Settings, environ: Mapping[str, str] | None, dotenv_path: Path) -> str:
    """Un appel reel minimal, avec sortie structuree comme dans l'application."""
    provider = build_llm_provider(settings, environ, dotenv_path=dotenv_path)
    start = time.monotonic()
    with get_usage_metadata_callback() as usage:
        result = provider.generate_structured(
            "ping",
            [
                {"role": "system", "content": "Test de configuration. Réponds selon le schéma."},
                {"role": "user", "content": "Indique ok = true."},
            ],
            PingResult,
        )
    return (
        f"Appel réel réussi en {time.monotonic() - start:.1f} s (ok = {result.ok}) ; "
        f"{format_usage(summarize_usage(usage.usage_metadata))}."
    )


def main(argv: list[str] | None = None, *, env_file: Path | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ping", action="store_true", help="un appel reel minimal (payant)")
    parser.add_argument("--role", choices=ROLES, help="role vise par --ping")
    parser.add_argument("--budget-usd", type=float, help="plafond strict du --ping par role")
    parser.add_argument("--history", action="store_true", help="historique des modeles charges")
    args = parser.parse_args(argv)
    env_file = env_file or ROOT / ".env"
    if args.role and not args.ping:
        parser.error("--role ne s'utilise qu'avec --ping")
    if args.history:
        try:
            settings = Settings.from_env(dotenv_path=env_file)
        except ConfigurationError as exc:
            print(f"Bloquant : {exc}")
            return 1
        for line in history_lines(settings):
            print(f"- {line}")
        return 0
    infos, warnings, errors, settings = check(dotenv_path=env_file, root=root)
    for line in infos:
        print(f"- {line}")
    for line in warnings:
        print(f"Avertissement : {line}")
    for line in errors:
        print(f"Bloquant : {line}")
    if errors:
        return 1
    customized = settings is not None and any(
        len(a.inherited) < 3 for a in resolve_roles(settings).values()
    )
    if settings is None or (settings.llm_provider == "fake" and not customized):
        print("Faux fournisseur : aucune clé requise. Rien à vérifier pour un modèle réel.")
        return 2
    try:
        # M2 : la meme construction que l'application (validation des roles comprise).
        today = datetime.now(ZoneInfo(settings.default_timezone)).date()
        build_role_providers(settings, dotenv_path=env_file, today=today)
    except ConfigurationError as exc:
        print(f"Bloquant : {exc}")
        return 1
    print("Construction des clients : réussie (aucun appel réseau).")
    if not args.ping:
        hint = " --role <rôle> --budget-usd <plafond>" if customized else ""
        print(
            f"Configuration prête. Pour un appel réel minimal : scripts/check_llm.py --ping{hint}"
        )
        return 0
    target = settings
    if customized or args.role:
        # M3 : un test reel par role exige le role et un budget strict, verifie AVANT l'appel.
        if not args.role or args.budget_usd is None:
            print(
                "Bloquant : rôles configurés : précisez --role et --budget-usd. Rien n'est envoyé."
            )
            return 1
        try:
            target, worst = ping_worst_case(settings, args.role)
        except ConfigurationError as exc:
            print(f"Bloquant : {exc}")
            return 1
        if worst > args.budget_usd:
            print(
                f"Bloquant : pire cas du test {worst:.4f} $ > budget {args.budget_usd:.4f} $. "
                "Rien n'est envoyé."
            )
            return 1
        print(
            f"Test du rôle {ROLE_LABELS[args.role]} : {target.llm_model}, pire cas {worst:.4f} $."
        )
    try:
        print(ping(target, None, env_file))
    except DomainError as exc:
        print(f"Appel réel en échec : {exc.code.value} ({describe_cause(exc)})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
