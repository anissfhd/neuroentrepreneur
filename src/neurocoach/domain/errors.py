"""Codes d'erreur du domaine et messages utilisateur (DOMAIN_CONTRACTS section 12)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    CYCLE_DETECTED = "CYCLE_DETECTED"
    DONE_TASK_PROTECTED = "DONE_TASK_PROTECTED"
    ACTION_EXPIRED = "ACTION_EXPIRED"
    ACTION_ALREADY_DECIDED = "ACTION_ALREADY_DECIDED"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    LLM_OUTPUT_INVALID = "LLM_OUTPUT_INVALID"
    STORAGE_ERROR = "STORAGE_ERROR"


USER_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.NOT_FOUND: "Élément introuvable.",
    ErrorCode.VALIDATION_ERROR: "Certaines informations ne sont pas valides.",
    ErrorCode.INVALID_TRANSITION: "Ce changement de statut n'est pas possible.",
    ErrorCode.CYCLE_DETECTED: "Ces dépendances formeraient une boucle.",
    ErrorCode.DONE_TASK_PROTECTED: "Cette tâche est terminée ; rouvrez-la d'abord.",
    ErrorCode.ACTION_EXPIRED: "Cette proposition a expiré ; je peux la regénérer.",
    ErrorCode.ACTION_ALREADY_DECIDED: "Cette proposition a déjà été traitée.",
    ErrorCode.VERSION_CONFLICT: (
        "Le projet a changé depuis la proposition ; un nouvel aperçu est nécessaire."
    ),
    ErrorCode.LLM_UNAVAILABLE: (
        "Le service de langage ne répond pas. Vos données sont intactes ; réessayez."
    ),
    ErrorCode.LLM_OUTPUT_INVALID: (
        "Je n'ai pas pu produire une proposition valide. Réessayez ou reformulez."
    ),
    ErrorCode.STORAGE_ERROR: "Enregistrement impossible pour le moment ; rien n'a été modifié.",
}


class DomainError(Exception):
    """Erreur metier portant un code stable et un detail lisible."""

    def __init__(self, code: ErrorCode, detail: str | None = None, **data: Any) -> None:
        self.code = code
        self.detail = detail
        self.data = data
        super().__init__(f"{code}: {detail}" if detail else str(code))

    @property
    def user_message(self) -> str:
        base = USER_MESSAGES[self.code]
        return f"{base} {self.detail}" if self.detail else base
