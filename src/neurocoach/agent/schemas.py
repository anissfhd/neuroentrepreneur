"""Sorties structurees attendues du LLM (DOMAIN_CONTRACTS 11.1 et 11.2).

``PlanDraft`` (11.3) et ``ChangeProposal`` (11.4) sont definis dans le domaine, car leur
validation depend des regles metier.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from neurocoach.domain.models import TaskStatus

Intent = Literal[
    "aide",
    "information_projet",
    "demande_plan",
    "etat_projet",
    "changer_statut",
    "modifier_tache",
    "ajouter_tache",
    "supprimer_tache",
    "replanifier",
    "hors_perimetre",
    "preferences",
    # D-85 : pause et reprise d'un projet (simulation 6 validee).
    "pause_projet",
    "reprendre_projet",
    "autre",
]
MissingField = Literal["resultat_attendu", "contraintes", "temps_disponible"]
# D-79 : informations que la personne peut refuser de donner (le plan avance alors avec des
# hypotheses signalees). « contraintes » reste accepte pour les fiches deja enregistrees.
Declinable = Literal["resultat_attendu", "contraintes", "temps_disponible", "budget", "experience"]
Item = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class LLMOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IntentResult(LLMOutput):
    intent: Intent
    task_ref: str | None = Field(default=None, pattern=r"^T[1-9][0-9]{0,3}$")
    target_status: TaskStatus | None = None
    blocked_reason: str | None = Field(default=None, max_length=300)
    user_text_summary: str = Field(default="", max_length=300)
    # D-85 : taches qu'elle dit avoir terminees (le code verifie que le message les nomme) et
    # raison d'une pause, avec ses mots (affichee dans la carte qu'elle confirme).
    task_refs: list[Annotated[str, StringConstraints(pattern=r"^T[1-9][0-9]{0,3}$")]] = Field(
        default_factory=list, max_length=10
    )
    pause_note: str | None = Field(default=None, max_length=300)
    # D-87 : seconde demande du meme message, traitee juste apres la premiere (« je reprends,
    # mais je n'ai plus que 2 h » ; « j'ai posé l'affiche, mais personne ne m'a contacté »).
    then_intent: Intent | None = None


class ProjectBrief(LLMOutput):
    facts: list[Item] = Field(default_factory=list, max_length=5)
    assumptions: list[Item] = Field(default_factory=list, max_length=5)
    open_questions: list[Item] = Field(default_factory=list, max_length=5)
    target_outcome: str | None = Field(default=None, max_length=300)
    constraints: list[Item] = Field(default_factory=list, max_length=10)
    available_minutes_per_day: int | None = Field(default=None, ge=5, le=720)
    horizon_days: int | None = Field(default=None, ge=1, le=365)
    missing: list[MissingField] = Field(default_factory=list)
    skipped: list[Declinable] = Field(default_factory=list)
    next_question: str | None = Field(default=None, max_length=200)
    # D-76 : titre court PROPOSE pour un projet au titre provisoire ; enregistre seulement
    # apres le clic de l'utilisateur.
    project_title: str | None = Field(default=None, max_length=60)
    # D-78 : ce que le modele a compris du sujet (la derniere precision de l'utilisateur
    # l'emporte), et ses decisions pour ce tour. Le code verifie ensuite ce qui est permis :
    # un plan n'est qu'une proposition a confirmer, une recherche qu'une mission a approuver.
    idea_summary: str | None = Field(default=None, max_length=400)
    wants_plan_now: bool = False
    ready_for_plan: bool = False
    research_request: bool = False
    # D-79 : budget et experience dits par la personne ; recherche refusee (ne pas la
    # reproposer d'elle-meme). Les anciens champs restent lisibles dans les fils enregistres.
    budget: str | None = Field(default=None, max_length=200)
    experience: str | None = Field(default=None, max_length=200)
    research_declined: bool = False
    # D-80 : la personne a demande de ne pas construire de plan pour l'instant.
    plan_declined: bool = False
    ideas_requested: bool = False
    # D-81 : diagnostic de la personne (consultant) : ce qu'elle a dit d'elle-meme.
    interests: str | None = Field(default=None, max_length=300)
    skills: str | None = Field(default=None, max_length=300)
    past_attempts: str | None = Field(default=None, max_length=300)
    motivation: str | None = Field(default=None, max_length=300)
    # D-82 : zone et clientele visees ; points que la personne a demande de retenir.
    market: str | None = Field(default=None, max_length=200)
    notes: list[Item] = Field(default_factory=list, max_length=8)


NextStep = Literal["conseiller", "preparer_plan", "preparer_recherche"]
# D-81 : ou en est l'accompagnement, decide AVANT d'ecrire la reponse (premier champ apres
# l'intention) : decouvrir la personne, proposer des pistes, aider sur une idee precise, ou
# repondre a une demande explicite de conseil immediat.
Stage = Literal["decouverte", "pistes", "idee_precise", "conseil_immediat"]
SpecCategory = Literal["marche", "concurrence", "prix", "avis", "problemes", "temoignages"]


class SpecQuery(LLMOutput):
    category: SpecCategory
    text: str = Field(max_length=200)


class ResearchSpec(LLMOutput):
    """D-80 : ce que la recherche doit trouver, redige par le modele a partir de toute la
    conversation (le titre du projet peut etre provisoire). Le code minimise les requetes,
    borne leur nombre et montre tout dans l'apercu avant le clic « Approuver et lancer »."""

    subject: str = Field(max_length=200)
    segment: str | None = Field(default=None, max_length=150)
    market: str | None = Field(default=None, max_length=60)
    queries: list[SpecQuery] = Field(default_factory=list, max_length=12)
    exclude_senses: list[Item] = Field(default_factory=list, max_length=3)


class CoachBrief(LLMOutput):
    """D-79 : fiche du projet tenue par le modele dans le meme appel que sa reponse."""

    idea_summary: str | None = Field(default=None, max_length=400)
    target_outcome: str | None = Field(default=None, max_length=300)
    available_minutes_per_day: int | None = Field(default=None, ge=5, le=720)
    horizon_days: int | None = Field(default=None, ge=1, le=365)
    budget: str | None = Field(default=None, max_length=200)
    experience: str | None = Field(default=None, max_length=200)
    constraints: list[Item] = Field(default_factory=list, max_length=10)
    facts: list[Item] = Field(default_factory=list, max_length=5)
    assumptions: list[Item] = Field(default_factory=list, max_length=3)
    declined: list[Declinable] = Field(default_factory=list)
    project_title: str | None = Field(default=None, max_length=60)
    # D-81 : diagnostic (avec ses mots) : interets et motivations, competences, essais passes.
    interests: str | None = Field(default=None, max_length=300)
    skills: str | None = Field(default=None, max_length=300)
    past_attempts: str | None = Field(default=None, max_length=300)
    motivation: str | None = Field(default=None, max_length=300)
    # D-82 : zone (pays) et clientele ; points a retenir dans le suivi du projet (par exemple
    # une correction d'analyse demandee) : enregistres avec la fiche, visibles dans l'interface.
    market: str | None = Field(default=None, max_length=200)
    notes: list[Item] = Field(default_factory=list, max_length=8)


DiscoveryTopic = Literal["competence", "experience", "objectif", "temps", "budget", "marche"]


class CoachAssessment(LLMOutput):
    """Interprétation du message avant toute réponse visible."""

    intent: Intent
    stage: Stage = "idee_precise"
    fiche: CoachBrief = Field(default_factory=CoachBrief)
    plan_change: bool = False
    next_step: NextStep = "conseiller"
    plan_requested: bool = False
    plan_request_quote: str = ""
    real_change: bool = False
    research_requested: bool = False
    research_declined: bool = False
    plan_declined: bool = False
    ideas_requested: bool = False
    response_goal: Literal[
        "clarifier", "recommander", "diagnostiquer", "livrer_un_texte", "repondre"
    ] = "repondre"
    next_move: str = Field(default="", max_length=600)
    physical_incident: bool = False
    discovery_topic: DiscoveryTopic | None = None
    practice_quotes: list[str] = Field(default_factory=list)
    concrete_practice: bool = False
    solo_test_requested: bool = False
    commercial_test_requested: bool = False
    scope_adjustment_requested: bool = False
    wants_guidance: bool = False


class OfferRequirement(LLMOutput):
    capability: str
    # Zero means that no user message supports this capability.
    user_message: int
    evidence: str = ""


class OfferProposal(LLMOutput):
    offer: str
    customer: str
    deliverable: str
    requirements: list[OfferRequirement]
    pilot: str
    rationale: str = ""
    question: str = ""
    solo_exercise: Literal["observe", "simulate", "prepare"] = "observe"
    exercise_subject: str = ""
    exercise_output: str = ""
    exercise_action: str = ""
    exercise_requirement: OfferRequirement | None = None


class OfferReview(LLMOutput):
    feasible: bool
    missing_capability: str = ""
    relies_on_unconfirmed_technical_work: bool = False


class CoachResponse(LLMOutput):
    reply: str = ""
    question: str = ""
    recommends_offer: bool = False


class CoachTurn(LLMOutput):
    """D-79 : un seul appel par message ordinaire, une seule decision.

    L'ordre des champs est l'ordre de generation (sorties structurees d'OpenAI) : ``intent``
    d'abord (le code sait aussitot si le message releve d'une route deterministe), puis la
    reponse, diffusee pendant qu'elle s'ecrit, puis la fiche et la decision du tour, prises
    dans le meme raisonnement que la reponse. Le code verifie ensuite les preconditions : un
    plan n'est qu'une proposition a confirmer, une recherche qu'une mission a approuver.
    """

    intent: Intent
    # Defaut pour les sorties imposees des tests ; le vrai modele remplit toujours ce champ.
    stage: Stage = "idee_precise"
    # D-83 : apres « Demander un changement », ce message decrit-il le changement voulu ?
    # Decide avant la reponse, pour qu'elle reste coherente (recette reelle : conseil et
    # question au lieu du plan modifie annonce). Le code decide ensuite, pas le modele.
    plan_change: bool = False
    reply: str = ""
    # D-81 : la seule question du tour, a part : la reponse n'en contient aucune.
    question: str = ""
    fiche: CoachBrief = Field(default_factory=CoachBrief)
    next_step: NextStep = "conseiller"
    plan_requested: bool = False
    real_change: bool = False
    research_declined: bool = False
    plan_declined: bool = False
    # D-82 : elle demande maintenant des idees ou une recommandation (diagnostic ecourte).
    ideas_requested: bool = False
