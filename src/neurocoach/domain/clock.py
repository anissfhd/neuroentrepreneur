"""Interface d'horloge et calculs de dates calendaires (DOMAIN_CONTRACTS section 0).

Le domaine ne lit jamais l'heure systeme : il recoit toujours l'instant courant.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo


class Clock(Protocol):
    def now(self) -> datetime:
        """Instant courant, conscient du fuseau, en UTC."""
        ...


def local_today(now_utc: datetime, timezone_name: str) -> date:
    """Date calendaire du jour dans le fuseau d'affichage."""
    return now_utc.astimezone(ZoneInfo(timezone_name)).date()
