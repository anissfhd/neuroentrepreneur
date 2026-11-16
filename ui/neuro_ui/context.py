"""Contexte d'une execution de page : services, lanceur du graphe, utilisateur ouvert."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from neurocoach.domain.models import Preferences, User


@dataclass(frozen=True)
class Ctx:
    runtime: Any  # CoachRuntime
    settings: Any  # Settings
    changes: list[str]  # changements de configuration non appliques (M3)
    user: User
    prefs: Preferences

    @property
    def app(self) -> Any:
        return self.runtime.app

    @property
    def agent(self) -> Any:
        return self.runtime.agent

    @property
    def user_id(self) -> str:
        return self.user.id

    @property
    def first_name(self) -> str:
        return self.user.first_name or self.user.display_name
