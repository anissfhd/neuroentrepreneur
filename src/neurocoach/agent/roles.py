"""Correspondance tache -> role (etape M2, docs/MULTI_MODEL_DESIGN.md).

Table statique et unique : chaque nom de tache passe aux appels LLM par les noeuds a un role,
fixe dans le code. Aucun routage ne depend du contenu d'un message ni d'une sortie du modele.
``classify_intent`` reste dans le role coaching : la qualite du routage en depend (D-62).
"""

from __future__ import annotations

from types import MappingProxyType

from neurocoach.config import ConfigurationError
from neurocoach.llm_catalog import Role

TASK_ROLES: MappingProxyType[str, Role] = MappingProxyType(
    {
        # Coaching entrepreneurial (noeuds du graphe).
        "classify_intent": "coaching",
        "clarify": "coaching",
        "draft_plan": "coaching",
        "draft_change": "coaching",
        "coach_reply": "coaching",
        "coach_turn": "coaching",  # D-79 : reponse, fiche et decision du tour
        "coach_assessment": "coaching",
        "coach_response": "coaching",
        "coach_offer": "coaching",
        "verify_offer": "coaching",
        "research_spec": "coaching",  # D-80 : sujet, zone et requetes d'une recherche
        "research_conclusion": "coaching",  # D-82 : conclusion courte apres une recherche
        # Strategie business : harnais R0 aujourd'hui, Business Researcher ensuite.
        "strategy": "strategy",
        # R4 (D-71) : analyse des recherches par le modele de strategie.
        "research_analysis": "strategy",
        "research_comparison": "strategy",
        "research_solutions": "strategy",  # R6 (D-73)
        # Taches simples : harnais M4 seulement (aucune tache de l'application pour l'instant).
        "simple_classify": "simple",
        "simple_extract": "simple",
        "simple_format": "simple",
    }
)


class UnknownTaskError(ConfigurationError):
    """Tache sans role : erreur de programmation, jamais un repli vers un autre modele."""


def role_for(task: str) -> Role:
    try:
        return TASK_ROLES[task]
    except KeyError:
        raise UnknownTaskError(
            f"Tâche LLM sans rôle : « {task} ». L'ajouter dans neurocoach/agent/roles.py."
        ) from None
