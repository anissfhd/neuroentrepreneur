"""Checkpointer LangGraph sur SQLite, dans un fichier distinct de la base metier (D-05).

``SqliteConversationStore`` implemente le port ``ConversationStore`` : export des messages
d'un fil (E-01) et suppression definitive des fils (E-02, E-03 ; test technique S-03).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

_ROLES = {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}


def open_checkpointer(path: Path | str) -> SqliteSaver:
    """Connexion partageable entre les fils d'execution de Streamlit (verrou interne au saver)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode = WAL")
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


class SqliteConversationStore:
    def __init__(self, saver: SqliteSaver) -> None:
        self.saver = saver

    def delete_threads(self, thread_ids: Sequence[str]) -> None:
        for thread_id in thread_ids:
            self.saver.delete_thread(thread_id)

    def export_messages(self, thread_id: str) -> list[dict[str, str]]:
        snapshot = self.saver.get_tuple({"configurable": {"thread_id": thread_id}})
        if snapshot is None:
            return []
        messages = snapshot.checkpoint.get("channel_values", {}).get("messages", [])
        return [
            {"role": _ROLES.get(message.type, message.type), "content": str(message.content)}
            for message in messages
        ]
