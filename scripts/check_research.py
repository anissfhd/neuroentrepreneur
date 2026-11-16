"""Controle des services de recherche web (Tavily, Exa), sans jamais afficher de cle.

Usage :
  python scripts/check_research.py
        controles locaux : cles definies ou absentes, verrou, quota local du mois.
        Aucun appel reseau.
  python scripts/check_research.py --ping --provider tavily --real-api --budget-usd 0.01
        UNE seule recherche reelle (requete neutre fixe, aucune donnee de projet), dans
        l'offre gratuite. Refusee si le cout estime depasse le budget, si le quota local du
        mois est atteint, ou si le verrou NEUROCOACH_FORBID_REAL_RESEARCH est pose.
        Le cout reel annonce par le service est enregistre dans le compteur du mois.

Codes de sortie : 0 pret, 1 probleme bloquant, 2 aucun service configure.
La cle n'est jamais affichee, ni sa longueur, ni un extrait : seulement « définie » ou
« absente ».
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from neurocoach.config import (  # noqa: E402
    FORBID_REAL_RESEARCH,
    RESEARCH_KEYS,
    ConfigurationError,
    Settings,
    read_research_key,
    real_research_forbidden,
)
from neurocoach.domain.research import ResearchCategory  # noqa: E402
from neurocoach.infra.clock import SystemClock  # noqa: E402
from neurocoach.infra.db import Database  # noqa: E402
from neurocoach.infra.research_repository import ResearchRepository  # noqa: E402
from neurocoach.infra.search_providers import build_research_registry  # noqa: E402
from neurocoach.research.policy import load_domain_policy  # noqa: E402
from neurocoach.research.ports import ProviderError, load_provider_catalog  # noqa: E402

PING_QUERY = "small business market research methods"  # neutre, aucune donnee personnelle


def status_lines(settings: Settings, db: Database) -> tuple[list[str], list[str]]:
    catalog = load_provider_catalog()
    now = SystemClock().now()
    period = now.strftime("%Y-%m")
    with db.transaction(write=False) as conn:
        usage = ResearchRepository(conn).provider_usage(period)
    lines, configured = [], []
    for name, variable in RESEARCH_KEYS.items():
        entry = catalog.entry(name)
        defined = read_research_key(name) is not None
        if defined:
            configured.append(name)
        used = usage.get(name, {})
        cap = entry.monthly_cap_usd or 0
        state = "suspendu (quota)" if used.get("exhausted") else "disponible"
        lines.append(
            f"{entry.label} : {variable} {'définie' if defined else 'absente'} ; "
            f"{used.get('queries', 0)} requête(s) et {used.get('reserved_usd', 0.0):.3f} $ "
            f"sur {cap:.2f} $ autorisés en {period} ; {state} ; offre : {entry.free_tier}"
        )
    if real_research_forbidden():
        lines.append(f"Verrou {FORBID_REAL_RESEARCH} posé : aucun service réel ne sera utilisé.")
    lines.append("Simulation : " + ("demandée" if settings.research_simulation else "désactivée"))
    return lines, configured


def ping(
    settings: Settings, db: Database, provider: str, budget: float, market: str | None = None
) -> int:
    registry = build_research_registry(settings)
    if provider not in registry.real_names():
        print(f"{provider} : non branché (clé absente ou verrou posé). Aucun appel.")
        return 1
    entry = registry.catalog.entry(provider)
    cost = entry.cost_per_query_usd
    if cost > budget + 1e-9:
        print(f"Refusé : coût estimé {cost:.3f} $ supérieur au budget {budget:.3f} $.")
        return 1
    now = SystemClock().now()
    period = now.strftime("%Y-%m")
    with db.transaction(write=True) as conn:
        if not ResearchRepository(conn).reserve_provider(
            provider, period, cost, entry.monthly_cap_usd, now
        ):
            print("Refusé : quota local du mois atteint ou service suspendu. Aucun appel.")
            return 1
    print(f"Un appel réel à {entry.label} (coût estimé {cost:.3f} $, offre gratuite)…")
    try:
        # Memes parametres que l'application : sites exclus (R5) et pays, si demande.
        response = registry.get(provider).search(
            PING_QUERY,
            category=ResearchCategory.MARKET,
            market=market,
            max_results=3,
            exclude_domains=load_domain_policy().excluded_domains,
        )
    except ProviderError as exc:
        with db.transaction(write=True) as conn:
            if exc.kind == "quota":
                ResearchRepository(conn).mark_exhausted(provider, period, SystemClock().now())
        print(f"Échec : {exc} (catégorie {exc.kind}).")
        return 1
    actual = response.cost_usd
    if actual is not None and abs(actual - cost) > 1e-9:
        with db.transaction(write=True) as conn:
            ResearchRepository(conn).settle_provider(
                provider, period, actual - cost, SystemClock().now()
            )
    print(f"OK : {len(response.results)} résultat(s) ; coût annoncé : "
          + (f"{actual:.4f} $" if actual is not None else "non communiqué"))  # fmt: skip
    for result in response.results:
        print(f"  - {result.url}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ping", action="store_true")
    parser.add_argument("--provider", choices=sorted(RESEARCH_KEYS))
    parser.add_argument("--real-api", action="store_true")
    parser.add_argument("--budget-usd", type=float)
    parser.add_argument("--market", help="pays transmis (ex. France), comme l'application")
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
    except ConfigurationError as exc:
        print(exc)
        return 1
    db = Database(settings.business_db_path)
    db.migrate()
    lines, configured = status_lines(settings, db)
    print("\n".join(lines))
    if not args.ping:
        return 0 if configured else 2
    if not (args.provider and args.real_api and args.budget_usd is not None):
        print("Un appel réel exige --provider, --real-api et --budget-usd. Aucun appel.")
        return 1
    return ping(settings, db, args.provider, args.budget_usd, args.market)


if __name__ == "__main__":
    raise SystemExit(main())
