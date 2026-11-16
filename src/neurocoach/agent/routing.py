"""Routage deterministe : le LLM classe, le code choisit le chemin (D-03, ARCHITECTURE 4.3)."""

from __future__ import annotations

from typing import Any

CHANGE_INTENTS = frozenset({"modifier_tache", "ajouter_tache", "supprimer_tache", "replanifier"})

INTENT_ROUTES: dict[str, str] = {
    "aide": "respond",
    "autre": "respond",
    "etat_projet": "answer_status",
    "changer_statut": "apply_status",
    "hors_perimetre": "out_of_scope",
    "preferences": "respond",
    "pause_projet": "pause",  # D-85 : carte a confirmer
    "reprendre_projet": "pause",
}


def route_intent(intent: str, project_status: str) -> str:
    """Table intention -> noeud ; aucune ecriture n'est jamais choisie par le modele."""
    if intent in ("information_projet", "demande_plan"):
        # Un projet sans plan se clarifie ; un projet actif ne recoit pas de second plan.
        return "clarify" if project_status == "draft" else "respond"
    if intent == "ajouter_tache":
        return "draft_change"
    if intent in CHANGE_INTENTS:
        return "draft_change" if project_status == "active" else "respond"
    return INTENT_ROUTES.get(intent, "respond")


# R3 (D-70) : intentions qu'une recherche peut prendre en charge. Un changement de statut,
# une modification de tache, une question hors perimetre ou de preferences gardent leur route.
RESEARCH_ELIGIBLE = frozenset(
    {"aide", "autre", "information_projet", "demande_plan", "etat_projet"}
)


def after_understand(state: dict[str, Any]) -> str:
    if state.get("error") or not state.get("intent"):
        return "respond"
    if state.get("research_route"):
        return "research"
    if state.get("research_tasks"):
        return "solution_tasks"  # R6 : proposition de taches, a confirmer
    if state.get("research_solve"):
        return "solutions"  # R6 : mission de solutions, a approuver
    if state.get("research_analyze"):
        return "analyze"  # R4 : analyse des sources deja collectees
    if state.get("research_followup"):
        # Reponse du coach appuyee sur les constats de la recherche. D-80 : sur un projet sans
        # plan, c'est le tour unique du coach (fiche et decision tenues : « ne construisez
        # aucun plan » est retenu) ; avec un plan, la reponse simple.
        snapshot = state.get("snapshot") or {}
        draft = snapshot.get("project", {}).get("status") == "draft" and not snapshot.get("tasks")
        return "clarify" if draft else "respond"
    return route_intent(state["intent"]["intent"], state["snapshot"]["project"]["status"])


def after_clarify(state: dict[str, Any]) -> str:
    """D-78 : apres la reponse du coach, le modele a pu demander un plan (proposition a
    confirmer) ou une recherche (mission a approuver) ; rien d'autre n'est possible."""
    result = state.get("last_result") or {}
    if state.get("error"):
        return "respond"
    if state.get("reclassify"):
        return "understand"  # D-79 : intention a route deterministe, classification complete
    if result.get("kind") == "brief_complete":
        return "draft_plan"
    if state.get("research_route"):
        return "research"
    return "respond"


def after_draft(state: dict[str, Any]) -> str:
    return "propose" if state.get("proposal") and not state.get("error") else "respond"


def after_await(state: dict[str, Any]) -> str:
    """Une proposition corrigee (5.5) attend une nouvelle decision."""
    revised = (state.get("last_result") or {}).get("kind") == "revised"
    return "await_decision" if revised else "respond"


def after_respond(state: dict[str, Any]) -> str:
    """D-87 : apres la reponse, la seconde demande du message (s'il y en a une)."""
    return "followup" if state.get("followup") else "end"


def after_followup(state: dict[str, Any]) -> str:
    if state.get("followup_skipped") or not state.get("intent"):
        return "end"
    status = ((state.get("snapshot") or {}).get("project") or {}).get("status") or "active"
    # La premiere action a pu enregistrer un plan : le projet est alors actif.
    route = route_intent(state["intent"]["intent"], "active" if status != "draft" else status)
    return route if route in ("draft_change", "respond") else "respond"


def after_propose(state: dict[str, Any]) -> str:
    return (
        "await_decision" if state.get("pending_action_id") and not state.get("error") else "respond"
    )
