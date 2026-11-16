"""Politique des sites (R5, D-72) : sites exclus de toute recherche, et pourquoi.

Utilisee a deux endroits : les requetes (Tavily ``exclude_domains``, Exa ``excludeDomains``)
et la reception (tout resultat d'un site exclu est ecarte avant stockage). Aucun
contournement : un site dont l'acces exige une autorisation n'est jamais consulte, ni
directement, ni par un service tiers.
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from neurocoach.domain.research import domain_of

POLICY_PATH = Path(__file__).resolve().parent.parent / "research_domain_policy.toml"


class BlockedSite(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    domains: list[str] = Field(min_length=1)
    label: str
    reason: str
    source: str | None = None
    official: bool = False


class DomainPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    blocked: list[BlockedSite]

    @property
    def excluded_domains(self) -> list[str]:
        return [d for site in self.blocked for d in site.domains][:150]

    def blocked_site(self, url: str) -> BlockedSite | None:
        host = domain_of(url)
        for site in self.blocked:
            if any(host == d or host.endswith("." + d) for d in site.domains):
                return site
        return None

    def excluded_labels(self) -> list[str]:
        """D-80 : sites que la recherche ne consulte jamais (conditions restrictives, Reddit)."""
        return list(dict.fromkeys(site.label for site in self.blocked))

    def preview_lines(self) -> list[str]:
        reddit = next((s for s in self.blocked if s.label == "Reddit"), None)
        others = ", ".join(s.label for s in self.blocked if s.label != "Reddit")
        lines = []
        if reddit is not None:
            lines.append(
                "Reddit : non consulté (" + reddit.reason + ") ; aucun contournement, ni "
                "extraction, ni service tiers"
            )
        if others:
            lines.append(f"Sites exclus (conditions restrictives) : {others}")
        return lines


@lru_cache(maxsize=4)
def load_domain_policy(path: Path = POLICY_PATH) -> DomainPolicy:
    with path.open("rb") as handle:
        return DomainPolicy.model_validate(tomllib.load(handle))
