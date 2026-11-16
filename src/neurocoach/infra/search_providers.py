"""Adaptateurs HTTP des services de recherche reels (R2, D-69) et registre de l'application.

Tavily (``POST https://api.tavily.com/search``) et Exa (``POST https://api.exa.ai/search``),
d'apres leur documentation officielle lue le 10/11/2026. Regles :
- une seule tentative par requete (aucune nouvelle tentative automatique : pas de double
  facturation) ; delai borne ;
- la cle n'apparait que dans l'en-tete d'autorisation : jamais dans un message d'erreur, un
  journal, une exception ou la base ;
- Tavily : recherche ``basic`` (1 credit), credits reels demandes (``include_usage``) ;
- Exa : recherche ``lite``, SANS contenu des pages (conditions : pas de conservation sans
  accord ecrit ; et aucun cout de contenu) ; cout reel lu dans ``costDollars``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from neurocoach.config import Settings, read_research_key, real_research_forbidden
from neurocoach.domain.research import INTERNATIONAL, ResearchCategory
from neurocoach.research.fake import FakeResearchProvider
from neurocoach.research.ports import (
    ProviderAuthError,
    ProviderCatalog,
    ProviderError,
    ProviderQuotaExceeded,
    ProviderRateLimited,
    ProviderRegistry,
    RawResult,
    ResearchProvider,
    SearchResponse,
    load_provider_catalog,
)

TAVILY_URL = "https://api.tavily.com/search"
EXA_URL = "https://api.exa.ai/search"
TAVILY_CREDIT_USD = 0.008
# Pays acceptes par le parametre ``country`` de Tavily (noms anglais en minuscules) et codes
# ISO pour ``userLocation`` d'Exa. Un marche absent de cette table n'est pas transmis.
TAVILY_COUNTRIES = {
    "France": "france", "Maroc": "morocco", "Tunisie": "tunisia", "Algérie": "algeria",
    "Belgique": "belgium", "Suisse": "switzerland", "Canada": "canada", "Sénégal": "senegal",
    "Espagne": "spain", "Allemagne": "germany", "Royaume-Uni": "united kingdom",
    "États-Unis": "united states", "Luxembourg": "luxembourg",
}  # fmt: skip
ISO_COUNTRIES = {
    "France": "FR", "Maroc": "MA", "Tunisie": "TN", "Algérie": "DZ", "Belgique": "BE",
    "Suisse": "CH", "Canada": "CA", "Sénégal": "SN", "Côte d'Ivoire": "CI", "Espagne": "ES",
    "Allemagne": "DE", "Royaume-Uni": "GB", "États-Unis": "US", "Luxembourg": "LU",
}  # fmt: skip


def parse_date(value: Any) -> date | None:
    """Date de publication tolerante (ISO 8601 ou RFC 2822) ; inconnue plutot qu'inventee."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    try:
        parsed: datetime = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return None
    return parsed.date()


def _raise_for_status(response: httpx.Response, provider: str) -> None:
    code = response.status_code
    if code < 400:
        return
    if code in (401, 403):
        raise ProviderAuthError(f"{provider} : clé refusée (HTTP {code})")
    if code == 429:
        raise ProviderRateLimited(f"{provider} : trop de requêtes (HTTP 429)")
    if code in (402, 432, 433):
        raise ProviderQuotaExceeded(f"{provider} : quota ou crédits épuisés (HTTP {code})")
    raise ProviderError(f"{provider} : réponse HTTP {code}")


class _HttpProvider:
    simulated = False
    name = ""
    url = ""

    def __init__(self, key: Any, *, timeout: float, client: httpx.Client | None = None) -> None:
        # ``key`` est un SecretStr : sa valeur n'est lue qu'au moment de l'en-tete.
        self._key = key
        self._client = client or httpx.Client(timeout=timeout)
        self._timeout = timeout

    def __repr__(self) -> str:  # jamais la cle
        return f"<{type(self).__name__}>"

    def _post(self, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        try:
            response = self._client.post(self.url, json=body, headers=headers,
                                         timeout=self._timeout)  # fmt: skip
        except httpx.TimeoutException:
            raise ProviderError(f"{self.name} : délai dépassé") from None
        except httpx.HTTPError:
            raise ProviderError(f"{self.name} : erreur réseau") from None
        _raise_for_status(response, self.name)
        try:
            data = response.json()
        except ValueError:
            raise ProviderError(f"{self.name} : réponse illisible") from None
        if not isinstance(data, dict):
            raise ProviderError(f"{self.name} : réponse inattendue")
        return data


class TavilyProvider(_HttpProvider):
    name = "tavily"
    url = TAVILY_URL

    def search(
        self,
        query: str,
        *,
        category: ResearchCategory,
        market: str | None,
        max_results: int,
        exclude_domains: list[str] | None = None,
    ) -> SearchResponse:
        body: dict[str, Any] = {
            "query": query,
            "search_depth": "basic",
            "topic": "general",
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "include_published_date": True,
            "include_usage": True,
        }
        if exclude_domains:
            body["exclude_domains"] = list(exclude_domains)[:150]  # R5 : sites non autorises
        country = TAVILY_COUNTRIES.get(market or "")
        if country and market != INTERNATIONAL:
            body["country"] = country
        headers = {"Authorization": f"Bearer {self._key.get_secret_value()}"}
        data = self._post(body, headers)
        results = []
        for item in data.get("results") or []:
            if not isinstance(item, dict) or not str(item.get("url", "")).startswith("http"):
                continue
            results.append(
                RawResult(
                    url=str(item["url"])[:2000],
                    title=str(item.get("title") or "")[:1000],
                    content=str(item.get("content") or "")[:20000],
                    published_date=parse_date(item.get("published_date")),
                    market=market if country else None,
                )
            )
        usage = data.get("usage") or {}
        credits = usage.get("credits") if isinstance(usage, dict) else None
        cost = float(credits) * TAVILY_CREDIT_USD if isinstance(credits, int | float) else None
        return SearchResponse(results=results[:max_results], cost_usd=cost)


class ExaProvider(_HttpProvider):
    name = "exa"
    url = EXA_URL

    def search(
        self,
        query: str,
        *,
        category: ResearchCategory,
        market: str | None,
        max_results: int,
        exclude_domains: list[str] | None = None,
    ) -> SearchResponse:
        body: dict[str, Any] = {
            "query": query,
            "type": "lite",
            "numResults": max_results,
            # Conditions d'Exa : rien n'est conserve sans accord ecrit ; on ne demande donc
            # ni texte ni extraits (references seules), ce qui evite aussi leur cout.
            "contents": {"text": False, "highlights": False},
        }
        if category is ResearchCategory.COMPETITION:
            body["category"] = "company"
        if exclude_domains:
            body["excludeDomains"] = list(exclude_domains)[:1200]  # R5 : sites non autorises
        iso = ISO_COUNTRIES.get(market or "")
        if iso:
            body["userLocation"] = iso
        headers = {"x-api-key": self._key.get_secret_value()}
        data = self._post(body, headers)
        results = []
        for item in data.get("results") or []:
            if not isinstance(item, dict) or not str(item.get("url", "")).startswith("http"):
                continue
            results.append(
                RawResult(
                    url=str(item["url"])[:2000],
                    title=str(item.get("title") or "")[:1000],
                    content="",  # jamais conserve (voir ci-dessus)
                    published_date=parse_date(item.get("publishedDate")),
                    market=market if iso else None,
                )
            )
        cost_block = data.get("costDollars") or {}
        total = cost_block.get("total") if isinstance(cost_block, dict) else None
        cost = float(total) if isinstance(total, int | float) else None
        return SearchResponse(results=results[:max_results], cost_usd=cost)


REAL_PROVIDERS = {"tavily": TavilyProvider, "exa": ExaProvider}


def configured_real_providers(
    environ: Mapping[str, str] | None = None, *, dotenv_path: Any = None
) -> list[str]:
    """Services dont la cle est presente (sans jamais lire ni montrer sa valeur ici)."""
    return [
        name
        for name in REAL_PROVIDERS
        if read_research_key(name, environ, dotenv_path=dotenv_path) is not None
    ]


def build_research_registry(
    settings: Settings | None = None,
    environ: Mapping[str, str] | None = None,
    *,
    dotenv_path: Any = None,
    simulation: bool | None = None,
    catalog: ProviderCatalog | None = None,
    extra: Mapping[str, ResearchProvider] | None = None,
    client: httpx.Client | None = None,
) -> ProviderRegistry:
    """Registre de l'application.

    - Services reels : Tavily et Exa, chacun seulement si sa cle existe et si le verrou
      ``NEUROCOACH_FORBID_REAL_RESEARCH`` est absent.
    - Simulation : uniquement si elle est demandee (``NEUROCOACH_RESEARCH_SIMULATION=1``).
    - ``extra`` : doublures de test, conformes au catalogue.
    """
    settings = settings or Settings()
    catalog = catalog or load_provider_catalog()
    registry = ProviderRegistry(catalog)
    use_simulation = settings.research_simulation if simulation is None else simulation
    if use_simulation:
        registry.register(FakeResearchProvider())
    if not real_research_forbidden(environ):
        for name, factory in REAL_PROVIDERS.items():
            key = read_research_key(name, environ, dotenv_path=dotenv_path)
            if key is not None and catalog.entry(name).status == "available":
                registry.register(
                    factory(key, timeout=settings.research_timeout_seconds, client=client)
                )
    for provider in (extra or {}).values():
        registry.register(provider)
    return registry
