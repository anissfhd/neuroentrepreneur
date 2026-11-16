"""Horloges concretes : systeme (production) et fixe (tests, demonstration)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC).replace(microsecond=0)


class FixedClock:
    """Horloge deterministe, avancable a la main."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("FixedClock attend un instant avec fuseau")
        self._now = start.astimezone(UTC).replace(microsecond=0)

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta
