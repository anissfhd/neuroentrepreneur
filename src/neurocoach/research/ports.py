"""Ports de recherche, catalogue des fournisseurs et registre (R1 D-68, R2 D-69).

- ``ResearchProvider`` : un service qui, pour une requete deja minimisee, renvoie des
  resultats bruts et, s'il le communique, le cout reel de l'appel. Tavily et Exa sont deux
  adaptateurs de ce port (``neurocoach.infra.search_providers``) ; Reddit et les forums ne
  le seront que si leurs conditions et l'utilisateur l'autorisent.
- ``FindingExtractor`` : transforme des sources en constats candidats, toujours soumis aux
  regles de preuve du domaine.
- ``ProviderRegistry`` : fournisseurs branches. Une mission ne melange jamais simule et reel.

Ce paquet n'ouvre aucune connexion : les adaptateurs HTTP vivent dans ``infra``.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.research import (
    FindingCandidate,
    ResearchBrief,
    ResearchCategory,
    SourceRecord,
)

CATALOG_PATH = Path(__file__).resolve().parent.parent / "research_providers.toml"


class RawResult(BaseModel):
    """Resultat brut d'un fournisseur : donnee non fiable, bornee avant stockage."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    url: str = Field(min_length=8, max_length=2000)
    title: str = Field(default="", max_length=1000)
    content: str = Field(default="", max_length=20000)
    published_date: date | None = None
    market: str | None = None


class SearchResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    results: list[RawResult] = Field(default_factory=list)
    cost_usd: float | None = Field(default=None, ge=0)  # cout reel annonce par le service


class ProviderError(Exception):
    """Echec d'un fournisseur. Le message ne contient jamais la cle ni les en-tetes."""

    kind = "error"


class ProviderAuthError(ProviderError):
    kind = "auth"


class ProviderRateLimited(ProviderError):
    kind = "rate_limited"


class ProviderQuotaExceeded(ProviderError):
    """Quota gratuit ou limite du compte atteint : le service est suspendu jusqu'au mois
    suivant, pour qu'aucun depassement payant ne soit tente."""

    kind = "quota"


@runtime_checkable
class ResearchProvider(Protocol):
    name: str
    simulated: bool

    def search(
        self,
        query: str,
        *,
        category: ResearchCategory,
        market: str | None,
        max_results: int,
        exclude_domains: list[str] | None = None,
    ) -> SearchResponse: ...


@runtime_checkable
class FindingExtractor(Protocol):
    def extract(
        self, brief: ResearchBrief, sources: list[SourceRecord]
    ) -> list[FindingCandidate]: ...


# --- catalogue -----------------------------------------------------------------------------


class ProviderEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    status: Literal["available", "planned", "disabled"]
    simulated: bool
    cost_per_query_usd: float = Field(ge=0, le=1)
    # Garde du quota gratuit : plafond mensuel LOCAL, inferieur a l'offre gratuite.
    monthly_cap_usd: float | None = Field(default=None, ge=0)
    free_tier: str | None = None
    # Conditions d'utilisation : conserver ou non le texte renvoye (sinon references seules).
    store_excerpts: bool = True
    categories: list[ResearchCategory]
    sends: str
    terms: str
    hosting: str | None = None
    verified: date | None = None
    source: str | None = None


class ProviderCatalog(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    providers: dict[str, ProviderEntry]

    def entry(self, name: str) -> ProviderEntry:
        if name not in self.providers:
            raise DomainError(ErrorCode.VALIDATION_ERROR, f"Fournisseur inconnu : {name}.")
        return self.providers[name]

    def usable(self) -> list[str]:
        """Fournisseurs implementes (``available``) ; les autres ne peuvent pas etre branches."""
        return [name for name, entry in self.providers.items() if entry.status == "available"]


@lru_cache(maxsize=4)
def load_provider_catalog(path: Path = CATALOG_PATH) -> ProviderCatalog:
    with path.open("rb") as handle:
        return ProviderCatalog.model_validate(tomllib.load(handle))


# --- registre ------------------------------------------------------------------------------


class ProviderRegistry:
    """Fournisseurs effectivement branches, tous conformes au catalogue."""

    def __init__(
        self, catalog: ProviderCatalog, providers: Iterable[ResearchProvider] = ()
    ) -> None:
        self.catalog = catalog
        self._providers: dict[str, ResearchProvider] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: ResearchProvider) -> None:
        if not isinstance(provider, ResearchProvider):
            raise TypeError("fournisseur de recherche invalide")
        entry = self.catalog.entry(provider.name)
        if entry.status != "available":
            raise DomainError(
                ErrorCode.VALIDATION_ERROR,
                f"Fournisseur « {provider.name} » non activé ({entry.status}).",
            )
        if provider.simulated != entry.simulated:
            raise DomainError(
                ErrorCode.VALIDATION_ERROR,
                f"Fournisseur « {provider.name} » : simulé ou réel, contraire au catalogue.",
            )
        self._providers[provider.name] = provider

    def names(self) -> list[str]:
        return sorted(self._providers)

    def real_names(self) -> list[str]:
        return [n for n in self.names() if not self._providers[n].simulated]

    def default_names(self) -> list[str]:
        """Les services reels s'ils existent ; la simulation seulement a defaut."""
        return self.real_names() or self.names()

    def get(self, name: str) -> ResearchProvider:
        if name not in self._providers:
            raise DomainError(ErrorCode.VALIDATION_ERROR, f"Fournisseur « {name} » indisponible.")
        return self._providers[name]

    def labels(self) -> dict[str, str]:
        return {name: self.catalog.entry(name).label for name in self._providers}

    def cost(self, name: str) -> float:
        return self.catalog.entry(name).cost_per_query_usd

    def routing(self, names: Iterable[str]) -> dict[ResearchCategory, list[str]]:
        """Categorie -> fournisseurs, selon le catalogue, parmi ``names``."""
        chosen = [n for n in names if n in self._providers]
        return {
            category: [n for n in chosen if category in self.catalog.entry(n).categories]
            for category in ResearchCategory
        }
