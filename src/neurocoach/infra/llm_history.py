"""Historique des changements de configuration des modeles (etape M3, D-64).

Une ligne par role dont le fournisseur, le modele ou l'effort a change depuis le dernier
enregistrement : un redemarrage avec la meme configuration n'ajoute rien. Aucune cle, aucun
secret, aucun utilisateur ni contenu de conversation : seulement des noms et des reglages.
La table est en ajout seul (declencheurs SQL).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from neurocoach.infra.db import Database

Triple = tuple[str, str, str | None]  # fournisseur, modele, effort
_COLUMNS = (
    "recorded_at, role, provider_before, model_before, effort_before, provider_after, "
    "model_after, effort_after, catalog_version, fingerprint"
)


@dataclass(frozen=True)
class ConfigEvent:
    recorded_at: str  # ISO 8601, UTC
    role: str
    before: Triple | None
    after: Triple
    catalog_version: str
    fingerprint: str


def _event(row: sqlite3.Row) -> ConfigEvent:
    before = None
    if row["provider_before"] is not None:
        before = (row["provider_before"], row["model_before"], row["effort_before"])
    return ConfigEvent(
        recorded_at=row["recorded_at"],
        role=row["role"],
        before=before,
        after=(row["provider_after"], row["model_after"], row["effort_after"]),
        catalog_version=row["catalog_version"],
        fingerprint=row["fingerprint"],
    )


def record_if_changed(
    database: Database,
    current: Mapping[str, Triple],
    *,
    catalog_version: str,
    fingerprint: str,
    now: datetime,
) -> list[ConfigEvent]:
    """Ajoute une ligne par role modifie ; renvoie les lignes ajoutees (vide sinon)."""
    stamp = now.isoformat(timespec="seconds")
    added: list[ConfigEvent] = []
    with database.transaction(write=True) as conn:  # BEGIN IMMEDIATE : pas de doublon concurrent
        latest = {
            row["role"]: _event(row)
            for row in conn.execute(
                f"SELECT {_COLUMNS} FROM llm_config_events e "
                "WHERE id = (SELECT MAX(id) FROM llm_config_events WHERE role = e.role)"
            )
        }
        for role, after in current.items():
            previous = latest.get(role)
            if previous is not None and previous.after == tuple(after):
                continue
            before = previous.after if previous is not None else (None, None, None)
            conn.execute(
                f"INSERT INTO llm_config_events ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (stamp, role, *before, *after, catalog_version, fingerprint),
            )
            added.append(
                ConfigEvent(
                    stamp,
                    role,
                    previous.after if previous else None,
                    tuple(after),
                    catalog_version,
                    fingerprint,
                )
            )
    return added


def list_events(database: Database) -> list[ConfigEvent]:
    with database.transaction(write=False) as conn:
        rows = conn.execute(f"SELECT {_COLUMNS} FROM llm_config_events ORDER BY id").fetchall()
    return [_event(row) for row in rows]


def read_events(path: Path) -> list[ConfigEvent] | None:
    """Lecture seule, sans creer ni migrer la base : ``None`` si elle n'existe pas encore ou
    n'a pas l'historique (application jamais demarree depuis M3)."""
    if not Path(path).is_file():
        return None
    conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(f"SELECT {_COLUMNS} FROM llm_config_events ORDER BY id").fetchall()
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
    return [_event(row) for row in rows]


def last_loaded(events: list[ConfigEvent]) -> dict[str, Triple]:
    """Derniere configuration chargee par role, d'apres l'historique."""
    state: dict[str, Triple] = {}
    for event in events:
        state[event.role] = event.after
    return state
