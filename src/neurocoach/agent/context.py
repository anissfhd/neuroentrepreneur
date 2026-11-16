"""Contexte d'execution de confiance (R-SEC-02, test technique S-04).

Le contexte n'est jamais checkpointe : le lanceur le fournit a chaque appel, y compris a la
reprise, a partir de la session applicative. Un noeud refuse de s'executer sans lui.
"""

from __future__ import annotations

from dataclasses import dataclass

from langgraph.runtime import Runtime


@dataclass(frozen=True)
class AgentContext:
    user_id: str
    project_id: str


def require_context(runtime: Runtime[AgentContext]) -> AgentContext:
    if runtime.context is None or not isinstance(runtime.context, AgentContext):
        raise PermissionError("Contexte d'identité absent : exécution refusée.")
    return runtime.context
