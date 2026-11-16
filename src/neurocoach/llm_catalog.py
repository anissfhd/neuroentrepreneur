"""Catalogue des modeles et configuration par role (etape M1, docs/MULTI_MODEL_DESIGN.md).

Ce module ne construit aucun client et n'appelle aucun fournisseur : il lit le catalogue,
calcule la configuration effective de chaque role et la valide. Le routage effectif entre
modeles (un fournisseur par role) est l'objet de M2 ; tant qu'il n'existe pas, l'application
utilise, comme aujourd'hui, ``NEUROCOACH_LLM_PROVIDER`` et ``NEUROCOACH_LLM_MODEL``.

Principes :
- sans variable de role, chaque role herite de la configuration actuelle ;
- aucune bascule : la validation signale, elle ne remplace jamais un modele par un autre ;
- une information non verifiee du catalogue (``unverified``) ne bloque jamais ;
- les variables existantes ne sont jamais bloquees par le catalogue (compatibilite stricte) ;
  les nouvelles variables par role, elles, sont validees strictement.
Module sans dependance aux extras ``agent`` (D-30).
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from neurocoach.config import ConfigurationError, Settings

CATALOG_PATH = Path(__file__).with_name("llm_models.toml")
Role = Literal["coaching", "strategy", "simple"]
ROLES: tuple[Role, ...] = ("coaching", "strategy", "simple")
ROLE_LABELS = {
    "coaching": "coaching entrepreneurial",
    "strategy": "stratégie et recherche business",
    "simple": "tâches simples",
}
RETIREMENT_WARNING_DAYS = 30
STALE_AFTER_DAYS = 30
VERIFIABLE = {
    "status",
    "retirement_date",
    "replacement",
    "snapshots",
    "efforts",
    "default_effort",
    "apis",
    "structured_outputs",
    "context_window",
    "max_output_tokens",
    "price_input",
    "price_cached_input",
    "price_output",
}


class ModelSpec(BaseModel):
    """Une entree du catalogue. Les valeurs non confirmees sont listees dans ``unverified``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    provider: Literal["openai", "anthropic"]
    status: Literal["available", "deprecated", "retired"]
    retirement_date: date | None = None
    replacement: str | None = None
    snapshots: tuple[str, ...] = ()
    efforts: tuple[str, ...] = ()
    default_effort: str | None = None
    observed_efforts: tuple[str, ...] = ()
    apis: tuple[Literal["chat_completions", "responses", "batch"], ...] = ()
    structured_outputs: bool | None = None
    context_window: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    price_input: float | None = Field(default=None, ge=0)
    price_cached_input: float | None = Field(default=None, ge=0)
    price_output: float | None = Field(default=None, ge=0)
    verified_on: date
    unverified: tuple[str, ...] = ()
    sources: tuple[str, ...] = Field(min_length=1)
    notes: str = ""

    @field_validator("sources")
    @classmethod
    def _official_https(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for url in value:
            if not url.startswith("https://"):
                raise ValueError(f"source non https : {url}")
        return value

    @field_validator("unverified")
    @classmethod
    def _known_fields(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unknown = set(value) - VERIFIABLE
        if unknown:
            raise ValueError(f"champs inconnus dans unverified : {sorted(unknown)}")
        return value

    @model_validator(mode="after")
    def _coherent(self) -> ModelSpec:
        if self.status == "retired" and self.retirement_date is None:
            raise ValueError(f"{self.id} : un modele retire doit avoir une date de retrait")
        if self.default_effort and self.efforts and self.default_effort not in self.efforts:
            raise ValueError(f"{self.id} : effort par defaut absent de la liste des efforts")
        return self

    def confirmed(self, name: str) -> bool:
        return name not in self.unverified

    def names(self) -> tuple[str, ...]:
        return (self.id, *self.snapshots)


class Catalog(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    catalog_version: str = Field(min_length=1)
    models: tuple[ModelSpec, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_and_linked(self) -> Catalog:
        seen: set[str] = set()
        for spec in self.models:
            for name in spec.names():
                if name in seen:
                    raise ValueError(f"identifiant en double dans le catalogue : {name}")
                seen.add(name)
        for spec in self.models:
            if spec.replacement and spec.replacement not in seen:
                raise ValueError(f"{spec.id} : remplacement inconnu du catalogue")
        return self

    def get(self, name: str) -> ModelSpec | None:
        return next((spec for spec in self.models if name in spec.names()), None)

    def ids(self) -> list[str]:
        return [spec.id for spec in self.models]


def load_catalog(path: Path | None = None) -> Catalog:
    """Charge et valide le catalogue ; toute anomalie devient une ``ConfigurationError``."""
    source = path or CATALOG_PATH
    try:
        data = tomllib.loads(source.read_text(encoding="utf-8"))
        return Catalog.model_validate(data)
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Catalogue des modèles introuvable : {source.name}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(
            f"Catalogue des modèles illisible ({source.name}) : {exc}"
        ) from exc
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"]) or "catalogue"
        raise ConfigurationError(
            f"Catalogue des modèles invalide ({where}) : {first['msg']}"
        ) from exc


@lru_cache(maxsize=1)
def default_catalog() -> Catalog:
    return load_catalog()


# --- configuration par role ----------------------------------------------------------------


@dataclass(frozen=True)
class RoleAssignment:
    """Configuration effective d'un role et origine de chaque valeur."""

    role: Role
    provider: str
    model: str
    effort: str | None
    inherited: frozenset[str]  # champs repris de la configuration commune

    def describe(self) -> str:
        def tag(field: str) -> str:
            return " (hérité)" if field in self.inherited else ""

        model = self.model or "(aucun)"
        effort = self.effort or "par défaut"
        return (
            f"{ROLE_LABELS[self.role]} : {self.provider}{tag('provider')} · {model}{tag('model')}"
            f" · effort {effort}{tag('effort')}"
        )


def resolve_roles(settings: Settings) -> dict[Role, RoleAssignment]:
    """Sans variable de role, chaque role reprend fournisseur, modele et effort communs."""
    roles: dict[Role, RoleAssignment] = {}
    for role in ROLES:
        own = {
            "provider": getattr(settings, f"llm_provider_{role}"),
            "model": getattr(settings, f"llm_model_{role}") or None,
            "effort": getattr(settings, f"llm_effort_{role}"),
        }
        common = {
            "provider": settings.llm_provider,
            "model": settings.llm_model,
            "effort": settings.llm_effort,
        }
        roles[role] = RoleAssignment(
            role=role,
            provider=own["provider"] or common["provider"],
            model=own["model"] or common["model"],
            effort=own["effort"] or common["effort"],
            inherited=frozenset(name for name, value in own.items() if value is None),
        )
    return roles


# --- validation ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Issue:
    severity: Literal["erreur", "avertissement"]
    role: Role | None
    message: str


def _issue(strict: bool, role: Role, message: str) -> Issue:
    # Compatibilite stricte : une valeur venant de la configuration existante (heritee) n'est
    # jamais bloquee par le catalogue ; une nouvelle variable de role l'est.
    return Issue("erreur" if strict else "avertissement", role, message)


def validate_roles(
    settings: Settings, catalog: Catalog | None = None, *, today: date
) -> list[Issue]:
    """Erreurs et avertissements, sans jamais remplacer un modele par un autre."""
    catalog = catalog or default_catalog()
    issues: list[Issue] = []
    per_model: dict[str, tuple[ModelSpec, list[str], list[bool]]] = {}
    for role, assignment in resolve_roles(settings).items():
        label = ROLE_LABELS[role]
        own_model = "model" not in assignment.inherited
        own_provider = "provider" not in assignment.inherited
        own_effort = "effort" not in assignment.inherited
        if assignment.provider == "fake":
            if own_model or own_effort:
                issues.append(
                    Issue(
                        "avertissement",
                        role,
                        f"Rôle {label} : modèle ou effort ignorés avec le faux fournisseur.",
                    )
                )
            continue
        if not assignment.model:
            # Modele commun vide : deja signale par la configuration existante (check-llm).
            if own_provider:
                issues.append(Issue("erreur", role, f"Rôle {label} : aucun modèle configuré."))
            continue
        spec = catalog.get(assignment.model)
        if spec is None:
            issues.append(
                _issue(
                    own_model,
                    role,
                    f"Modèle inconnu pour le rôle {label} : {assignment.model}. Modèles "
                    f"déclarés : {', '.join(catalog.ids())} (src/neurocoach/llm_models.toml).",
                )
            )
            continue
        if spec.provider != assignment.provider:
            issues.append(
                _issue(
                    own_model or own_provider,
                    role,
                    f"{spec.id} est un modèle {spec.provider}, mais le rôle {label} est configuré "
                    f"pour {assignment.provider}.",
                )
            )
        issues.extend(_effort_issues(spec, assignment, own_effort or own_model))
        users = per_model.setdefault(spec.id, (spec, [], []))
        users[1].append(label)
        users[2].append(own_model)
    # Cycle de vie et fraicheur : un seul message par modele, avec les roles concernes.
    for spec, labels, strict in per_model.values():
        issues.extend(_lifecycle_issues(spec, labels, today, any(strict)))
        age = (today - spec.verified_on).days
        if age > STALE_AFTER_DAYS:
            issues.append(
                Issue(
                    "avertissement",
                    None,
                    f"Fiche de {spec.id} vérifiée il y a {age} jours : revérifier les sources.",
                )
            )
    return issues


def _effort_issues(spec: ModelSpec, assignment: RoleAssignment, strict: bool) -> list[Issue]:
    effort = assignment.effort
    label = ROLE_LABELS[assignment.role]
    if effort is None:
        return []
    if spec.confirmed("efforts") and spec.efforts:
        if effort not in spec.efforts:
            return [
                _issue(
                    strict,
                    assignment.role,
                    f"L'effort « {effort} » n'est pas accepté par {spec.id} (accepté : "
                    f"{', '.join(spec.efforts)}).",
                )
            ]
        return []
    if effort in spec.observed_efforts:
        return []
    # Information non verifiee : jamais bloquante.
    return [
        Issue(
            "avertissement",
            assignment.role,
            f"Rôle {label} : effort « {effort} » non confirmé par la documentation de {spec.id}.",
        )
    ]


def _lifecycle_issues(spec: ModelSpec, labels: list[str], today: date, strict: bool) -> list[Issue]:
    roles = ", ".join(labels)
    plural = "s" if len(labels) > 1 else ""
    replacement = f" ; remplacement indiqué : {spec.replacement}" if spec.replacement else ""
    when = spec.retirement_date
    if spec.status == "retired" and spec.confirmed("status"):
        return [
            Issue(
                "erreur" if strict else "avertissement",
                None,
                f"{spec.id} est retiré depuis le {when:%d/%m/%Y} : choisissez un autre modèle "
                f"(rôle{plural} {roles}){replacement}.",
            )
        ]
    if when is None or not spec.confirmed("retirement_date"):
        return []
    days = (when - today).days
    if days < 0:
        return [
            Issue(
                "avertissement",
                None,
                f"Date de retrait de {spec.id} dépassée ({when:%d/%m/%Y}, rôle{plural} {roles}) : "
                f"vérifier sa disponibilité et mettre à jour le catalogue{replacement}.",
            )
        ]
    if days <= RETIREMENT_WARNING_DAYS or spec.status == "deprecated":
        return [
            Issue(
                "avertissement",
                None,
                f"{spec.id} (rôle{plural} {roles}) sera retiré le {when:%d/%m/%Y}, dans {days} "
                f"jours{replacement}. Aucune bascule automatique : le changement reste à décider.",
            )
        ]
    return []


def unknown_llm_variables(names: Iterable[str]) -> list[str]:
    """Variables NEUROCOACH_LLM_* inconnues (faute de frappe probable), jamais bloquantes."""
    known = {f"NEUROCOACH_{name.upper()}" for name in Settings.model_fields}
    return sorted(
        name for name in set(names) if name.startswith("NEUROCOACH_LLM_") and name not in known
    )


def raise_on_errors(issues: Iterable[Issue]) -> None:
    """Pour M2 : refuser de demarrer sur une erreur de configuration, avec son message."""
    errors = [issue.message for issue in issues if issue.severity == "erreur"]
    if errors:
        raise ConfigurationError(" ".join(errors))


def summary(settings: Settings, roles: Mapping[Role, RoleAssignment] | None = None) -> list[str]:
    return [assignment.describe() for assignment in (roles or resolve_roles(settings)).values()]


# --- configuration chargee et configuration demandee (etape M3) ----------------------------

RESTART_MESSAGE = (
    "Configuration des modèles modifiée, mais pas encore active : redémarrez l'application pour "
    "l'appliquer. D'ici là, les modèles réellement utilisés restent ceux indiqués comme chargés."
)


@dataclass(frozen=True)
class LoadedConfig:
    """Configuration effectivement chargee par une execution de l'application (sans secret)."""

    assignments: Mapping[Role, RoleAssignment]
    common: tuple[float, int, int]  # delai, plafond de sortie, nouvelles tentatives
    catalog_version: str
    fingerprint: str

    def triples(self) -> dict[Role, tuple[str, str, str | None]]:
        return {role: (a.provider, a.model, a.effort) for role, a in self.assignments.items()}


def describe_triple(provider: str, model: str, effort: str | None) -> str:
    return f"{provider} · {model or '(aucun)'} · effort {effort or 'par défaut'}"


def loaded_config(settings: Settings, catalog: Catalog | None = None) -> LoadedConfig:
    """Configuration et empreinte stable (aucune cle : seuls des noms et des reglages)."""
    import hashlib
    import json

    version = (catalog or default_catalog()).catalog_version
    roles = resolve_roles(settings)
    common = (
        settings.llm_timeout_seconds,
        settings.llm_max_output_tokens,
        settings.llm_max_retries,
    )
    data = {
        "roles": {role: [a.provider, a.model, a.effort] for role, a in roles.items()},
        "common": list(common),
        "catalog": version,
    }
    digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return LoadedConfig(roles, common, version, digest)


def loaded_lines(loaded: LoadedConfig) -> list[str]:
    return [
        f"{ROLE_LABELS[role]} : {describe_triple(*triple)} (chargé)"
        for role, triple in loaded.triples().items()
    ]


def pending_changes(loaded: LoadedConfig, requested: Settings) -> list[str]:
    """Differences entre la configuration demandee (.env, environnement) et celle chargee.

    Vide si elles concordent. Rien n'est jamais applique ici : un redemarrage est necessaire.
    """
    wanted = loaded_config(requested)
    if wanted.fingerprint == loaded.fingerprint:
        return []
    changes = [
        f"{ROLE_LABELS[role]} : {describe_triple(*before)} → {describe_triple(*after)}"
        for role, (before, after) in (
            (role, (loaded.triples()[role], wanted.triples()[role])) for role in ROLES
        )
        if before != after
    ]
    if wanted.common != loaded.common:
        changes.append(
            "paramètres communs modifiés (délai, plafond de sortie ou nouvelles tentatives)"
        )
    if wanted.catalog_version != loaded.catalog_version:
        old, new = loaded.catalog_version, wanted.catalog_version
        changes.append(f"catalogue des modèles mis à jour ({old} → {new})")
    return changes
