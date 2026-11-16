"""Interfaces attendues par les services et implementations neutres.

Le stockage conversationnel (checkpoints LangGraph) est branche en phase 2 ; d'ici la,
``NullConversationStore`` ne conserve aucun message.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class ConversationStore(Protocol):
    def delete_threads(self, thread_ids: Sequence[str]) -> None:
        """Supprime definitivement les fils indiques (E-02, E-03)."""
        ...

    def export_messages(self, thread_id: str) -> list[dict[str, str]]:
        """Messages d'un fil, sous la forme ``{"role": ..., "content": ...}`` (E-01)."""
        ...


class NullConversationStore:
    def delete_threads(self, thread_ids: Sequence[str]) -> None:
        return None

    def export_messages(self, thread_id: str) -> list[dict[str, str]]:
        return []
