"""Configuration lue depuis l'environnement ou un fichier .env local (ARCHITECTURE section 8).

Aucun secret n'a de valeur par defaut. Les cles des fournisseurs ne sont jamais stockees dans
``Settings`` : ``read_provider_key`` les lit a part et les rend masquees (``SecretStr``).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

_PREFIX = "NEUROCOACH_"
PROVIDER_KEYS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
# Business Researcher (R2, D-69) : cles des services de recherche, lues comme celles des
# modeles (environnement puis .env), jamais stockees dans Settings ni affichees.
RESEARCH_KEYS = {"tavily": "TAVILY_API_KEY", "exa": "EXA_API_KEY"}
# Verrou : toute valeur non vide interdit les services de recherche reels (tests, CI).
FORBID_REAL_RESEARCH = "NEUROCOACH_FORBID_REAL_RESEARCH"


class ConfigurationError(ValueError):
    pass


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    data_dir: Path = Path("./data")
    llm_provider: Literal["fake", "anthropic", "openai"] = "fake"
    llm_model: str = ""
    llm_timeout_seconds: float = Field(default=30, gt=0, le=300)
    # Recette du 10/11/2026 : les analyses de strategie (R4 a R6) durent environ 45 s avec
    # gpt-5-mini ; 30 s les coupait. Delai propre a ces taches, sans changer celui du coach.
    llm_timeout_seconds_analysis: float = Field(default=120, gt=0, le=600)
    # Meme recette : avec 12 sources reelles, une analyse depassait 4 000 jetons de sortie
    # (raisonnement compris) et revenait tronquee, donc rejetee.
    llm_max_output_tokens_analysis: int = Field(default=8000, ge=64, le=32000)
    # Finalisation (11/11/2026) : appels independants en parallele (recherches web, analyses
    # d'idees, solutions par probleme). 1 = comportement sequentiel d'origine.
    research_parallelism: int = Field(default=4, ge=1, le=8)
    # Les modeles Claude recents reflechissent toujours, et ces jetons comptent dans le plafond :
    # 1200 risquait de tronquer les sorties structurees (constat avant les dialogues reels).
    llm_max_output_tokens: int = Field(default=4000, ge=64, le=16000)
    # Effort de reflexion (Claude recents, modeles de raisonnement OpenAI) ; vide = defaut.
    llm_effort: Literal["low", "medium", "high"] | None = None
    # Nouvelles tentatives automatiques du client (0 pour une campagne a budget limite).
    llm_max_retries: int = Field(default=1, ge=0, le=3)
    # Configuration par role (etape M1, docs/MULTI_MODEL_DESIGN.md), entierement facultative :
    # une valeur absente est heritee de llm_provider, llm_model et llm_effort ci-dessus. Le
    # routage effectif par role est l'objet de M2 ; d'ici la, seule la configuration commune
    # est utilisee par l'application. Validation : neurocoach.llm_catalog.
    llm_provider_coaching: Literal["fake", "anthropic", "openai"] | None = None
    llm_provider_strategy: Literal["fake", "anthropic", "openai"] | None = None
    llm_provider_simple: Literal["fake", "anthropic", "openai"] | None = None
    llm_model_coaching: str = ""
    llm_model_strategy: str = ""
    llm_model_simple: str = ""
    llm_effort_coaching: Literal["low", "medium", "high"] | None = None
    llm_effort_strategy: Literal["low", "medium", "high"] | None = None
    llm_effort_simple: Literal["low", "medium", "high"] | None = None
    pending_action_ttl_minutes: int = Field(default=15, ge=1, le=1440)
    default_timezone: str = "Europe/Paris"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # Business Researcher (R2, D-69). Simulation : uniquement si demandee explicitement
    # (demonstration hors ligne, tests) ; elle n'est jamais melangee a une recherche reelle.
    research_simulation: bool = False
    research_timeout_seconds: float = Field(default=20, gt=0, le=120)

    @field_validator("default_timezone")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"fuseau horaire inconnu : {value}") from exc
        return value

    @property
    def business_db_path(self) -> Path:
        return self.data_dir / "neurocoach.sqlite"

    @property
    def checkpoint_db_path(self) -> Path:
        return self.data_dir / "checkpoints.sqlite"

    @classmethod
    def from_env(
        cls, environ: Mapping[str, str] | None = None, *, dotenv_path: Path | None = None
    ) -> Settings:
        """Variables d'environnement prioritaires sur le fichier .env (s'il existe)."""
        values: dict[str, str] = {}
        env_file = dotenv_path if dotenv_path is not None else Path(".env")
        if env_file.is_file():
            values.update({k: v for k, v in dotenv_values(env_file).items() if v is not None})
        values.update(os.environ if environ is None else environ)
        raw = {
            key[len(_PREFIX) :].lower(): value
            for key, value in values.items()
            if key.startswith(_PREFIX) and value != ""
        }
        try:
            return cls.model_validate(raw)
        except ValidationError as exc:
            raise ConfigurationError(f"Configuration invalide : {exc}") from exc


def read_provider_key(
    provider: str,
    environ: Mapping[str, str] | None = None,
    *,
    dotenv_path: Path | None = None,
) -> SecretStr | None:
    """Cle du fournisseur : environnement d'abord, puis .env. Jamais affichee ni journalisee.

    ``dotenv_values`` ne modifie pas l'environnement : sans cette lecture explicite, une cle
    placee uniquement dans .env n'atteignait pas le SDK (defaut trouve avant les dialogues).
    """
    name = PROVIDER_KEYS.get(provider)
    if name is None:
        return None
    value = (os.environ if environ is None else environ).get(name, "")
    env_file = dotenv_path if dotenv_path is not None else Path(".env")
    if not value and env_file.is_file():
        value = dotenv_values(env_file).get(name) or ""
    value = value.strip()
    return SecretStr(value) if value else None


def read_research_key(
    provider: str,
    environ: Mapping[str, str] | None = None,
    *,
    dotenv_path: Path | None = None,
) -> SecretStr | None:
    """Cle d'un service de recherche (``tavily``, ``exa``) : environnement, puis .env."""
    name = RESEARCH_KEYS.get(provider)
    if name is None:
        return None
    value = (os.environ if environ is None else environ).get(name, "")
    env_file = dotenv_path if dotenv_path is not None else Path(".env")
    if not value and env_file.is_file():
        value = dotenv_values(env_file).get(name) or ""
    value = value.strip()
    return SecretStr(value) if value else None


def real_research_forbidden(environ: Mapping[str, str] | None = None) -> bool:
    """Verrou de securite : lu dans l'environnement du processus ET dans ``environ``."""
    return bool(os.environ.get(FORBID_REAL_RESEARCH)) or bool(
        (environ or {}).get(FORBID_REAL_RESEARCH)
    )
