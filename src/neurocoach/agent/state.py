"""Etat minimal du graphe (ARCHITECTURE 4.1).

L'etat est checkpointe : il ne contient ni identite (fournie par le contexte d'execution),
ni copie de la base. ``snapshot`` est un resume leger, recharge a chaque tour.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class CoachState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    snapshot: dict[str, Any] | None
    intent: dict[str, Any] | None
    brief_draft: dict[str, Any] | None
    proposal: dict[str, Any] | None
    pending_action_id: str | None
    preview_lines: list[str] | None
    last_result: dict[str, Any] | None
    error: dict[str, Any] | None
    # D-61 : question du resultat deja posee, et objectif provisoire propose, NON valide.
    outcome_asked: bool | None
    provisional_outcome: str | None
    # R3 (D-70) : recueil et proposition d'une mission de recherche. Le fil ne garde que des
    # informations dites par l'utilisateur (idees, marche, criteres) et l'identifiant de la
    # mission proposee ; l'approbation et l'execution passent par l'interface, jamais ici.
    research_flow: dict[str, Any] | None
    research_need: dict[str, Any] | None
    research_route: bool | None
    research_offer: bool | None
    research_offered: bool | None
    research_followup: bool | None
    research_analyze: bool | None
    research_solve: bool | None
    research_tasks: bool | None
    # D-77 : coaching proactif. Reformulation deja faite, question de repartition deja posee,
    # recherche proposee avant le plan (et reponse attendue), plan demande maintenant, plan
    # provisoire (sans recherche), conseils quand l'utilisateur est bloque.
    recap_done: bool | None
    # D-85 : date du dernier resume de retour (une fois par pause ou longue absence).
    return_recap_at: str | None
    last_turn_at: str | None  # horloge de l'application, a chaque message traite
    # D-87 : seconde demande du message, traitee apres la premiere (decision ou reponse).
    followup: dict[str, Any] | None
    followup_skipped: bool | None
    schedule_asked: bool | None
    prep_offer: bool | None
    prep_offered: bool | None
    plan_now: bool | None
    provisional_plan: bool | None
    stuck_advice: bool | None
    # D-78 : un plan a deja ete propose de l'initiative du coach (pas de relance a chaque
    # tour) ; la reponse du tour a ete diffusee.
    plan_offered: str | None
    coach_streamed: bool | None
    # D-79 : message envoye directement au coach (sans classification prealable) ; message
    # a reclasser (intention a route deterministe lue dans la sortie du coach) ; decision du
    # tour et sa verification par le code ; derniere proposition de plan (a adapter).
    coach_direct: bool | None
    reclassify: str | None
    coach_decision: dict[str, Any] | None
    plan_previous: dict[str, Any] | None
    # D-81 : questions deja posees par le coach (diagnostic), pour ne jamais les reposer.
    questions_asked: list[str] | None
    discovery_topics_asked: list[str] | None
    last_verified_offer: str | None
    # D-82 : « Demander un changement » sur la derniere proposition de plan.
    plan_change_requested: bool | None
