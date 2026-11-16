"""Quelles ecritures exigent une confirmation (DOMAIN_CONTRACTS section 4, DECISIONS D-09).

Regle par defaut : toute ecriture non listee comme directe exige une confirmation.
"""

from __future__ import annotations

from enum import StrEnum


class DirectOperation(StrEnum):
    TASK_STATUS = "task.status"
    PREFERENCES_UPDATE = "preferences.update"
    PROJECT_CREATE_EMPTY = "project.create_empty"


DIRECT_OPERATIONS = frozenset(op.value for op in DirectOperation)


def requires_confirmation(operation: str) -> bool:
    """R-CONF-01 / R-CONF-02 : seules trois operations sont directes."""
    return operation not in DIRECT_OPERATIONS
