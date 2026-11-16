"""Noeuds du graphe (ARCHITECTURE 4.2).

Regles respectees ici :
- le LLM n'ecrit jamais : il produit des objets valides que le code transmet aux services ;
- seule ``propose`` cree une action en attente, dans un noeud distinct de l'interruption (S-01) ;
- ``await_decision`` n'a aucun effet de bord et relit l'issue en base apres la reprise ;
- les chiffres et statuts des reponses viennent des gabarits deterministes (D-15) ;
- aucune preference n'est jamais modifiee par le graphe (PF-01).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import timedelta
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from neurocoach.agent import coaching as co
from neurocoach.agent.context import AgentContext, require_context
from neurocoach.agent.guards import (
    DATE_NOT_PROPOSED_MESSAGE,
    DATE_REQUEST,
    DEADLINES_DISABLED_MESSAGE,
    DEFAULT_STATUS_QUESTION,
    NEXT_QUERY,
    OVERLOAD,
    OVERLOAD_RATIONALE,
    PREFERENCE_REQUEST,
    PREFERENCES_MESSAGE,
    REPLAN_REQUEST,
    STATUS_QUESTIONS,
    WHOLE_PLAN,
    change_question,
    clean_brief,
    designate_task,
    designate_tasks,
    designated_refs,
    drop_example_lists,
    drop_internal_labels,
    drop_questions,
    drop_technical,
    echoes,
    fit_plan,
    ground_profile,
    grounded_in,
    humanize_field_names,
    infer_target_status,
    is_lightening,
    keep_concrete_instructions,
    keep_one_question,
    keep_vouvoiement,
    lighter_step,
    localize_dates,
    repeated_question,
    single_question,
    tasks_over,
)
from neurocoach.agent.llm import STREAM, LLMProvider
from neurocoach.agent.prompts import build_messages
from neurocoach.agent.research_analyst import LLMResearchAnalyst
from neurocoach.agent.research_dialogue import (
    ANALYZE,
    ASK_CRITERIA,
    ASK_IDEAS,
    ASK_IDEAS_UNKNOWN,
    ASK_MARKET_SUFFIX,
    CANCELLED,
    EXPLICIT,
    FOLLOWUP,
    NO_ACTIONS,
    NO_PROBLEMS,
    NOT_ENABLED,
    PROPOSAL_INTRO,
    REDO,
    RESEARCH_COMMAND,
    RESULT_QUESTION,
    SENSITIVE_ADVICE,
    SKIP,
    SOLUTIONS_INTRO,
    SOLVE,
    TASKS_PHASE,
    TO_TASKS,
    detect_research_need,
    known_criteria,
    market_from_answer,
    parse_ideas,
)
from neurocoach.agent.routing import RESEARCH_ELIGIBLE
from neurocoach.agent.schemas import (
    CoachAssessment,
    CoachResponse,
    CoachTurn,
    IntentResult,
    OfferProposal,
    OfferReview,
    ProjectBrief,
    ResearchSpec,
)
from neurocoach.application.formatting import (
    OUT_OF_SCOPE_MESSAGE,
    format_next_actions,
    format_next_step,
    format_progress,
    format_status_change,
)
from neurocoach.application.research_format import (
    DETAILS_MARKER,
    analysis_facts,
    format_analysis,
    proposal_message,
    solutions_facts,
)
from neurocoach.application.research_service import PROGRESS, MissionRequest
from neurocoach.bootstrap import Application
from neurocoach.domain.clock import local_today
from neurocoach.domain.errors import USER_MESSAGES, DomainError, ErrorCode
from neurocoach.domain.models import ActionStatus, ActionType, PendingAction, TaskStatus
from neurocoach.domain.plans import (
    BriefUpdate,
    Change,
    ChangeCommand,
    PlanDraft,
    PlanPhaseDraft,
    PlanTaskDraft,
    apply_command,
    strip_deadlines,
)
from neurocoach.domain.preview import describe_preview
from neurocoach.domain.profiles import best_title
from neurocoach.domain.project_profile import KnownFacts, extract_known
from neurocoach.domain.proposals import (
    ChangeProposal,
    ProposedChange,
    ProposedFields,
    proposal_to_command,
)
from neurocoach.domain.research import (
    CATEGORY_LABELS,
    MissionStatus,
    RequestedQuery,
    ResearchCategory,
    detect_markets,
)
from neurocoach.domain.solutions import select_problems

HISTORY_LIMIT = 6
# D-78 : intentions traitees par le coach (reponse du modele) sur un projet sans plan.
COACHED_WITHOUT_PLAN = frozenset(
    {"aide", "autre", "etat_projet", "demande_plan", "information_projet", "modifier_tache",
     "ajouter_tache", "supprimer_tache", "replanifier"}
)  # fmt: skip
# Recherche demandee ou acceptee dans la conversation : marche, concurrence, prix, avis.
PREP_CATEGORIES = (
    ResearchCategory.MARKET,
    ResearchCategory.COMPETITION,
    ResearchCategory.PRICES,
    ResearchCategory.REVIEWS,
)
MAX_TASKS_IN_FACTS = 30
# D-79 : intentions dont la route se decide sans autre champ (lues en tete de la sortie du
# coach) ; les autres (statut d'une tache, recherche…) passent par la classification.
DIRECT_INTENTS = frozenset({"hors_perimetre", "preferences", "pause_projet", "reprendre_projet"})
# D-87 : demandes qui peuvent suivre une premiere demande du meme message, et premieres
# demandes qui peuvent en porter une seconde.
FOLLOWUP_INTENTS = frozenset({"replanifier", "modifier_tache", "aide"})
FIRST_INTENTS = frozenset({"reprendre_projet", "changer_statut", "etat_projet"})

# D-85 : propositions d'etat (pause, reprise, taches terminees) : texte de la carte.
STATE_TEXTS = {
    "tasks_done": (
        "Je note ces tâches comme terminées :",
        "Rien n'est enregistré tant que vous n'avez pas cliqué sur « Confirmer les tâches "
        "terminées ».",
    ),
    "pause": (
        "Je vous propose de mettre le projet en pause :",
        "Votre plan, vos tâches et ce que je retiens de votre projet restent enregistrés ; "
        "rien n'est supprimé et aucune échéance n'est ajoutée. Rien ne change tant que vous "
        "n'avez pas cliqué sur « Mettre en pause ».",
    ),
    "resume": (
        "Je vous propose de reprendre le projet :",
        "Vos tâches terminées restent acquises. Rien ne change tant que vous n'avez pas cliqué "
        "sur « Reprendre le projet ».",
    ),
}

HELP_MESSAGE = (
    "Je peux vous aider à clarifier votre idée, à construire un plan de petites actions, à "
    "suivre vos tâches (par exemple « J'ai terminé T1 ») et à replanifier sans pression. "
    "Vos préférences (longueur des réponses, nombre d'actions visibles, échéances) se règlent "
    "dans le panneau Préférences : je ne les modifie jamais moi-même."
)
# D-79 : preconditions d'un plan propose de l'initiative du coach (verifiees par le code).
# Une information refusee par la personne ne manque plus : le plan avance avec une hypothese.
PLAN_PREREQUISITES = {
    "idee": "votre idée",
    "temps_disponible": "votre disponibilité",
    "budget": "votre budget",
}
DECLINED_LABELS = {
    "resultat_attendu": "le résultat visé",
    "contraintes": "les contraintes",
    "temps_disponible": "la disponibilité",
    "budget": "le budget",
    "experience": "l'expérience",
}
# D-86 : question du coach qui propose une recherche (offre, pas encore un accord).
RESEARCH_OFFER = re.compile(
    r"\b(souhaitez|voulez|dois-je|puis-je|je (?:lance|fasse|peux))\b.*"
    r"\b(recherche|v[ée]rifi\w*|march[ée]|concurren\w*|tarifs?|prix)\b",
    re.IGNORECASE,
)
ALREADY_PAUSED = (
    "Le projet est déjà en pause : votre plan et vos tâches sont conservés. Dites-moi "
    "quand vous souhaitez reprendre."
)
IMPLICIT_CANCEL = (
    "La proposition précédente n'a pas été enregistrée, car vous avez envoyé un nouveau message."
)
PLAN_CREATION_LINES = ("Nouvelle phase", "Nouvelle tâche")
CHANGE_REQUESTED = (
    "D'accord, je mets cette proposition de côté : rien n'a été enregistré. Dites-moi ce que "
    "vous souhaitez changer, et je vous présenterai un plan modifié."
)
DECISION_MESSAGES = {
    "cancelled": "D'accord, rien n'a été modifié.",
    "expired": USER_MESSAGES[ErrorCode.ACTION_EXPIRED],
    "superseded": "Cette proposition a été remplacée par une plus récente.",
    "pending": "La proposition attend toujours votre décision.",
}


def _error(exc: DomainError) -> dict[str, Any]:
    return {"code": exc.code.value, "message": exc.user_message}


def _last_human_text(messages: list[AnyMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


def _user_texts(state: dict[str, Any]) -> list[str]:
    """Tout ce que l'utilisateur a ecrit dans ce fil, plus l'idee saisie a la creation."""
    texts = [str(m.content) for m in state.get("messages", []) if isinstance(m, HumanMessage)]
    idea = ((state.get("snapshot") or {}).get("project") or {}).get("idea")
    return [*texts, idea] if idea else texts


def _last_ai_text(messages: list[AnyMessage]) -> str | None:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return str(message.content)
    return None


def _quote_key(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.replace("\u2019", "'").replace("\u2010", "-")
    return " ".join(normalized.casefold().split())


def _dedupe(*lists: list[str], limit: int) -> list[str]:
    seen: list[str] = []
    for items in lists:
        for item in items:
            if item not in seen:
                seen.append(item)
    return seen[:limit]


def merge_brief(
    previous: ProjectBrief, new: ProjectBrief, *, cumulative: bool = False
) -> ProjectBrief:
    """Cumule les informations des tours de clarification ; la derniere valeur l'emporte.
    Une information donnee apres un refus l'emporte sur le refus."""
    skipped = _dedupe(previous.skipped, new.skipped, limit=5)
    provided = {
        "budget": new.budget,
        "temps_disponible": new.available_minutes_per_day,
        "resultat_attendu": new.target_outcome,
        "experience": new.experience,
    }
    skipped = [item for item in skipped if not (provided.get(item))]

    def lists(old: list[str], fresh: list[str], limit: int) -> list[str]:
        # D-80 : la fiche du modele est cumulative (il recoit la precedente) : ses listes
        # remplacent les anciennes, sans quoi une hypothese perimee (« temps non precise »)
        # resterait a cote de l'information donnee depuis.
        if cumulative and fresh:
            return _dedupe(fresh, limit=limit)
        return _dedupe(old, fresh, limit=limit)

    return ProjectBrief(
        facts=lists(previous.facts, new.facts, 5),
        assumptions=lists(previous.assumptions, new.assumptions, 5),
        open_questions=new.open_questions,
        target_outcome=new.target_outcome or previous.target_outcome,
        constraints=lists(previous.constraints, new.constraints, 10),
        available_minutes_per_day=new.available_minutes_per_day
        or previous.available_minutes_per_day,
        horizon_days=new.horizon_days or previous.horizon_days,
        skipped=skipped,
        project_title=new.project_title or previous.project_title,
        idea_summary=new.idea_summary or previous.idea_summary,
        budget=new.budget or previous.budget,
        experience=new.experience or previous.experience,
        research_declined=new.research_declined or previous.research_declined,
        # Un plan demande leve le refus ; sinon le refus reste jusqu'a nouvel ordre.
        plan_declined=(new.plan_declined or previous.plan_declined) and not new.wants_plan_now,
        interests=new.interests or previous.interests,
        skills=new.skills or previous.skills,
        past_attempts=new.past_attempts or previous.past_attempts,
        motivation=new.motivation or previous.motivation,
        market=new.market or previous.market,
        notes=lists(previous.notes, new.notes, 8),
    )


def plan_missing(brief: ProjectBrief, known: KnownFacts, subject: str | None) -> list[str]:
    """D-79 : ce qui manque pour qu'un plan soit propose de l'initiative du coach. Calcule par
    le code (fiche du modele et faits dits par l'utilisateur), jamais repris tel quel du LLM."""
    missing = [] if (subject or "").strip() else ["idee"]
    time_known = brief.available_minutes_per_day or known.session_minutes()
    if not time_known and "temps_disponible" not in brief.skipped:
        missing.append("temps_disponible")
    budget_known = known.budget_eur is not None or known.budget_mad is not None or brief.budget
    if not budget_known and "budget" not in brief.skipped:
        missing.append("budget")
    return missing


def plan_key(brief: ProjectBrief) -> str:
    """Informations dont depend un plan : une reformulation du sujet ne la change pas."""
    values = (
        brief.target_outcome,
        brief.available_minutes_per_day,
        brief.horizon_days,
        sorted(brief.constraints),
        brief.budget,
        brief.experience,
        sorted(brief.skipped),
    )
    return "|".join(str(value) for value in values)


def brief_from_turn(turn: CoachTurn) -> ProjectBrief:
    fiche = turn.fiche
    return ProjectBrief(
        facts=fiche.facts,
        assumptions=fiche.assumptions,
        target_outcome=fiche.target_outcome,
        constraints=fiche.constraints,
        available_minutes_per_day=fiche.available_minutes_per_day,
        horizon_days=fiche.horizon_days,
        skipped=fiche.declined,
        project_title=fiche.project_title,
        idea_summary=fiche.idea_summary,
        budget=fiche.budget,
        experience=fiche.experience,
        research_declined=turn.research_declined,
        wants_plan_now=turn.plan_requested,
        plan_declined=turn.plan_declined and not turn.plan_requested,
        interests=fiche.interests,
        skills=fiche.skills,
        past_attempts=fiche.past_attempts,
        motivation=fiche.motivation,
        market=fiche.market,
        notes=fiche.notes,
    )


# D-81 : diagnostic d'un consultant. Le code dit au modele ce qu'il sait deja de la personne
# et ce qu'il ignore encore (jamais redemander) ; le modele choisit la question suivante.
DISCOVERY_LABELS = {
    "centres_interet": "ses centres d'intérêt",
    "competences": "ce qu'elle sait faire (compétences)",
    "experience": "sa situation actuelle et son expérience",
    # D-84 : un sujet par libelle ; un libelle double (« pays ou zone, et clientèle »)
    # faisait poser deux questions en une (recette reelle du 12/11/2026).
    "tentatives_passees": "ses essais passés de projet",
    # D-82 : objectif et motivation ne font qu'un (recette du 12/11/2026 : la motivation
    # etait redemandee alors que l'objectif chiffre venait d'etre donne).
    "objectifs": "ses objectifs et motivations",
    "temps": "son temps disponible",
    "budget": "son budget",
    "zone": "son pays ou sa zone de vente",
    "contraintes": "ses contraintes et préférences de travail",
}
# Libelles montres a la personne (« Ce que le coach a retenu ») : a la deuxieme personne.
DISCOVERY_DISPLAY = {
    "centres_interet": "Vos centres d'intérêt",
    "competences": "Ce que vous savez faire",
    "experience": "Votre situation et votre expérience",
    "tentatives_passees": "Vos essais passés",
    "objectifs": "Vos objectifs",
    "temps": "Votre temps disponible",
    "budget": "Votre budget",
    "zone": "Votre zone et votre clientèle",
    "contraintes": "Vos contraintes et préférences",
}
# D-82 : ce qu'un consultant sait avant de recommander une activite (recette : pistes
# proposees des que le temps etait connu, sans budget ni essais passes).
NO_PROFILE = "son profil (intérêts ou compétences)"
# Budget de la personne pour son projet (« je peux investir 150 € », « mon budget est de… »).
OWN_BUDGET = re.compile(
    r"\b(je (peux|pourrais|souhaite|veux|compte) (y )?(investir|mettre|d[ée]penser|consacrer)|"
    r"mon budget|budget (de|maximum|max)|\d+\s*(€|euros?) (au )?(maximum|max|de budget))"
)
REQUIRED_FOR_IDEAS = ("tentatives_passees", "objectifs", "temps", "budget", "zone")
# Affirmations d'enregistrement : jamais sans operation reelle (recette : « corrections
# prises en compte et enregistrées » sans aucune ecriture).
SAVE_CLAIM = re.compile(
    r"\b(j'(?:ai |)(?:bien |aussi |)(?:enregistr|consign|sauvegard|archiv)\w*|"
    r"(?:est|sont|a été|ont été) (?:bien |)(?:enregistr|consign|sauvegard)\w*|"
    r"\benregistr\w* (?:dans|au) |ajout\w* au dossier|dans (?:le|votre) (?:suivi|dossier))",
    re.I,
)


def drop_save_claims(text: str) -> str:
    """Retire les phrases qui annoncent un enregistrement que le coach n'a pas fait."""
    sentences = re.split(r"(?<=[.!?…])\s+", text.strip())
    return " ".join(s for s in sentences if s and not SAVE_CLAIM.search(s))


def first_sentence(text: str) -> str:
    sentences = [s for s in re.split(r"(?<=[.!…])\s+", text.strip()) if s]
    return sentences[0] if sentences else ""


LIST_MARKERS = re.compile(r"(?m)^\s*(?:[-•*]|\d+[.)])\s+\S|(?:^|\s)[1-9][.)]\s+\S")
SOCIAL_GREETING = re.compile(
    r"(?:(?:bonjour|bonsoir|salut|coucou|hello)\b[\s,.!?]*)?"
    r"(?P<check_in>(?:(?:ça va|ca va|cv)\b[\s,.!?]*)?"
    r"(?:comment (?:allez[- ]vous|vas[- ]tu)|vous allez bien|tu vas bien)?)[\s,.!?]*",
    re.IGNORECASE,
)
ADD_DISCUSSION_TASKS = re.compile(
    r"^(?:peux[- ]tu |pouvez[- ]vous )?(?:ajoute[rz]?|mets?|mettez|enregistre[rz]?)\b"
    r".*\b(?:tâches?|taches?|plan)\b",
    re.IGNORECASE,
)
PLAN_SAVED_QUESTION = re.compile(
    r"^(?:est-ce que\s+)?(?:tu as|vous avez|as-tu|avez-vous)\s+"
    r"(?:ajout[ée]r?|enregistr[ée]r?)\b.*\b(?:plan|tâches?|taches?)\b",
    re.IGNORECASE,
)


def _time_text(brief: ProjectBrief, known: KnownFacts) -> str | None:
    """Temps disponible lisible (recette : « 240 », minutes brutes d'une seance)."""
    if known.weekly_hours:
        hours = f"{known.weekly_hours:g}".replace(".", ",")
        return f"environ {hours} h par semaine" + (f" ({known.schedule})" if known.schedule else "")
    minutes = brief.available_minutes_per_day or known.session_minutes()
    # D-84 : l'unite qu'elle a employee (« 30 minutes par jour »), sinon une seance.
    unit = "par jour" if known.daily_minutes else "par séance"
    return f"environ {minutes} min {unit}" if minutes else None


def discovery_values(brief: ProjectBrief, known: KnownFacts) -> dict[str, Any]:
    """Elements du diagnostic, dans l'ordre de DISCOVERY_LABELS (valeur vide : inconnu)."""
    values: dict[str, Any] = {
        "centres_interet": brief.interests,
        "competences": brief.skills,
        "experience": brief.experience or ("débutant" if known.beginner else None),
        "zone": brief.market or known.city,
        "tentatives_passees": brief.past_attempts,
        "objectifs": brief.target_outcome or brief.motivation,
        "temps": _time_text(brief, known)
        or ("non précisé (refus)" if "temps_disponible" in brief.skipped else None),
        "budget": brief.budget
        or (f"{known.budget_eur} €" if known.budget_eur is not None else None)
        or (f"{known.budget_mad:g} DH" if known.budget_mad is not None else None)
        or ("non précisé (refus)" if "budget" in brief.skipped else None),
        "contraintes": "; ".join(brief.constraints) or None,
    }
    return {key: values.get(key) for key in DISCOVERY_LABELS}


def discovery_status(
    brief: ProjectBrief,
    known: KnownFacts,
    subject: str | None = None,
    asked: list[str] | None = None,
) -> dict[str, Any]:
    values = discovery_values(brief, known)
    known_items = {DISCOVERY_LABELS[k]: v for k, v in values.items() if v}
    profile = any(values[k] for k in ("centres_interet", "competences", "experience"))
    missing_for_ideas = [DISCOVERY_LABELS[k] for k in REQUIRED_FOR_IDEAS if not values[k]]
    return {
        # Idee comprise par le coach, ou donnee explicitement a la creation du projet.
        "idee_retenue": bool(brief.idea_summary or (subject or "").strip()),
        "deja_connu": known_items,
        "a_decouvrir": [DISCOVERY_LABELS[k] for k, v in values.items() if not v],
        # Assez pour recommander : un profil, et les essais passes, l'objectif, le temps,
        # le budget et la zone. Sinon, le diagnostic continue (sauf demande explicite).
        "assez_pour_des_pistes": profile and not missing_for_ideas,
        "manque_avant_recommandation": [*([] if profile else [NO_PROFILE]), *missing_for_ideas],
        # Questions deja posees : jamais reposees ; si elle n'a pas su repondre, le sujet est
        # aborde autrement (exemple, autre angle) ou laisse pour plus tard.
        "questions_deja_posees": list(asked or [])[-8:],
    }


MENTIONED = (
    # « recherche de marché » designe toute l'etude : seule la demande nomme le marche seul.
    (re.compile(r"\bdemande\b|taille du march|tendances?\b"), ResearchCategory.MARKET),
    (re.compile(r"\bconcurren\w*"), ResearchCategory.COMPETITION),
    (re.compile(r"\bprix\b|\btarifs?\b"), ResearchCategory.PRICES),
    (re.compile(r"\bavis\b|t[ée]moignages?"), ResearchCategory.REVIEWS),
)


def mentioned_categories(text: str) -> list[ResearchCategory]:
    """Categories nommees dans une demande de recherche adressee au coach."""
    lower = text.lower()
    return [category for rx, category in MENTIONED if rx.search(lower)]


def research_conclusion(
    llm: Any, analysis: Any, sources: list[Any], brief: ProjectBrief, texts: list[str]
) -> str:
    """D-82 : conclusion d'expert, courte, ecrite par le modele a partir des seuls elements
    VALIDES de l'analyse (le detail reste consultable). En cas d'echec : un resume factuel
    de l'analyse validee, jamais un conseil invente. Meme texte apres l'approbation d'une
    recherche et apres « refais l'analyse » (D-83)."""
    facts = {
        "analyse": analysis_facts(analysis, sources),
        "brief": brief.model_dump(mode="json"),
        "decouverte": discovery_status(brief, extract_known(texts)),
        "demande": texts[-2:],
        "preferences": {},
    }
    try:
        if llm is None:
            raise DomainError(ErrorCode.LLM_UNAVAILABLE)
        messages = build_messages(
            "research_conclusion", text=texts[-1] if texts else "", facts=facts
        )
        text = drop_internal_labels(
            drop_save_claims(keep_vouvoiement(llm.generate_text("research_conclusion", messages)))
        )
        if text.strip():
            return text.strip()
    except DomainError:
        pass
    order = {"insuffisant": 0, "partiel": 1, "suffisant": 2}
    levels = [i.evidence for i in analysis.ideas if i.evidence in order]
    comparison = analysis.comparison
    recommended = (
        f" Piste la mieux étayée : {comparison.recommended}."
        if comparison is not None and comparison.recommended
        else ""
    )
    level = f" Niveau de preuve : {min(levels, key=order.__getitem__)}." if levels else ""
    return f"L'analyse des résultats est terminée.{level}{recommended} Le détail suit."


def spec_markets(market: str) -> list[str]:
    """Zone dite par la personne, normalisee (pays reconnu, international) ou gardee telle
    quelle si elle est courte ; elle n'est transmise aux fournisseurs que si elle est connue."""
    detected = detect_markets([market])
    return detected or [" ".join(market.split())[:40]]


def spec_request(spec: ResearchSpec) -> dict[str, Any]:
    queries = [
        RequestedQuery(category=ResearchCategory(q.category), text=q.text)
        for q in spec.queries
        if len(q.text.strip()) >= 3
    ]
    return {
        "subject": " ".join(spec.subject.split())[:200] or None,
        "segment": spec.segment,
        "queries": queries[:12],
        "exclude_senses": [s[:80] for s in spec.exclude_senses],
    }


def _labels(names: list[str]) -> str:
    words = [PLAN_PREREQUISITES[name] for name in names]
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " et " + words[-1]


def shorten(text: str, response_length: str) -> str:
    """PF-02 : longueur maximale des textes rediges par le LLM."""
    limits = {"court": 2, "standard": 5}
    if response_length not in limits:
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(sentences[: limits[response_length]])


def complete_sentences(text: str) -> str:
    """Retire une phrase inachevee en fin de texte. Constate avec gpt-5-mini : pour tenir
    dans la limite du schema (300 caracteres), le modele coupe sa justification en plein mot."""
    text = text.strip()
    if not text or text[-1] in ".!?…»)":
        return text
    end = max(text.rfind(mark) for mark in ".!?…")
    return text[: end + 1] if end != -1 else ""


class CoachNodes:
    def __init__(self, app: Application, llm: LLMProvider) -> None:
        self.app = app
        self.llm = llm

    # --- contexte -------------------------------------------------------------------
    def _today(self, user_id: str):
        prefs = self.app.coach.get_preferences(user_id)
        return local_today(self.app.clock.now(), prefs.display_timezone)

    def load_context(self, state: dict[str, Any], runtime: Runtime[AgentContext]) -> dict:
        context = require_context(runtime)
        coach = self.app.coach
        prefs = coach.get_preferences(context.user_id)
        snapshot = coach.get_snapshot(context.user_id, context.project_id)
        summary = coach.get_progress(context.user_id, context.project_id)
        next_actions = coach.get_next_actions(context.user_id, context.project_id)
        phase_titles = {phase.id: phase.title for phase in snapshot.phases.values()}
        refs = {task.id: task.ref for task in snapshot.tasks.values()}
        tasks = [
            {
                "ref": task.ref,
                "title": task.title,
                "status": task.status.value,
                "phase": phase_titles.get(task.phase_id, ""),
                "estimate_minutes": task.estimate_minutes,
                "due_date": task.due_date.isoformat()
                if task.due_date and prefs.deadlines_enabled
                else None,
                "depends_on": sorted(
                    refs[dep] for (owner, dep) in snapshot.dependencies if owner == task.id
                ),
            }
            for task in snapshot.ordered_tasks()[:MAX_TASKS_IN_FACTS]
        ]
        project = snapshot.project
        facts = {
            "today": local_today(self.app.clock.now(), prefs.display_timezone).isoformat(),
            "project": {
                "title": project.title,
                "idea": project.idea,
                "status": project.status.value,
                "target_outcome": project.target_outcome,
                "constraints": project.constraints,
                "available_minutes_per_day": project.available_minutes_per_day,
                # D-76 : titre provisoire, a proposer (jamais enregistre sans clic).
                "title_pending": project.title_pending,
                # D-85 : pause reelle, enregistree en base (date et raison confirmees).
                "pause": {
                    "depuis": local_today(project.paused_at, prefs.display_timezone).isoformat(),
                    "raison": project.pause_note,
                }
                if project.paused_at
                else None,
            },
            "phases": [phase.title for phase in snapshot.ordered_phases()],
            "tasks": tasks,
            "next_actions": [item.ref for item in next_actions.items]
            or ([next_actions.fallback.ref] if next_actions.fallback else []),
            # D-78 : facteurs du choix calcules par le code, pour que le coach l'explique.
            "next_action_details": [
                {"ref": item.ref, "title": item.title, "factors": item.factors}
                for item in next_actions.items
            ],
            "progress": format_progress(summary),
            "preferences": {
                "response_length": prefs.response_length.value,
                "one_question_at_a_time": prefs.one_question_at_a_time,
                "deadlines_enabled": prefs.deadlines_enabled,
                "cadence": prefs.cadence.value,
            },
            "history": [
                {
                    "role": "user" if isinstance(message, HumanMessage) else "assistant",
                    "content": str(message.content)[:500],
                }
                for message in state.get("messages", [])[-HISTORY_LIMIT - 1 : -1]
            ],
        }
        return {
            "snapshot": facts,
            # D-85 : date du dernier message, avec l'horloge de l'application (retour apres
            # une longue absence).
            "last_turn_at": self.app.clock.now().isoformat(),
            "followup": None,
            "intent": None,
            "proposal": None,
            "pending_action_id": None,
            "preview_lines": None,
            "last_result": None,
            "error": None,
            "research_need": None,
            "research_route": None,
            "research_offer": None,
            "research_followup": None,
            "research_analyze": None,
            "research_solve": None,
            "research_tasks": None,
            "plan_now": None,
            "stuck_advice": None,
            "coach_streamed": None,
            "coach_direct": None,
            "reclassify": None,
            "coach_decision": None,
        }

    def _known(self, state: dict[str, Any]) -> Any:
        """D-77 : faits dits par l'utilisateur dans TOUT le fil (pas seulement les 6 derniers
        messages transmis au modele)."""
        return extract_known(_user_texts(state), asked_schedule=bool(state.get("schedule_asked")))

    def _idea_label(self, state: dict[str, Any]) -> str | None:
        project = (state.get("snapshot") or {}).get("project") or {}
        texts = [t for t in [project.get("idea"), *_user_texts(state)] if t]
        title = best_title(texts)
        if title is None:
            return None
        return title[0].lower() + title[1:] if not title[:2].isupper() else title

    def _facts(self, state: dict[str, Any], **extra: Any) -> dict[str, Any]:
        brief = ProjectBrief(**(state.get("brief_draft") or {}))
        subject = brief.idea_summary or (state["snapshot"].get("project") or {}).get("idea")
        missing = plan_missing(brief, self._known(state), subject)
        return {
            **state["snapshot"],
            "brief": {**brief.model_dump(mode="json"), "missing": missing},
            # D-77 : faits connus, relus dans tout le fil a chaque tour (memoire durable).
            "connu": self._known(state).as_facts(),
            # D-78 : le sujet vient de la comprehension du modele (derniere precision de
            # l'utilisateur) ou de l'idee decrite, jamais du titre.
            "sujet": brief.idea_summary or (state["snapshot"].get("project") or {}).get("idea"),
            "intent": (state.get("intent") or {}).get("intent"),
            **extra,
        }

    # --- comprehension et clarification -----------------------------------------------
    def _classify_facts(self, state: dict[str, Any]) -> dict[str, Any]:
        """D-78 : contexte compact pour la classification (latence) : statut, taches, dernier
        message du coach. La reponse elle-meme recoit le contexte complet."""
        snapshot = state.get("snapshot") or {}
        project = snapshot.get("project") or {}
        return {
            "project": {"status": project.get("status")},
            "tasks": [
                {"ref": t["ref"], "title": t["title"], "status": t["status"]}
                for t in snapshot.get("tasks", [])
            ],
            "preferences": snapshot.get("preferences", {}),
            "dernier_message_du_coach": (_last_ai_text(state.get("messages", [])) or "")[:400],
            # D-85 : la raison d'une pause est souvent dite juste avant (« elles refusent… »).
            "messages_precedents": [
                str(m.content)[:300]
                for m in [m for m in state.get("messages", []) if isinstance(m, HumanMessage)][
                    -3:-1
                ]
            ],
            "recherche": (state.get("research_flow") or {}).get("stage"),
        }

    def understand(self, state: dict[str, Any], runtime: Runtime[AgentContext]) -> dict:
        ctx = require_context(runtime)
        text = _last_human_text(state.get("messages", []))
        status = (state.get("snapshot") or {}).get("project", {}).get("status")
        if ADD_DISCUSSION_TASKS.match(text.strip()):
            return {"intent": IntentResult(intent="ajouter_tache").model_dump(mode="json")}
        if PLAN_SAVED_QUESTION.match(text.strip()):
            return {"intent": IntentResult(intent="etat_projet").model_dump(mode="json")}
        if self._is_research_command(state, text, ctx):
            # Finalisation : commande explicite apres une recherche (« analyse », « cherche des
            # solutions », « transforme ces actions en tâches ») : sa route est certaine.
            intent = IntentResult(intent="autre", user_text_summary=text[:300])
            update: dict[str, Any] = {"intent": intent.model_dump(mode="json")}
            update.update(
                self._research_route(state, text, "autre", status, ctx.user_id, ctx.project_id)
            )
            return update
        aborted = state.get("reclassify")
        if aborted in DIRECT_INTENTS:
            # D-79 : l'intention lue en tete de la sortie du coach suffit pour ces routes
            # (refus hors perimetre, renvoi aux preferences) : aucun second appel.
            intent = IntentResult(intent=aborted, user_text_summary=text[:300])
            # Drapeau consomme : sans cela, le coach renverrait sans fin vers la comprehension.
            return {**self._route_update(state, text, intent, ctx), "reclassify": None}
        if not aborted and self._direct_coaching(state, text):
            # D-79 : message ordinaire d'un projet sans plan : aucune classification prealable.
            # Le coach repond en un seul appel dont le premier champ est l'intention ; si elle
            # releve d'une route deterministe, l'appel est interrompu et le message reclasse.
            intent = IntentResult(intent="information_projet", user_text_summary=text[:300])
            return {"intent": intent.model_dump(mode="json"), "coach_direct": True}
        messages = build_messages("classify_intent", text=text, facts=self._classify_facts(state))
        try:
            intent = self.llm.generate_structured("classify_intent", messages, IntentResult)
        except DomainError as exc:
            return {"error": _error(exc), "reclassify": None}
        return {**self._route_update(state, text, intent, ctx), "reclassify": None}

    def _direct_coaching(self, state: dict[str, Any], text: str) -> bool:
        """Projet sans plan, hors recueil d'une recherche, sans demande de preferences ni de
        recherche reconnue par le code : la conversation va directement au coach."""
        snapshot = state.get("snapshot") or {}
        if (snapshot.get("project") or {}).get("status") != "draft" or snapshot.get("tasks"):
            return False
        stage = (state.get("research_flow") or {}).get("stage")
        if stage in ("collect_ideas", "collect_criteria", "collect_market"):
            return False
        lower = text.lower()
        # D-82 : une demande de recherche passe aussi par le coach (sa fiche retient l'idee
        # nommee dans la demande : recette, « il manque encore votre idée » juste apres).
        # Seule la comparaison de plusieurs idees (liste a recueillir) garde son dialogue.
        if PREFERENCE_REQUEST.search(lower) or not self._coach_handles_research(state, text):
            return False
        return not (
            stage == "done"
            and any(p.search(lower) for p in (ANALYZE, FOLLOWUP, SOLVE, TO_TASKS, REDO, EXPLICIT))
        )

    @staticmethod
    def _coach_handles_research(state: dict[str, Any], text: str) -> bool:
        """Faux pour les dialogues de recherche qui recueillent une liste : comparer plusieurs
        idees, ou relancer une comparaison deja preparee (idees en memoire)."""
        need = detect_research_need(text)
        if need is None:
            return True
        ideas = (state.get("research_flow") or {}).get("ideas")
        return need.kind != "compare" and not (need.kind == "explicit" and ideas)

    @classmethod
    def _new_research_asked(cls, state: dict[str, Any], text: str) -> bool:
        """Nouvelle recherche demandee : avant toute recherche, une question de concurrence ou
        de prix en est une ; apres, seule une demande explicite (« faites une recherche… »),
        les autres questions portant sur les resultats deja trouves."""
        need = detect_research_need(text)
        if need is None or not cls._coach_handles_research(state, text):
            return False
        done = (state.get("research_flow") or {}).get("stage") == "done"
        return not done or need.kind == "explicit" or bool(EXPLICIT.search(text.lower()))

    def _coached(self, state: dict[str, Any], text: str, intent: str, ctx: AgentContext) -> bool:
        """L'intention lue dans la sortie du coach garde-t-elle le message dans la
        conversation ? Meme table que pour une classification (``_route_update``)."""
        try:
            parsed = IntentResult(intent=intent)  # type: ignore[arg-type]
        except ValueError:
            return True  # sortie invalide : la validation finale le signalera
        update = self._route_update(state, text, parsed, ctx)
        flags = ("research_route", "research_tasks", "research_solve", "research_analyze",
                 "research_followup")  # fmt: skip
        if (
            update.get("research_route")
            and self._new_research_asked(state, text)
            and not any(update.get(flag) for flag in flags[1:])
        ):
            return True  # le coach tient la fiche et propose la recherche (D-82)
        return update["intent"]["intent"] == "information_projet" and not any(
            update.get(flag) for flag in flags
        )

    def _route_update(
        self, state: dict[str, Any], text: str, intent: IntentResult, ctx: AgentContext
    ) -> dict[str, Any]:
        status = (state.get("snapshot") or {}).get("project", {}).get("status")
        if PREFERENCE_REQUEST.search(text.lower()) and intent.intent in ("aide", "autre"):
            intent = intent.model_copy(update={"intent": "preferences"})
        if intent.intent == "hors_perimetre" and self._asks_about_results(state, text):
            intent = intent.model_copy(update={"intent": "autre"})
        if intent.intent == "hors_perimetre" and self._states_own_budget(text):
            # D-82 : dire ce qu'on peut investir dans son projet n'est pas demander un conseil
            # financier (recettes du 11 et du 12/11/2026 : budget classe hors perimetre).
            intent = intent.model_copy(update={"intent": "information_projet"})
        active = status == "active"
        if (
            active
            and NEXT_QUERY.search(text.lower())
            and intent.intent in ("aide", "autre", "demande_plan", "information_projet")
        ):
            # « Et maintenant ? » : la prochaine tache, pas un nouveau plan (constat campagne 2).
            intent = intent.model_copy(update={"intent": "etat_projet"})
        elif (
            active
            and REPLAN_REQUEST.search(text.lower())
            and intent.intent
            in ("aide", "autre", "demande_plan", "etat_projet", "information_projet")
        ):
            # Retard ou demande d'allegement : une proposition plus petite, jamais appliquee
            # sans clic (constat de la validation D-58).
            intent = intent.model_copy(update={"intent": "replanifier"})
        update = {"intent": intent.model_dump(mode="json")}
        then = intent.then_intent
        if then in FOLLOWUP_INTENTS and then != intent.intent and intent.intent in FIRST_INTENTS:
            update["followup"] = {"intent": then}
        update.update(
            self._research_route(state, text, intent.intent, status, ctx.user_id, ctx.project_id)
        )
        no_plan = status == "draft" and not (state.get("snapshot") or {}).get("tasks")
        if no_plan and intent.intent in COACHED_WITHOUT_PLAN and not update.get("research_route"):
            # D-78 : sur un projet sans plan, toute conversation (idee, question, demande
            # d'aide ou de plan, correction) va au coach : la reponse est ecrite par le modele.
            # Seuls restent deterministes : hors perimetre, preferences, statut d'une tache.
            coached = intent.model_copy(update={"intent": "information_projet"})
            update["intent"] = coached.model_dump(mode="json")
        return update

    @staticmethod
    def _states_own_budget(text: str) -> bool:
        lower = text.lower()
        return bool(OWN_BUDGET.search(lower)) and not SENSITIVE_ADVICE.search(lower)

    @staticmethod
    def _asks_about_results(state: dict[str, Any], text: str) -> bool:
        """Question sur les idees ou solutions deja trouvees (« laquelle de ces solutions, avec
        mon budget ? ») : un choix d'organisation, pas un conseil financier personnalise."""
        lower = text.lower()
        done = (state.get("research_flow") or {}).get("stage") == "done"
        return done and bool(RESULT_QUESTION.search(lower)) and not SENSITIVE_ADVICE.search(lower)

    def _is_research_command(self, state: dict[str, Any], text: str, ctx: AgentContext) -> bool:
        if len(text.split()) > 8 or not RESEARCH_COMMAND.match(text.strip().lower()):
            return False
        flow = state.get("research_flow") or {}
        if flow.get("stage") == "done":
            return True
        research = self.app.research
        return (
            research.project_analysis(ctx.user_id, ctx.project_id) is not None
            or research.project_solutions(ctx.user_id, ctx.project_id) is not None
        )

    # --- recherche (R3, D-70) : detection par le code, proposition sans appel externe ---------
    def _research_route(
        self,
        state: dict[str, Any],
        text: str,
        intent: str,
        status: str | None,
        user_id: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        flow = state.get("research_flow") or {}
        stage = flow.get("stage")
        if (
            status == "draft"
            and intent == "demande_plan"
            and not (state.get("snapshot") or {}).get("tasks")
        ):
            # « Prépare mon plan à partir de ces résultats » (classe demande_plan par le modele)
            # demande le plan, avec les constats de la recherche, pas une nouvelle analyse.
            return {}
        # Reponse a une question de recherche : une liste d'idees, un critere ou un marche.
        # « Investir peu » ou « un revenu » ne sont pas une demande de conseil financier :
        # pour un critere ou un marche, la classification hors perimetre ne l'emporte pas.
        answering = {"aide", "autre", "information_projet"}
        if stage in ("collect_criteria", "collect_market"):
            answering = answering | {"hors_perimetre"}
        collecting = stage in ("collect_ideas", "collect_criteria", "collect_market") and (
            intent in answering
        )
        lower = text.lower()
        # R6 : « ajoute ces actions a mon plan » est souvent classe « ajouter une tache » ; une
        # proposition de taches a confirmer est construite a partir des solutions validees.
        if (
            user_id
            and project_id
            and TO_TASKS.search(lower)
            and intent in RESEARCH_ELIGIBLE | {"ajouter_tache", "replanifier"}
            and self.app.research.project_solutions(user_id, project_id) is not None
        ):
            return {"research_tasks": True}
        if intent not in RESEARCH_ELIGIBLE and not collecting:
            return {}
        solved = stage == "done" and flow.get("kind") == "solutions"
        if (
            solved
            and intent != "etat_projet"  # « Ou en suis-je ? » reste l'etat du projet
            and (ANALYZE.search(lower) or FOLLOWUP.search(lower))
            and not SOLVE.search(lower)
        ):
            # Questions sur les solutions trouvees : reponse appuyee sur elles.
            return {"research_followup": True}
        if (
            user_id
            and project_id
            and SOLVE.search(lower)
            and self.app.research.project_analysis(user_id, project_id) is not None
        ):
            return {"research_solve": True}
        topical = detect_research_need(text)
        if (
            stage == "done"
            and (
                FOLLOWUP.search(lower)
                or ANALYZE.search(lower)
                or (topical is not None and topical.kind == "topic")
            )
            and not parse_ideas(text)
            and not EXPLICIT.search(lower)
        ):
            # Apres une recherche, une question de concurrence, de prix ou de risques porte sur
            # ses resultats ; une NOUVELLE recherche se demande explicitement (« fais une
            # recherche… »).
            # R4 : la premiere demande (ou une demande explicite de mise a jour) produit
            # l'analyse ; ensuite, les questions sont traitees avec l'analyse en memoire.
            analysed = (
                self.app.research.latest_analysis(user_id, flow["mission_id"])
                if flow.get("mission_id") and user_id
                else None
            )
            incomplete = analysed is not None and not all(i.available for i in analysed.ideas)
            # Recette du 10/11/2026 : une analyse incomplete (panne, reponse tronquee) est
            # refaite a la demande d'analyse suivante, pas resservie.
            # D-80 : l'analyse est faite des l'approbation ; « analyse » (commande courte)
            # la montre de nouveau (sans appel si les sources n'ont pas change).
            command = len(text.split()) <= 8 and bool(RESEARCH_COMMAND.match(text.strip().lower()))
            if (
                analysed is None
                or REDO.search(lower)
                or (ANALYZE.search(lower) and (incomplete or command))
            ):
                return {"research_analyze": True}
            return {"research_followup": True}
        need = detect_research_need(text)
        if need is not None or collecting:
            payload = None
            if need is not None:
                payload = {
                    "kind": need.kind,
                    "categories": [c.value for c in need.categories],
                    "count": need.count,
                }
            return {"research_route": True, "research_need": payload}
        return {}

    def research(self, state: dict[str, Any], runtime: Runtime[AgentContext]) -> dict:
        """Recueille l'indispensable (idees, criteres, marche) puis PROPOSE une mission.
        Aucune approbation, aucun appel externe : la mission attend le clic de l'utilisateur."""
        context = require_context(runtime)
        service = self.app.research
        text = _last_human_text(state.get("messages", []))
        previous = state.get("research_flow") or {}
        if not service.availability()["enabled"]:
            return {"last_result": {"kind": "text", "text": NOT_ENABLED}, "research_flow": None}
        if re.search(r"\b(annule|laisse tomber|oublie|pas de recherche)\b", text.lower()):
            self._cancel_proposed(previous, context)
            return {"last_result": {"kind": "text", "text": CANCELLED}, "research_flow": None}
        need = state.get("research_need")
        stage = previous.get("stage")
        flow = dict(previous)
        if stage == "collect_ideas":
            ideas = parse_ideas(text)
            if ideas:
                flow["ideas"] = ideas
            elif SKIP.search(text.lower()) or "ideas_reminded" in flow.get("asked", []):
                return {
                    "last_result": {
                        "kind": "text",
                        "text": "D'accord. Dites-moi quand vous voulez comparer vos idées.",
                    },
                    "research_flow": None,
                }
            else:
                flow["asked"] = [*flow.get("asked", []), "ideas_reminded"]
                question = (
                    "Je n'ai pas reconnu de liste : écrivez une idée par ligne, s'il vous plaît."
                )
                return {"last_result": {"kind": "question", "text": question},
                        "research_flow": flow}  # fmt: skip
        elif stage == "collect_criteria":
            flow["criteria"] = (
                [] if SKIP.search(text.lower()) else known_criteria([text]) or [text[:120]]
            )
        elif stage == "collect_market":
            # D-80 : zone reconnue dans la reponse, sinon comprise par le modele (fiche de
            # recherche) ; « international » seulement si rien n'est dit.
            flow["markets"] = market_from_answer(text) or []
            flow["market_answered"] = True
        if need is not None and stage not in ("collect_ideas", "collect_criteria",
                                              "collect_market"):  # fmt: skip
            # Nouvelle demande : on garde en memoire ce que l'utilisateur a deja dit.
            relaunch = need["kind"] == "explicit" and previous.get("ideas")
            flow = {
                "kind": "compare" if relaunch else need["kind"],
                "categories": previous.get("categories") if relaunch else need["categories"],
                "expected": need.get("count"),
                "ideas": previous.get("ideas") if relaunch or need["kind"] == "compare" else [],
                "markets": previous.get("markets"),
                "criteria": previous.get("criteria"),
                "asked": [],
                "mission_id": previous.get("mission_id"),
            }
            if flow["kind"] == "compare":
                flow["ideas"] = parse_ideas(text) or flow["ideas"] or self._ideas_in_history(state)
        return self._next_research_step(state, context, flow)

    def analyze(self, state: dict[str, Any], runtime: Runtime[AgentContext]) -> dict:
        """R4 : analyse des sources deja collectees par le modele de strategie, validee par le
        code. Aucune nouvelle recherche, aucune ecriture dans le projet ni le plan."""
        context = require_context(runtime)
        flow = dict(state.get("research_flow") or {})
        mission_id = flow.get("mission_id")
        if not mission_id:
            return {"last_result": {"kind": "text", "text": "Il n'y a pas encore de recherche "
                                    "à analyser."}}  # fmt: skip
        text = _last_human_text(state.get("messages", []))
        try:
            analysis = self.app.research.analyze_mission(
                context.user_id,
                mission_id,
                LLMResearchAnalyst(self.llm),
                context_texts=_user_texts(state),
                force=bool(REDO.search(text.lower())),
            )
            report = self.app.research.mission_report(context.user_id, mission_id)
        except DomainError as exc:
            return {"error": _error(exc)}
        flow["analysis_id"] = analysis.id
        return {
            "last_result": {
                "kind": "report",
                "text": (
                    research_conclusion(
                        self.llm,
                        analysis,
                        report.sources,
                        ProjectBrief(**(state.get("brief_draft") or {})),
                        _user_texts(state),
                    )
                    + f"\n\n{DETAILS_MARKER}\n\n"
                    + format_analysis(analysis, report.sources, log=False)
                ),
            },
            "research_flow": flow,
        }

    def solutions(self, state: dict[str, Any], runtime: Runtime[AgentContext]) -> dict:
        """R6 : propose UNE mission de recherche de solutions pour les problemes les mieux
        etayes de l'analyse. Rien n'est envoye avant le clic « Approuver et lancer »."""
        context = require_context(runtime)
        found = self.app.research.project_analysis(context.user_id, context.project_id)
        problems = select_problems(found[0]) if found else []
        if not problems:
            return {"last_result": {"kind": "text", "text": NO_PROBLEMS}}
        flow = dict(state.get("research_flow") or {})
        request = MissionRequest(
            project_ids=[context.project_id],
            problems=problems,
            context_texts=[t[:2000] for t in _user_texts(state)][-40:],
        )
        try:
            self._cancel_proposed(flow, context)
            mission = self.app.research.propose_mission(context.user_id, request)
        except DomainError as exc:
            return {"error": _error(exc)}
        flow.update(stage="proposed", kind="solutions", mission_id=mission.id)
        return {
            "last_result": {"kind": "text", "text": proposal_message(mission, SOLUTIONS_INTRO)},
            "research_flow": flow,
        }

    def solution_tasks(self, state: dict[str, Any], runtime: Runtime[AgentContext]) -> dict:
        """R6 : les actions recommandees deviennent une PROPOSITION (plan ou ajout de taches),
        confirmee ou annulee par les boutons habituels. Rien n'est ecrit ici."""
        context = require_context(runtime)
        found = self.app.research.project_solutions(context.user_id, context.project_id)
        actions = found[0].all_actions() if found else []
        if not actions:
            return {"last_result": {"kind": "text", "text": NO_ACTIONS}}
        unique: dict[str, tuple[str, Any]] = {}
        for label, action in actions:
            # Une meme action proposee pour plusieurs problemes ne devient qu'une tache.
            unique.setdefault(action.title.casefold(), (label, action))
        chosen = list(unique.values())[:7]  # une phase contient au plus 7 taches
        status = ((state.get("snapshot") or {}).get("project") or {}).get("status")
        if status == "active":
            snapshot = self.app.coach.get_snapshot(context.user_id, context.project_id)
            proposal = ChangeProposal(
                changes=[
                    ProposedChange(
                        op="add",
                        phase_title=TASKS_PHASE,
                        fields=ProposedFields(
                            title=action.title,
                            acceptance_criteria=action.done_when,
                            estimate_minutes=action.estimate_minutes,
                            description=f"Solution au problème : {label}"[:1000],
                        ),
                    )
                    for label, action in chosen
                ],
                rationale="Actions issues de la recherche de solutions, à confirmer.",
            )
            try:
                action_type, command = proposal_to_command(snapshot, proposal, replan=False)
            except DomainError as exc:
                return {"error": _error(exc)}
            return {"proposal": {"kind": "change", "action_type": action_type.value,
                                 "command": command.model_dump(mode="json"),
                                 "rationale": proposal.rationale}}  # fmt: skip
        labels = list(dict.fromkeys(label for label, _ in chosen))
        draft = PlanDraft(
            objective=("Résoudre : " + " ; ".join(labels))[:200],
            phases=[PlanPhaseDraft(title=TASKS_PHASE, tasks=[
                PlanTaskDraft(key=f"solution{n}", title=action.title,
                              acceptance_criteria=action.done_when,
                              estimate_minutes=action.estimate_minutes,
                              description=f"Solution au problème : {label}"[:1000])
                for n, (label, action) in enumerate(chosen, 1)
            ])],
        )  # fmt: skip
        return {"proposal": {"kind": "plan", "draft": draft.model_dump(mode="json"),
                             "brief": BriefUpdate().model_dump(mode="json")}}  # fmt: skip

    def _research_spec(
        self, state: dict[str, Any], flow: dict[str, Any], categories: list[ResearchCategory]
    ) -> ResearchSpec:
        notify = PROGRESS.get()
        if notify is not None:
            notify("Préparation de la proposition de recherche…")
        facts = self._facts(state)
        facts["recherche_demandee"] = {
            "categories": [c.value for c in categories],
            "marche_connu": flow.get("markets"),
        }
        text = _last_human_text(state.get("messages", []))
        messages = build_messages("research_spec", text=text, facts=facts)
        return self.llm.generate_structured("research_spec", messages, ResearchSpec)

    def _ideas_in_history(self, state: dict[str, Any]) -> list[str]:
        for message in reversed(state.get("messages", [])[:-1]):
            if isinstance(message, HumanMessage):
                ideas = parse_ideas(str(message.content))
                if ideas:
                    return ideas
        return []

    def _cancel_proposed(self, flow: dict[str, Any], context: AgentContext) -> None:
        mission_id = flow.get("mission_id")
        if not mission_id:
            return
        try:
            mission = self.app.research.list_missions(context.user_id, context.project_id)
            if any(m.id == mission_id and m.status is MissionStatus.PROPOSED for m in mission):
                self.app.research.cancel_mission(context.user_id, mission_id)
        except DomainError:
            pass

    def _next_research_step(
        self, state: dict[str, Any], context: AgentContext, flow: dict[str, Any]
    ) -> dict:
        asked = list(flow.get("asked") or [])
        texts = _user_texts(state)
        project = (state.get("snapshot") or {}).get("project") or {}
        compare = flow.get("kind") == "compare"
        ideas = flow.get("ideas") or []
        if compare and len(ideas) < 2:
            count = flow.get("expected")
            question = ASK_IDEAS.format(n=count) if count else ASK_IDEAS_UNKNOWN
            flow.update(stage="collect_ideas", asked=[*asked, "ideas"])
            return {"last_result": {"kind": "question", "text": question}, "research_flow": flow}
        known = (
            flow.get("criteria") is not None
            or known_criteria(texts)
            or project.get("target_outcome")
            or project.get("constraints")
        )
        if compare and not known and "criteria" not in asked:
            flow.update(stage="collect_criteria", asked=[*asked, "criteria"])
            return {"last_result": {"kind": "question", "text": ASK_CRITERIA},
                    "research_flow": flow}  # fmt: skip
        criteria = flow.get("criteria") or known_criteria(texts)
        categories = [ResearchCategory(c) for c in flow.get("categories") or []]
        spec = None
        if not compare:
            # D-80 : le perimetre (sujet precis, cible, zone, requetes) est redige par le
            # modele a partir de toute la conversation, jamais deduit du titre du projet.
            try:
                spec = self._research_spec(state, flow, categories or list(PREP_CATEGORIES))
            except DomainError as exc:
                return {"error": _error(exc), "research_flow": None}
            if spec.market and not flow.get("markets"):
                flow["markets"] = spec_markets(spec.market)
        objective = None
        if compare:
            objective = (
                f"Comparer vos {len(ideas)} idées"
                + (f" selon : {', '.join(criteria)}" if criteria else "")
                + " (demande, concurrents, prix, avis clients et risques)"
            )[:300]
        request = MissionRequest(
            project_ids=[context.project_id],
            ideas=ideas if compare else [],
            categories=categories,
            markets=flow.get("markets") or [],
            context_texts=[t[:2000] for t in texts][-40:],
            objective=objective,
            **(spec_request(spec) if spec is not None else {}),
        )
        try:
            draft = self.app.research.prepare_mission(context.user_id, request)
            if draft.question:
                if "market" in asked or flow.get("market_answered"):
                    request = request.model_copy(update={"markets": ["international"]})
                else:
                    flow.update(stage="collect_market", asked=[*asked, "market"])
                    return {
                        "last_result": {"kind": "question",
                                        "text": draft.question + ASK_MARKET_SUFFIX},
                        "research_flow": flow,
                    }  # fmt: skip
            self._cancel_proposed(flow, context)  # une seule proposition de recherche a la fois
            mission = self.app.research.propose_mission(context.user_id, request)
        except DomainError as exc:
            return {"error": _error(exc), "research_flow": None}
        flow.update(stage="proposed", mission_id=mission.id, asked=asked,
                    markets=mission.scope.markets or flow.get("markets"),
                    criteria=criteria, categories=[c.value for c in categories])  # fmt: skip
        labels = ", ".join(CATEGORY_LABELS[c] for c in categories)
        intro = f"{PROPOSAL_INTRO} :" if compare else f"{PROPOSAL_INTRO} ({labels}) :"
        return {
            "last_result": {"kind": "text", "text": proposal_message(mission, intro)},
            "research_flow": flow,
        }

    def clarify(self, state: dict[str, Any], runtime: Runtime[AgentContext]) -> dict:
        """Interprète, valide la décision, puis formule les tours de conseil."""
        context = require_context(runtime)
        text = _last_human_text(state.get("messages", []))
        greeting = SOCIAL_GREETING.fullmatch(text.strip())
        if greeting and any(char.isalpha() for char in text):
            reply = (
                "Ça va bien, merci ! Et vous ?"
                if greeting["check_in"].strip()
                else "Bonjour ! Comment allez-vous ?"
            )
            return {"messages": [AIMessage(content=reply)], "last_result": {"kind": "coach_done"}}
        previous = ProjectBrief(**(state.get("brief_draft") or {}))
        known = self._known(state)
        facts = self._facts(state)
        reply_facts = self._reply_facts(state, context, facts)
        reply_facts["preparation_du_plan"] = {
            "informations_manquantes": [
                PLAN_PREREQUISITES[name] for name in facts["brief"]["missing"]
            ],
            "deja_proposee": state.get("plan_offered") is not None,
            # D-82 : elle a demande un changement de la proposition precedente.
            "modification_demandee": bool(state.get("plan_change_requested")),
        }
        reply_facts["decouverte"] = discovery_status(
            previous, known, facts.get("sujet"), state.get("questions_asked")
        )
        topics_asked = state.get("discovery_topics_asked") or []
        reply_facts["sujets_a_explorer"] = self._discovery_topics(previous, known, topics_asked)
        # D-86 (campagne reelle V1) : tout etait connu, le modele a garde « decouverte » et lui
        # a demande de choisir elle-meme son offre. L'etape attendue est calculee par le code.
        discovery = reply_facts["decouverte"]
        discovery["etape_conseillee"] = (
            "idee_precise"
            if discovery["idee_retenue"]
            else ("pistes" if discovery["assez_pour_des_pistes"] else "decouverte")
        )
        reply_facts["recherche_disponible"] = self._research_offer()
        evidence = self._research_evidence(context)
        if evidence:
            reply_facts["preparation_du_plan"]["niveau_de_preuve_recherche"] = evidence
        allow_abort = bool(state.get("coach_direct")) and not state.get("reclassify")
        try:
            assessment = self.llm.generate_structured(
                "coach_assessment",
                build_messages("coach_assessment", text=text, facts=reply_facts),
                CoachAssessment,
            )
        except DomainError as exc:
            return {"error": _error(exc)}
        if allow_abort and not self._coached(state, text, assessment.intent, context):
            intent = assessment.intent
            if intent == "preferences" and not PREFERENCE_REQUEST.search(text.lower()):
                intent = "information_projet"
            route = self._route_update(state, text, IntentResult(intent=intent), context)
            if route["intent"]["intent"] in {
                "preferences",
                "hors_perimetre",
                "pause_projet",
                "reprendre_projet",
                "changer_statut",
            } or any(
                route.get(flag) for flag in ("research_tasks", "research_solve", "research_analyze")
            ):
                return {
                    "reclassify": intent if intent in DIRECT_INTENTS else "classify",
                    "coach_direct": None,
                }
        turn = CoachTurn.model_validate(
            assessment.model_dump(
                exclude={
                    "research_requested",
                    "next_move",
                    "response_goal",
                    "physical_incident",
                    "plan_request_quote",
                    "discovery_topic",
                    "practice_quotes",
                    "concrete_practice",
                    "solo_test_requested",
                    "commercial_test_requested",
                    "scope_adjustment_requested",
                    "wants_guidance",
                }
            )
        )
        quote = assessment.plan_request_quote.strip().casefold()
        if turn.plan_requested:
            explicit = bool(
                re.search(
                    r"\bplan\b|étape par étape|marche à suivre|"
                    r"exactement comment (?:lancer|démarrer)",
                    quote,
                )
            )
            previous_offer = bool(
                re.search(r"\bplan\b", _last_ai_text(state.get("messages", [])) or "", re.I)
            )
            if not (quote and quote in text.casefold() and (explicit or previous_offer)):
                turn = turn.model_copy(update={"plan_requested": False})
        new = brief_from_turn(turn)
        merged = clean_brief(merge_brief(previous, new, cumulative=True), _user_texts(state))
        user_messages = [
            str(message.content)
            for message in state.get("messages", [])
            if isinstance(message, HumanMessage)
        ]
        merged = ground_profile(merged, previous, user_messages)
        if assessment.research_requested:
            merged = merged.model_copy(update={"research_declined": False})
        updated_state = {**state, "brief_draft": merged.model_dump(mode="json")}
        current = self._facts(updated_state)
        discovery = discovery_status(merged, known, current["sujet"], state.get("questions_asked"))
        if turn.stage == "decouverte":
            stage = (
                "idee_precise"
                if discovery["idee_retenue"]
                else ("pistes" if discovery["assez_pour_des_pistes"] else "decouverte")
            )
            turn = turn.model_copy(update={"stage": stage})
        elif turn.stage == "pistes" and not (
            discovery["assez_pour_des_pistes"] or turn.ideas_requested
        ):
            turn = turn.model_copy(update={"stage": "decouverte"})
        if turn.next_step == "preparer_recherche" and not assessment.research_requested:
            turn = turn.model_copy(update={"next_step": "conseiller"})
        decision = self._check_decision(
            updated_state,
            turn,
            merged,
            known,
            current["sujet"],
            evidence=evidence,
            text=text,
            research_requested=assessment.research_requested,
        )
        response_goal = assessment.response_goal
        practice_quotes = [
            quote
            for quote in assessment.practice_quotes
            if _quote_key(quote)
            and any(_quote_key(quote) in _quote_key(message) for message in user_messages)
        ]
        practice = bool(practice_quotes)
        if turn.ideas_requested and response_goal in ("clarifier", "repondre"):
            response_goal = "recommander"
        if assessment.wants_guidance and response_goal in ("clarifier", "repondre"):
            response_goal = "recommander"
        if (
            not practice
            and len(user_messages) == 1
            and not discovery["idee_retenue"]
            and turn.stage == "decouverte"
            and not assessment.wants_guidance
        ):
            response_goal = "clarifier"
        if (
            response_goal == "recommander"
            and not practice
            and not discovery["idee_retenue"]
            and not (assessment.wants_guidance or turn.ideas_requested)
        ):
            response_goal = "clarifier"
            turn = turn.model_copy(update={"stage": "decouverte"})
        elif (
            practice
            and response_goal == "clarifier"
            and not discovery["idee_retenue"]
            and assessment.discovery_topic == "marche"
        ):
            response_goal = "recommander"
        if response_goal == "recommander" and not (
            assessment.wants_guidance
            or turn.ideas_requested
            or discovery["idee_retenue"]
            or discovery["assez_pour_des_pistes"]
        ):
            response_goal = "clarifier"
        last_offer = state.get("last_verified_offer")
        if (
            response_goal == "recommander"
            and last_offer
            and not assessment.wants_guidance
            and not turn.ideas_requested
        ):
            response_goal = "repondre"
        if (
            turn.stage == "conseil_immediat"
            and not turn.ideas_requested
            and response_goal == "clarifier"
        ):
            response_goal = "repondre"
        if (
            response_goal == "recommander"
            and turn.stage == "decouverte"
            and (turn.ideas_requested or practice or assessment.wants_guidance)
        ):
            turn = turn.model_copy(update={"stage": "pistes"})
        if turn.stage == "decouverte" and response_goal == "recommander":
            response_goal = "clarifier"
        if assessment.solo_test_requested:
            response_goal = "recommander"
        commercial_test = assessment.commercial_test_requested and len(user_messages) > 1
        scope_adjustment = assessment.scope_adjustment_requested and len(user_messages) > 1
        direct_next_action = commercial_test or scope_adjustment
        if direct_next_action:
            response_goal = "repondre"
        reply_facts.update(
            current,
            decouverte=discovery,
            etape_du_tour=turn.stage,
            decision_du_tour=decision,
            jugement_propose=assessment.next_move,
            demande_du_tour=assessment.intent,
            objectif_reponse=response_goal,
            pratiques_citees=practice_quotes,
            derniere_offre_verifiee=last_offer,
            essai_autonome=assessment.solo_test_requested,
            essai_commercial=commercial_test,
            ajustement_perimetre=scope_adjustment,
        )
        topics = self._discovery_topics(merged, known, topics_asked)
        topic = assessment.discovery_topic if assessment.discovery_topic in topics else None
        if not practice and "competence" in topics:
            topic = "competence"
        topic = topic or next(iter(topics), None)
        if response_goal == "clarifier":
            reply_facts["sujet_de_la_question"] = topics.get(topic)
            if topic is None:
                reply_facts["objectif_reponse"] = "repondre"
        update: dict[str, Any] = {
            "brief_draft": updated_state["brief_draft"],
            "last_result": {"kind": "coach_done"},
        }
        contract: list[str] = []
        if assessment.physical_incident and not turn.plan_requested:
            decision.update(applied="conseiller", notice=None)
            update["messages"] = [
                AIMessage(
                    content=(
                        "Mettez le prototype de côté. Ne l'utilisez plus et ne le vendez pas "
                        "tant que la cause n'a pas été vérifiée. Conservez les références des "
                        "composants et vos observations pour faire vérifier le problème avant "
                        "tout nouvel essai."
                    )
                )
            ]
        elif decision["applied"] == "conseiller":
            try:
                if response_goal == "recommander":
                    response, offer_status = self._grounded_offer(
                        text,
                        reply_facts,
                        user_messages,
                        concrete_practice=practice and assessment.concrete_practice,
                    )
                    decision["offer_status"] = offer_status
                else:
                    response = self.llm.generate_structured(
                        "coach_response",
                        build_messages("coach_response", text=text, facts=reply_facts),
                        CoachResponse,
                    )
                    if (
                        response.recommends_offer
                        and not direct_next_action
                        and (practice or discovery["idee_retenue"])
                    ):
                        response, offer_status = self._grounded_offer(
                            text,
                            reply_facts,
                            user_messages,
                            concrete_practice=practice and assessment.concrete_practice,
                        )
                        decision["offer_status"] = offer_status
                    elif response.recommends_offer and not direct_next_action:
                        response = CoachResponse(
                            question=response.question
                            if response_goal == "clarifier"
                            else ("Quelle tâche savez-vous déjà réaliser ?")
                        )
            except DomainError as exc:
                return {"error": _error(exc)}
            turn = turn.model_copy(update=response.model_dump(exclude={"recommends_offer"}))
            if (
                direct_next_action
                or response_goal == "livrer_un_texte"
                or (response_goal == "clarifier" and not topic)
            ):
                turn = turn.model_copy(update={"question": ""})
            elif response_goal == "clarifier" and topic == "temps" and turn.question:
                turn = turn.model_copy(
                    update={"question": "Combien de temps pouvez-vous y consacrer par semaine ?"}
                )
            if (
                response_goal == "clarifier"
                and len(user_messages) == 1
                and not practice
                and not re.match(r"(?:bonjour|bonsoir|salut|coucou|hello)\b", text, re.I)
            ):
                turn = turn.model_copy(update={"reply": ""})
            if repeated_question(turn.question, state.get("questions_asked") or []):
                turn = turn.model_copy(update={"question": ""})
                contract.append("question_repetee_retiree")
            if decision.get("offer_status") == "verified":
                turn = turn.model_copy(update={"stage": "pistes"})
                update["last_verified_offer"] = response.reply
            elif decision.get("offer_status") == "exercise":
                turn = turn.model_copy(update={"stage": "conseil_immediat"})
            reply, text_contract = self._turn_text(
                turn,
                reply_facts,
                False,
                said=text,
                verified_offer=decision.get("offer_status") == "verified",
            )
            contract.extend(text_contract)
            if not reply and "question_repetee_retiree" in contract:
                reply = (
                    "Partons d'une tâche que vous faites déjà. Vous pouvez me raconter "
                    "un exemple tiré du quotidien, même si vous ne l'avez jamais vendu."
                )
            if not reply and response_goal == "clarifier":
                reply = (
                    "Partons d'un exemple de votre quotidien. Même une petite tâche "
                    "que vous faites régulièrement peut nous donner une piste."
                )
            if not reply:
                return {"error": _error(DomainError(ErrorCode.LLM_OUTPUT_INVALID))}
            update["messages"] = [AIMessage(content=reply)]
            displayed_question = reply.rsplit("\n\n", 1)[-1] if turn.question else ""
            if displayed_question.endswith("?"):
                turn = turn.model_copy(update={"question": displayed_question})
            else:
                turn = turn.model_copy(update={"question": ""})
            if response_goal == "clarifier" and topic and turn.question:
                update["discovery_topics_asked"] = [*topics_asked, topic]
        if new.idea_summary and (
            turn.plan_requested or (turn.stage == "idee_precise" and response_goal != "recommander")
        ):
            self.app.coach.update_idea(context.user_id, context.project_id, new.idea_summary)
        decision.update(
            stage=turn.stage,
            response_goal=response_goal,
            contract=contract,
            question=turn.question.strip()[:300],
        )
        if turn.question.strip():
            asked = [*(state.get("questions_asked") or []), turn.question.strip()[:300]]
            update["questions_asked"] = asked[-12:]
        update["coach_decision"] = decision
        if decision.get("notice"):
            update["last_result"] = {"kind": "coach_done", "notice": decision["notice"]}
        if decision["applied"] == "preparer_plan":
            update.update(
                last_result={"kind": "brief_complete"},
                plan_offered=decision["key"],
                plan_change_requested=None,
            )
        elif decision["applied"] == "preparer_recherche":
            update.update(
                research_route=True,
                research_need={
                    "kind": "topic",
                    "categories": decision.get("categories") or [c.value for c in PREP_CATEGORIES],
                    "count": None,
                },
            )
        return update

    @staticmethod
    def _discovery_topics(
        brief: ProjectBrief, known: KnownFacts, asked: list[str]
    ) -> dict[str, str]:
        values = {
            "competence": (brief.skills, "une chose concrète qu'elle sait déjà faire"),
            "experience": (
                brief.past_attempts,
                "une situation concrète dans laquelle elle a aidé quelqu'un",
            ),
            "objectif": (brief.target_outcome, "le premier résultat qu'elle souhaite"),
            "temps": (
                known.weekly_hours or known.daily_minutes or brief.available_minutes_per_day,
                "le temps disponible par semaine",
            ),
            "budget": (brief.budget or known.sources.get("budget"), "le budget de départ"),
            "marche": (brief.market or known.city, "la zone où elle souhaite commencer"),
        }
        return {
            key: label
            for key, (known_value, label) in values.items()
            if not known_value and key not in asked
        }

    def _grounded_offer(
        self, text: str, facts: dict[str, Any], user_texts: list[str], *, concrete_practice: bool
    ) -> tuple[CoachResponse, str]:
        sources = dict(enumerate(user_texts, start=1))
        offer_facts = {
            "paroles_utilisateur": sources,
            "contraintes": facts["brief"].get("constraints", []),
            "sujet": facts.get("sujet"),
            "offre_precedente": facts.get("derniere_offre_verifiee"),
            "pratique_concrete_confirmee": concrete_practice,
            "essai_autonome": facts.get("essai_autonome", False),
            "pratiques_citees": facts.get("pratiques_citees", []),
        }
        if not concrete_practice or not facts.get("pratiques_citees"):
            return CoachResponse(reply=self._independent_exercise()), "exercise"
        # Une seule proposition et au plus une vérification. Un refus de validation
        # ramène à un exercice autonome au lieu de régénérer l'offre en boucle.
        return self._offer_or_exercise(text, sources, offer_facts)

    def _offer_or_exercise(
        self, text: str, sources: dict[int, str], offer_facts: dict[str, Any]
    ) -> tuple[CoachResponse, str]:
        try:
            proposal = self.llm.generate_structured(
                "coach_offer",
                build_messages("coach_offer", text=text, facts=offer_facts),
                OfferProposal,
            )
            unsupported = [
                req.capability
                for req in proposal.requirements
                if not _quote_key(req.evidence)
                or _quote_key(req.evidence) not in _quote_key(sources.get(req.user_message, ""))
            ]
            if not proposal.requirements:
                unsupported.append("une pratique concrète pour livrer la prestation")
            if not all(
                value.strip()
                for value in (
                    proposal.offer,
                    proposal.customer,
                    proposal.deliverable,
                    proposal.pilot,
                )
            ):
                unsupported.append("décrire une prestation, son client et un test concret")
            visible = " ".join(
                (
                    proposal.offer,
                    proposal.deliverable,
                    proposal.rationale,
                    proposal.pilot,
                    proposal.question,
                )
            )
            if re.search(
                r"\bje (?:vous )?(?:livrerai|enverrai|renverrai|créerai|traiterai|fournis)\b|"
                r"\bj'appliquerai\b|\benvoyez-moi\b",
                visible,
                re.I,
            ):
                unsupported.append("faire exécuter le pilote par l'utilisateur")
            if not unsupported and not offer_facts["essai_autonome"]:
                review = self.llm.generate_structured(
                    "verify_offer",
                    build_messages(
                        "verify_offer",
                        text=text,
                        facts={
                            "paroles_utilisateur": sources,
                            "proposition": proposal.model_dump(),
                        },
                    ),
                    OfferReview,
                )
                if review.feasible and not review.relies_on_unconfirmed_technical_work:
                    customer = proposal.customer.strip()
                    customer = customer[:1].lower() + customer[1:]
                    return CoachResponse(
                        reply="\n\n".join(
                            filter(
                                None,
                                (
                                    f"Je commencerais avec {customer}"
                                    f" : {proposal.offer.strip().rstrip('.')}.",
                                    f"Livrable : {proposal.deliverable.strip().rstrip('.')}.",
                                    proposal.rationale,
                                    proposal.pilot,
                                ),
                            )
                        ),
                    ), "verified"
        except DomainError as exc:
            if exc.code not in (ErrorCode.LLM_OUTPUT_INVALID, ErrorCode.LLM_UNAVAILABLE):
                raise
            return CoachResponse(
                reply=self._independent_exercise(practices=offer_facts["pratiques_citees"])
            ), "exercise"
        return CoachResponse(
            reply=self._independent_exercise(proposal, sources, offer_facts["pratiques_citees"])
        ), "exercise"

    @staticmethod
    def _independent_exercise(
        proposal: OfferProposal | None = None,
        sources: dict[int, str] | None = None,
        practices: list[str] | None = None,
    ) -> str:
        if proposal and proposal.solo_exercise in ("simulate", "prepare"):
            subject = proposal.exercise_subject.strip().rstrip(".")
            output = proposal.exercise_output.strip().rstrip(".")
            if all(re.fullmatch(r"[^\n!?]{3,130}", value) for value in (subject, output)):
                if proposal.solo_exercise == "simulate":
                    requirement = proposal.exercise_requirement
                    action = proposal.exercise_action.strip().rstrip(".")
                    if (
                        requirement
                        and sources
                        and _quote_key(requirement.evidence)
                        and (
                            _quote_key(requirement.evidence)
                            in _quote_key(sources.get(requirement.user_message, ""))
                        )
                        and re.fullmatch(r"[^\n!?]{6,200}", action)
                    ):
                        return (
                            f"Prenez ce cas fictif : {subject}. {action}. "
                            f"À la fin, gardez {output[:1].lower() + output[1:]}."
                        )
                else:
                    return (
                        f"Voici un cas fictif à travailler chez vous. {subject}. "
                        "Dans votre brouillon, décrivez uniquement ce que vous savez déjà faire. "
                        f"À garder à la fin : {output[:1].lower() + output[1:]}."
                    )
        if practices:
            practice = practices[0].strip().rstrip(".")
            if re.fullmatch(r"[^\n!?]{6,145}", practice):
                return (
                    f"Partez de ce geste : « {practice} ». "
                    "Refaites-le une fois pour vous, avec ce que vous avez déjà et sans "
                    "données de tiers. Notez le résultat obtenu et ce qu'il faudrait "
                    "avoir sous la main pour refaire le même geste pour quelqu'un d'autre."
                )
        return (
            "Ce soir, choisissez une petite tâche que vous faites déjà au travail ou chez "
            "vous. Notez en trois lignes ce qui vous a été demandé, ce que vous avez fait "
            "et le résultat. Sans noms ni données privées. Ce sera votre point de départ "
            "pour choisir un service simple à tester."
        )

    @staticmethod
    def _turn_text(
        turn: CoachTurn,
        facts: dict[str, Any],
        streamed: bool,
        recorded: bool = False,
        said: str = "",
        verified_offer: bool = False,
    ) -> tuple[str, list[str]]:
        """D-81 : contrat du tour, verifie par le code (aucun texte ajoute).

        La question du tour est a part ; une question glissee dans la reponse est retiree.
        En decouverte, une reponse qui contient une liste (pistes, taches, consignes) ne
        respecte pas l'etape choisie par le modele lui-meme : seule sa question est gardee."""
        reply = localize_dates(keep_vouvoiement(turn.reply.strip()))
        question = localize_dates(keep_vouvoiement(turn.question.strip()))
        contract: list[str] = []
        if turn.stage == "decouverte":
            shorter = drop_example_lists(question)
            if shorter != question:
                question = shorter
                contract.append("exemples_retires_de_la_question")
        shorter = single_question(question)
        if shorter != question:
            question = shorter
            contract.append("question_double_coupee")
        if question:
            sentences = re.split(r"(?<=[.!?…])\s+", reply)
            body = " ".join(
                sentence
                for sentence in sentences
                if "?" not in sentence
                and not repeated_question(sentence, [question])
                and not re.match(
                    r"^(?:dites-moi|indiquez-moi|précisez-moi|pouvez-vous)\b",
                    sentence.strip(),
                    re.I,
                )
            )
            if body != reply:
                contract.append("question_dans_la_reponse")
            reply = body
        if turn.stage == "decouverte" and LIST_MARKERS.search(reply) and question:
            reply = ""
            contract.append("liste_en_decouverte")
        if turn.stage == "decouverte" and question and reply:
            # D-82 : en decouverte, une phrase au plus avant la question (conversation orale).
            short = first_sentence(reply)
            if short != reply:
                contract.append("reponse_raccourcie")
            reply = short
            if echoes(reply, said):
                # D-86 : une reformulation de son message n'apporte rien : seule la question
                # reste (aucun texte ajoute).
                reply = ""
                contract.append("reformulation_retiree")
        if SAVE_CLAIM.search(reply) and not recorded:
            reply = drop_save_claims(reply)
            contract.append("enregistrement_non_fait_retire")
        if (
            turn.stage == "pistes"
            and not verified_offer
            and not facts.get("decouverte", {}).get("assez_pour_des_pistes")
            and not turn.ideas_requested
        ):
            contract.append("pistes_avant_diagnostic_complet")
        if not streamed and not verified_offer and "«" not in reply:
            reply = shorten(reply, facts["preferences"]["response_length"])
        text = "\n\n".join(part for part in (reply, question) if part)
        if facts["preferences"].get("one_question_at_a_time", True):
            text = keep_one_question(text)  # PF-03 : preference de l'utilisateur
        return text, contract

    def _check_decision(
        self,
        state: dict[str, Any],
        turn: CoachTurn,
        brief: ProjectBrief,
        known: KnownFacts,
        subject: str | None,
        *,
        evidence: str | None = None,
        text: str = "",
        research_requested: bool = False,
    ) -> dict[str, Any]:
        """Preconditions verifiees par le code avant toute preparation couteuse.

        Un plan de l'initiative du coach exige l'idee, la disponibilite et le budget (connus ou
        refuses) et ne revient que si ces informations ont change ou si le projet a vraiment
        change ; un plan demande (meme provisoire) n'exige que l'idee. Une decision refusee
        est dite a l'utilisateur (avis factuel), jamais cachee ni remplacee par un conseil.
        """
        # D-83 : le changement decrit apres « Demander un changement » est une demande de
        # plan : elle a refuse la proposition pour la faire adapter, pas pour l'abandonner.
        # D-86 (campagne reelle V1) : le modele a repondu plan_change false a « Je ne veux pas
        # publier sur Facebook… Je préfère une affiche… ». Apres le clic, l'application vient de
        # demander ce qu'il faut changer : une affirmation de projet est ce changement ; une
        # question n'en est pas un.
        statement = (
            not text.strip().endswith("?")
            and len(text.split()) >= 4
            and turn.intent in ("information_projet", "demande_plan")
        )
        change = bool(state.get("plan_change_requested")) and (turn.plan_change or statement)
        chosen = "preparer_plan" if change else turn.next_step
        # D-84 : un changement reel du projet adapte un plan qu'elle a deja demande et qui
        # n'est pas encore enregistre ; sinon, un plan n'est prepare qu'a sa demande.
        requested = (turn.plan_requested and turn.intent == "demande_plan") or change
        result: dict[str, Any] = {"chosen": turn.next_step, "applied": "conseiller", "notice": None}
        if change:
            result["plan_change"] = True
        if chosen == "preparer_plan":
            missing = plan_missing(brief, known, brief.idea_summary or subject)
            key = plan_key(brief)
            result.update(missing=missing, key=key)
            blocking = ["idee"] if "idee" in missing else []
            if not requested and turn.stage in ("decouverte", "pistes"):  # D-81
                # D-81 : on ne planifie pas avant d'avoir compris la personne et choisi une
                # idee, sauf si elle le demande.
                result["notice"] = (
                    "Aucune proposition de plan n'a été préparée : nous n'avons pas encore "
                    "choisi votre idée ensemble."
                )
            elif not requested and brief.plan_declined:
                # D-80 : « ne construisez aucun plan » est respecte sur tous les chemins.
                result["notice"] = (
                    "Aucune proposition de plan n'a été préparée : vous avez demandé de ne pas "
                    "en construire pour l'instant."
                )
            elif not requested and evidence == "insuffisant":
                result["notice"] = (
                    "Aucune proposition de plan n'a été préparée : la dernière recherche ne "
                    "fournit pas de preuves suffisantes. Vous pouvez demander un plan provisoire."
                )
            elif not requested:
                # D-84 : le plan est prepare quand elle le souhaite (6/6 simulations validees :
                # le coach le propose par une question, un « oui » le declenche).
                result["notice"] = (
                    "Aucune proposition de plan n'a été préparée : je la prépare dès que vous "
                    "me la demandez."
                )
            elif blocking:
                result["notice"] = (
                    f"Aucune proposition de plan n'a été préparée : il manque encore "
                    f"{_labels(blocking)}. Vous pouvez aussi demander un plan provisoire."
                )
            else:
                result["applied"] = "preparer_plan"
        elif chosen == "preparer_recherche" and research_requested and not turn.research_declined:
            if RESEARCH_OFFER.search(turn.question):
                # D-86 (campagne reelle V1) : « Souhaitez-vous que je lance une vérification du
                # marché ? » et la carte de recherche dans le meme tour. La question est une
                # offre : la proposition attend sa reponse (sauf demande explicite ci-dessous).
                result["offre_de_recherche"] = True
            else:
                result["applied"] = "preparer_recherche"
        need = detect_research_need(text) if text else None
        if (
            need is not None
            and self._new_research_asked(state, text)
            and (research_requested or bool(EXPLICIT.search(text.lower())))
            # D-84 : une recherche demandee explicitement passe avant un changement de plan
            # suppose (recette dans l'interface : « Vérifiez d'abord le marché… » apres
            # « Demander un changement » donnait un plan) ; pas avant un plan demande.
            and not turn.plan_requested
            and not turn.research_declined
        ):
            # Une recherche demandee explicitement est toujours proposee (a approuver par un
            # clic), meme si le modele ne l'a pas choisie, et passe avant un plan qu'elle n'a
            # pas demande (recette de bout en bout : plan propose au lieu de la recherche
            # demandee) ; ses categories sont celles dites.
            result.update(applied="preparer_recherche", notice=None)
        if result["applied"] == "preparer_recherche":
            named = mentioned_categories(text)
            if need is not None:
                named = list(dict.fromkeys([*need.categories, *named]))
            result["categories"] = [c.value for c in named] or None
        return result

    def _research_offer(self) -> dict[str, Any]:
        """Ce que la recherche peut reellement consulter (D-80) : le coach ne promet jamais un
        site exclu ni un fournisseur absent."""
        availability = self.app.research.availability()
        offer: dict[str, Any] = {"active": bool(availability.get("enabled"))}
        if offer["active"]:
            offer["fournisseurs"] = list(self.app.research.registry.labels().values())
            offer["non_consultes"] = self.app.research.policy.excluded_labels()
        return offer

    def _research_evidence(self, context: AgentContext) -> str | None:
        """Niveau de preuve de la derniere analyse du projet (le plus faible des idees)."""
        found = self.app.research.project_analysis(context.user_id, context.project_id)
        if found is None:
            return None
        levels = [i.evidence for i in found[0].ideas if i.available and i.evidence != "inconnu"]
        order = {"insuffisant": 0, "partiel": 1, "suffisant": 2}
        return min(levels, key=order.__getitem__) if levels else None

    def _reply_facts(
        self, state: dict[str, Any], context: AgentContext, facts: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Contexte complet de la reponse : projet, fiche, faits connus, historique recent,
        plan et taches, et les resultats valides de la recherche (R3 a R6)."""
        facts = dict(facts or self._facts(state))
        found = self.app.research.project_analysis(context.user_id, context.project_id)
        if found is not None:
            # D-82 : apres l'analyse, le coach ne recoit que ses elements VALIDES (recette : des
            # prix d'audits de plusieurs jours, lus dans les extraits bruts, presentes comme
            # « preuves partielles de prix » alors que l'analyse n'en retenait aucun).
            facts["analyse"] = analysis_facts(*found)
        else:
            research = self.app.research.conversation_findings(context.user_id, context.project_id)
            if research:
                facts["research"] = research
        solved = self.app.research.project_solutions(context.user_id, context.project_id)
        if solved is not None:
            facts["solutions"] = solutions_facts(*solved)
        return facts

    def _model_reply(self, messages: list[Any], facts: dict[str, Any]) -> tuple[str, bool]:
        """Reponse du modele, diffusee si l'interface le demande. Une erreur remonte telle
        quelle : jamais de texte de secours presente comme une reponse du coach."""
        on_delta = STREAM.get()
        stream = getattr(self.llm, "stream_text", None)
        if on_delta is not None and stream is not None:
            text = stream("coach_reply", messages, on_delta)
            return drop_save_claims(localize_dates(keep_vouvoiement(text))) or text, True
        reply = localize_dates(keep_vouvoiement(self.llm.generate_text("coach_reply", messages)))
        reply = drop_save_claims(reply) or reply
        return shorten(reply, facts["preferences"]["response_length"]), False

    def draft_plan(self, state: dict[str, Any], runtime: Runtime[AgentContext]) -> dict:
        context = require_context(runtime)
        known = self._known(state)
        brief = ProjectBrief(**(state.get("brief_draft") or {}))
        missions = self.app.research.list_missions(context.user_id, context.project_id)
        evidence = self._research_evidence(context)
        provisional = not any(m.queries_used > 0 for m in missions) or evidence == "insuffisant"
        notify = PROGRESS.get()
        if notify is not None:
            notify("Préparation de la proposition de plan…")
        extra: dict[str, Any] = {"plan_provisoire": provisional}
        research = self.app.research.conversation_findings(context.user_id, context.project_id)
        if research:
            extra["research"] = research
        found = self.app.research.project_analysis(context.user_id, context.project_id)
        if found is not None:
            extra["analyse"] = analysis_facts(*found)
        facts = self._facts(state, **extra)
        missing = [m for m in facts["brief"]["missing"] if m != "idee"]
        facts["brief"] = {**brief.model_dump(mode="json"), "missing": []}
        # D-79 : un plan demande sans tout savoir avance avec des hypotheses signalees.
        if missing:
            facts["informations_manquantes"] = [PLAN_PREREQUISITES[m] for m in missing]
        if brief.skipped:
            facts["informations_non_fournies"] = [DECLINED_LABELS[m] for m in brief.skipped]
        if state.get("plan_previous"):
            facts["proposition_precedente"] = state["plan_previous"]
        if evidence:
            facts["niveau_de_preuve_recherche"] = evidence
        request = _last_human_text(state.get("messages", []))
        messages = build_messages("draft_plan", text=request, facts=facts)
        try:
            draft = self.llm.generate_structured("draft_plan", messages, PlanDraft)
        except DomainError as exc:
            return {"error": _error(exc)}
        session = known.daily_minutes
        weekly = int(known.weekly_hours * 60) if known.weekly_hours else None
        violations = co.plan_capacity_errors(draft, session=session, weekly=weekly)
        if violations:
            facts["plan_a_reviser"] = draft.model_dump(mode="json")
            facts["contraintes_non_respectees"] = violations
            try:
                draft = self.llm.generate_structured(
                    "draft_plan", build_messages("draft_plan", text=request, facts=facts), PlanDraft
                )
            except DomainError as exc:
                return {"error": _error(exc)}
            if co.plan_capacity_errors(draft, session=session, weekly=weekly):
                return {
                    "last_result": {
                        "kind": "text",
                        "text": (
                            "La proposition dépasse encore votre temps disponible. "
                            "Quelle partie du projet souhaitez-vous prioriser ?"
                        ),
                    }
                }
        draft = fit_plan(draft, None)
        if known.no_deadlines:
            # « Je ne veux pas de dates limites » : aucune echeance, meme si les preferences
            # les autorisent. L'objectif (« dans trois mois ») n'est pas une echeance de tache.
            draft = co.without_deadlines(draft)
        brief = clean_brief(brief, _user_texts(state))
        horizon = None
        if brief.horizon_days:
            horizon = self._today(context.user_id) + timedelta(days=brief.horizon_days)
        update = BriefUpdate(
            target_outcome=brief.target_outcome,
            constraints=brief.constraints,
            facts=brief.facts,
            assumptions=brief.assumptions,
            available_minutes_per_day=known.daily_minutes,
            horizon_date=horizon,
        )
        prefs = (state.get("snapshot") or {}).get("preferences") or {}
        return {
            "proposal": {
                "kind": "plan",
                "draft": draft.model_dump(mode="json"),
                "brief": update.model_dump(mode="json"),
                "provisional": provisional,
                "session_minutes": session,
                "no_deadlines": known.no_deadlines or not prefs.get("deadlines_enabled", False),
                "schedule": known.schedule,
                "budget_eur": known.budget_eur,
            },
            "prep_offer": None,
            "plan_previous": draft.model_dump(mode="json"),
        }

    def draft_change(self, state: dict[str, Any], runtime: Runtime[AgentContext]) -> dict:
        context = require_context(runtime)
        text = _last_human_text(state.get("messages", []))
        intent = (state.get("intent") or {}).get("intent")
        wants_date = intent == "modifier_tache" and DATE_REQUEST.search(text.lower()) is not None
        if wants_date and not state["snapshot"]["preferences"]["deadlines_enabled"]:
            # Echeances desactivees : le dire, sans appel au modele ni autre modification.
            return {"last_result": {"kind": "text", "text": DEADLINES_DISABLED_MESSAGE}}
        snapshot = self.app.coach.get_snapshot(context.user_id, context.project_id)
        facts = self._facts(state)
        if intent == "ajouter_tache":
            facts["dernier_message_du_coach"] = _last_ai_text(state.get("messages", []))
        # D-87 (campagne reelle V1) : le modele reecrivait des consignes qu'il ne voyait pas
        # (« fractionner en sessions ») et gardait des taches de 150 min pour 2 h par semaine.
        facts["instructions_actuelles"] = {
            task.ref: {"mode_d_emploi": task.description, "termine_quand": task.acceptance_criteria}
            for task in snapshot.ordered_tasks()
            if task.status is not TaskStatus.DONE
        }
        known = self._known(state)
        weekly = int(known.weekly_hours * 60) if known.weekly_hours else None
        session = known.daily_minutes or weekly
        if weekly is not None and session is not None:
            session = min(session, weekly)
        if session:
            facts["duree_max_par_tache"] = session
        catalog = [(task.id, task.number, task.title) for task in snapshot.tasks.values()]
        designated = designated_refs(text, catalog, _last_ai_text(state.get("messages", [])))
        targeted = intent in ("modifier_tache", "supprimer_tache") and not WHOLE_PLAN.search(
            text.lower()
        )
        overload = intent == "replanifier" and OVERLOAD.search(text.lower()) is not None
        deadlines = state["snapshot"]["preferences"]["deadlines_enabled"]
        try:
            for attempt in range(2):
                proposal = self.llm.generate_structured(
                    "draft_change",
                    build_messages("draft_change", text=text, facts=facts),
                    ChangeProposal,
                )
                proposal = keep_concrete_instructions(proposal, snapshot)
                if intent != "replanifier" or not proposal.changes:
                    break
                try:
                    _, preview_command = proposal_to_command(snapshot, proposal, replan=True)
                    preview = apply_command(snapshot, preview_command, now=self.app.clock.now())
                except DomainError as exc:
                    if attempt == 1:
                        raise
                    violations = [exc.user_message]
                else:
                    violations = co.revision_capacity_errors(snapshot, preview.snapshot, weekly)
                    violations.extend(tasks_over(proposal, snapshot, session))
                if not violations:
                    break
                if attempt == 1:
                    return {
                        "last_result": {
                            "kind": "question",
                            "text": (
                                "Je n'ai pas encore de version adaptée au temps disponible. "
                                "Quel résultat voulez-vous garder en priorité dans le plan allégé ?"
                            ),
                        }
                    }
                facts["revision_a_corriger"] = proposal.model_dump(mode="json")
                facts["contraintes_non_respectees"] = violations
            if wants_date and not any(c.fields.due_date for c in proposal.changes):
                # Une date demandee ne devient jamais une autre modification (dependance...).
                return {"last_result": {"kind": "text", "text": DATE_NOT_PROPOSED_MESSAGE}}
            if targeted and any(
                change.op != "add" and change.task_ref not in designated
                for change in proposal.changes
            ):
                # D-61 : une tache non designee par l'utilisateur n'est jamais supposee.
                question = change_question(intent, None, deadlines=deadlines)
                return {"last_result": {"kind": "question", "text": question}}
            if overload and not is_lightening(proposal.changes, state["snapshot"]["tasks"]):
                lighter = self._lighter_plan(state, snapshot)
                if lighter is not None:
                    return lighter
            if not proposal.changes:
                # Seules des consignes appauvries etaient proposees : rien a montrer.
                question = change_question(intent, None, deadlines=deadlines)
                return {"last_result": {"kind": "question", "text": question}}
            if intent == "ajouter_tache":
                if any(change.op != "add" for change in proposal.changes):
                    return {"last_result": {"kind": "question", "text": change_question(
                        intent, None, deadlines=deadlines
                    )}}  # fmt: skip
                if not snapshot.phases:
                    proposal = proposal.model_copy(
                        update={
                            "changes": [
                                change.model_copy(
                                    update={"phase_title": change.phase_title or "À faire"}
                                )
                                for change in proposal.changes
                            ]
                        }
                    )
            action_type, command = proposal_to_command(
                snapshot, proposal, replan=intent == "replanifier"
            )
            if known.no_deadlines:
                command = strip_deadlines(command)
        except DomainError as exc:
            unclear = bool(exc.data.get("unclear"))
            if overload and (unclear or exc.code is ErrorCode.LLM_OUTPUT_INVALID):
                # D-61 : surcharge et proposition vide ou invalide : allegement concret.
                lighter = self._lighter_plan(state, snapshot)
                if lighter is not None:
                    return lighter
            if unclear:
                # Correction R0 : une demande vide ou imprecise recoit une question simple,
                # jamais une erreur technique. Rien n'est propose ni ecrit. D-61 : la tache
                # n'est nommee que si l'utilisateur l'a designee.
                ref = exc.data.get("task_ref")
                question = change_question(
                    intent, ref if ref in designated else None, deadlines=deadlines
                )
                return {"last_result": {"kind": "question", "text": question}}
            return {"error": _error(exc)}
        return {
            "proposal": {
                "kind": "change",
                "action_type": action_type.value,
                "command": command.model_dump(mode="json"),
                "rationale": proposal.rationale,
            }
        }

    def _lighter_plan(self, state: dict[str, Any], snapshot: Any) -> dict | None:
        """Allegement deterministe (D-61) : la prochaine tache faisable, deja estimee a plus de
        10 minutes, ramenee a une etape de 10 minutes. Une proposition, jamais une ecriture."""
        facts = state["snapshot"]
        step = lighter_step(facts["tasks"], facts.get("next_actions") or [])
        if step is None:
            return None
        ref, _ = step
        new = 10
        proposal = ChangeProposal(
            changes=[
                ProposedChange(
                    op="update", task_ref=ref, fields=ProposedFields(estimate_minutes=new)
                )
            ],
            rationale=OVERLOAD_RATIONALE.format(new=new),
        )
        try:
            action_type, command = proposal_to_command(snapshot, proposal, replan=True)
        except DomainError:
            return None
        return {
            "proposal": {
                "kind": "change",
                "action_type": action_type.value,
                "command": command.model_dump(mode="json"),
                "rationale": proposal.rationale,
            }
        }

    # --- seul noeud qui cree une action en attente ------------------------------------
    def propose(self, state: dict[str, Any], runtime: Runtime[AgentContext]) -> dict:
        context = require_context(runtime)
        proposal = state["proposal"]
        actions = self.app.actions
        try:
            if proposal["kind"] == "plan":
                action = actions.request_plan(
                    context.user_id,
                    context.project_id,
                    PlanDraft.model_validate(proposal["draft"]),
                    BriefUpdate.model_validate(proposal["brief"]),
                )
            elif proposal["kind"] == "tasks_done":
                action = actions.request_tasks_done(
                    context.user_id, context.project_id, proposal["task_ids"]
                )
            elif proposal["kind"] == "pause":
                action = actions.request_pause(
                    context.user_id, context.project_id, proposal.get("note")
                )
            elif proposal["kind"] == "resume":
                action = actions.request_resume(context.user_id, context.project_id)
            else:
                action = actions.request_change(
                    context.user_id,
                    context.project_id,
                    ActionType(proposal["action_type"]),
                    ChangeCommand.model_validate(proposal["command"]),
                )
        except DomainError as exc:
            return {"error": _error(exc)}
        lines = describe_preview([Change(**change) for change in action.preview])
        details = ""
        body_lines = lines
        if proposal["kind"] == "plan":
            # Le detail par etape remplace la liste des creations (affichee dans la carte).
            body_lines = [line for line in lines if not line.startswith(PLAN_CREATION_LINES)]
            # D-84 : le temps est dit avec les mots de la personne (« environ 8 h par semaine »),
            # jamais une duree de seance deduite (recette : « 240 minutes par séance »).
            time = _time_text(ProjectBrief(**(state.get("brief_draft") or {})), self._known(state))
            if time:
                body_lines = [
                    f"Temps disponible : {time}" if line.startswith("Temps disponible :") else line
                    for line in body_lines
                ]
            # D-78 : la presentation vient du modele (summary) ; le code n'affiche que les
            # donnees de la proposition et la facon de la valider.
            draft = PlanDraft.model_validate(proposal["draft"])
            label = co.PROVISIONAL_LABEL if proposal.get("provisional") else co.PLAN_LABEL
            intro = f"{label}\n\n{draft.summary}" if draft.summary else label
            details = humanize_field_names(co.plan_details(draft))
            outro = co.PLAN_BUTTONS
        elif proposal["kind"] in STATE_TEXTS:
            intro, outro = STATE_TEXTS[proposal["kind"]]
        else:
            intro = "Je propose cette modification :"
            outro = (
                "Rien ne change tant que vous n'avez pas cliqué sur « Accepter les "
                "modifications ». Les tâches déjà terminées ne sont jamais modifiées."
            )
        body = "\n".join(f"- {line}" for line in body_lines)
        rationale = localize_dates(
            keep_vouvoiement(
                drop_technical(drop_questions(complete_sentences(proposal.get("rationale") or ""))),
                fallback="",
            )
        )
        if action.payload.get("deadlines_removed") and not (
            proposal["kind"] == "plan" and proposal.get("no_deadlines")
        ):
            # Pour un plan sans echeances, la ligne « Adapté à votre situation » le dit deja.
            # D-58 : retrait signale, jamais silencieux.
            rationale = (
                f"{rationale} Les échéances sont désactivées dans vos préférences : je les ai "
                "retirées de cette proposition."
            ).strip()
        # Ligne vide : en Markdown, une ligne collee a une liste rejoint son dernier element.
        text = (
            f"{intro}\n\n{body}\n\n{details + chr(10) * 2 if details else ''}"
            f"{rationale + ' ' if rationale else ''}{outro}"
        )
        return {
            "pending_action_id": action.id,
            "preview_lines": lines,
            "messages": [AIMessage(content=text)],
        }

    def await_decision(self, state: dict[str, Any], runtime: Runtime[AgentContext]) -> dict:
        """Aucun effet de bord avant l'interruption : ce noeud est reexecute a la reprise."""
        context = require_context(runtime)
        action_id = state["pending_action_id"]
        resume = interrupt(
            {
                "type": "confirmation",
                "pending_action_id": action_id,
                "kind": (state.get("proposal") or {}).get("kind"),
                "preview": state.get("preview_lines") or [],
            }
        )
        action = self.app.actions.get_action(context.user_id, action_id)
        revised = self._revised_action(resume, action, context)
        if revised is not None:
            # 5.5 : la proposition corrigee remplace l'ancienne ; on attend une nouvelle decision.
            lines = describe_preview([Change(**change) for change in revised.preview])
            body = "\n".join(f"- {line}" for line in lines)
            return {
                "pending_action_id": revised.id,
                "preview_lines": lines,
                "last_result": {"kind": "revised"},
                "messages": [
                    AIMessage(
                        content=f"Proposition mise à jour :\n\n{body}\n\n"
                        "Rien n'est enregistré tant que vous n'avez pas confirmé."
                    )
                ],
            }
        update: dict[str, Any] = {
            "last_result": {
                "kind": "decision",
                "status": action.status.value,
                "action_type": action.action_type.value,
                "result": action.result,
                # Mesure reelle du 11/11/2026 : un nouveau message pendant une proposition
                # l'annulait avec « D'accord, rien n'a été modifié. », lu comme un refus.
                "implicit": isinstance(resume, dict) and bool(resume.get("implicit")),
                # D-82 : « Demander un changement » : rien n'est garde, la conversation reprend.
                "change": isinstance(resume, dict) and resume.get("reason") == "change",
            }
        }
        if update["last_result"]["change"]:
            update["plan_change_requested"] = True
        if action.status.value == "applied" and action.action_type is ActionType.PLAN_CREATE:
            # D-82 : la fiche (profil, notes) reste : le suivi s'appuie sur ce que le coach sait
            # de la personne. Seules les decisions de plan sont remises a zero.
            update.update(plan_offered=None, plan_change_requested=None)
        return update

    def _revised_action(
        self, resume: Any, previous: PendingAction, context: AgentContext
    ) -> PendingAction | None:
        """La valeur de reprise n'est pas fiable : tout est reverifie en base."""
        if not isinstance(resume, dict) or resume.get("decision") != "revised":
            return None
        try:
            candidate = self.app.actions.get_action(context.user_id, str(resume.get("action_id")))
        except DomainError:
            return None
        valid = (
            previous.status is ActionStatus.SUPERSEDED
            and candidate.status is ActionStatus.PENDING
            and candidate.project_id == context.project_id
            and candidate.action_type is previous.action_type
        )
        return candidate if valid else None

    # --- lectures et statut ---------------------------------------------------------
    def answer_status(self, state: dict[str, Any], runtime: Runtime[AgentContext]) -> dict:
        context = require_context(runtime)
        coach = self.app.coach
        summary = coach.get_progress(context.user_id, context.project_id)
        if summary.total == 0:
            # Recette reelle du 11/11/2026 : « Pas encore de plan. » etait dit deux fois.
            return {"last_result": {"kind": "status", "text": co.NO_PLAN_STATUS}}
        next_actions = coach.get_next_actions(context.user_id, context.project_id)
        asked = _last_human_text(state.get("messages", []))
        snapshot = coach.get_snapshot(context.user_id, context.project_id)
        if co.DONE_QUERY.search(asked):
            done = [t for t in snapshot.ordered_tasks() if t.status is TaskStatus.DONE]
            listed = (
                "Tâches terminées :\n" + "\n".join(f"- {t.ref} « {t.title} »" for t in done)
                if done
                else "Aucune tâche n'est encore terminée."
            )
            text = f"{format_progress(summary)}\n\n{listed}\n\n{format_next_step(next_actions)}"
        elif NEXT_QUERY.search(asked.lower()):
            text = f"{format_progress(summary)}\n{format_next_step(next_actions)}"
            if next_actions.state == "ok":
                task = snapshot.tasks[next_actions.items[0].task_id]
                how = co.how_to(task.title, task.description, task.acceptance_criteria)
                text = f"{text}\n\n{how}" if how else text
        else:
            text = f"{format_progress(summary)}\n{format_next_actions(next_actions)}"
        return {"last_result": {"kind": "status", "text": text}}

    def apply_status(self, state: dict[str, Any], runtime: Runtime[AgentContext]) -> dict:
        """Changement direct (R-CONF-01a), seulement si le MESSAGE designe la tache (D-57).

        La reference proposee par le modele n'est jamais suffisante : constate avec gpt-5-mini,
        « J'ai fini » a termine une tache devinee. Journal et annulation inchanges.
        """
        context = require_context(runtime)
        intent = IntentResult(**state["intent"])
        snapshot = self.app.coach.get_snapshot(context.user_id, context.project_id)
        text = _last_human_text(state.get("messages", []))
        catalog = [(task.id, task.number, task.title) for task in snapshot.tasks.values()]
        if intent.target_status is None and (inferred := infer_target_status(text)):
            intent = intent.model_copy(update={"target_status": TaskStatus(inferred)})
        if intent.target_status is TaskStatus.DONE:
            # D-85 : plusieurs taches dites terminees (« J'ai fini l'offre et les deux
            # exemples ») : une carte les confirme ensemble ; une tache que le message ne
            # designe pas seule, sans equivoque, est aussi confirmee par un clic.
            group = designate_tasks(text, catalog, intent.task_refs)
            group = [t for t in group if snapshot.tasks[t].status is not TaskStatus.DONE]
            if len(group) >= 2 or (group and designate_task(text, catalog)[0] is None):
                return {"proposal": {"kind": "tasks_done", "task_ids": group}}
        task_id, why = designate_task(text, catalog)
        if task_id is None:
            if intent.target_status is TaskStatus.BLOCKED and not why.startswith("T"):
                return {}
            target = intent.target_status.value if intent.target_status else None
            question = STATUS_QUESTIONS.get(target or "", DEFAULT_STATUS_QUESTION)
            prefix = f"Je ne trouve pas la tâche {why}. " if why.startswith("T") else ""
            return {"last_result": {"kind": "question", "text": prefix + question}}
        if intent.target_status is None:
            return {
                "last_result": {
                    "kind": "question",
                    "text": "Voulez-vous la commencer, la terminer, la bloquer ou la rouvrir ?",
                }
            }
        reason = intent.blocked_reason if intent.target_status is TaskStatus.BLOCKED else None
        try:
            change = self.app.coach.set_task_status(
                context.user_id, task_id, intent.target_status, reason
            )
        except DomainError as exc:
            return {"error": _error(exc)}
        return {
            "last_result": {
                "kind": "status_change",
                "text": format_status_change(change),
                "event_id": change.event_id,
            }
        }

    def pause(self, state: dict[str, Any], runtime: Runtime[AgentContext]) -> dict:
        """D-85 : pause ou reprise proposee, appliquee seulement apres le clic (carte)."""
        context = require_context(runtime)
        intent = IntentResult(**state["intent"])
        project = self.app.coach.get_project(context.user_id, context.project_id)
        if intent.intent == "pause_projet":
            if project.paused_at is not None:
                return {"last_result": {"kind": "text", "text": ALREADY_PAUSED}}
            note = (intent.pause_note or "").strip()
            # La raison affichee vient des mots de la personne, jamais d'une supposition.
            keep = note and grounded_in(note, _user_texts(state))
            return {"proposal": {"kind": "pause", "note": note[:300] if keep else None}}
        if project.paused_at is None:
            return {}  # rien a reprendre : le coach repond normalement
        return {"proposal": {"kind": "resume"}}

    def followup(self, state: dict[str, Any], runtime: Runtime[AgentContext]) -> dict:
        """D-87 : seconde demande du meme message, apres la premiere. Une adaptation de plan
        n'est preparee que si la premiere action a ete appliquee (reprise refusee : rien) ;
        l'aide est toujours donnee."""
        require_context(runtime)
        wanted = (state.get("followup") or {}).get("intent")
        result = state.get("last_result") or {}
        done = (result.get("kind") == "decision" and result.get("status") == "applied") or (
            result.get("kind") == "status_change"
        )
        if wanted is None or not (done or wanted == "aide"):
            return {"followup": None, "followup_skipped": True}
        return {
            "followup": None,
            "followup_skipped": None,
            "intent": IntentResult(intent=wanted).model_dump(mode="json"),
            "last_result": None,
            "proposal": None,
            "pending_action_id": None,
            "preview_lines": None,
        }

    def out_of_scope(self, state: dict[str, Any], runtime: Runtime[AgentContext]) -> dict:
        require_context(runtime)
        return {"last_result": {"kind": "text", "text": OUT_OF_SCOPE_MESSAGE}}

    # --- reponse --------------------------------------------------------------------
    def respond(self, state: dict[str, Any], runtime: Runtime[AgentContext]) -> dict:
        context = require_context(runtime)
        if (state.get("last_result") or {}).get("kind") == "coach_done" and not state.get("error"):
            return {}  # la reponse du coach est deja dans le fil (noeud clarify)
        update: dict[str, Any] = {}
        try:
            text = self._compose(state, context)
        except DomainError as exc:
            # Erreur explicite, a reessayer : jamais une fausse reponse du coach.
            text = exc.user_message
            update["error"] = _error(exc)
        prefs = (state.get("snapshot") or {}).get("preferences") or {}
        report = (state.get("last_result") or {}).get("kind") == "report"
        if prefs.get("one_question_at_a_time", True) and not report:
            # PF-03 : preference de l'utilisateur, appliquee aussi au texte du modele (consigne
            # d'une question au plus ; le texte enregistre la respecte toujours).
            text = keep_one_question(text)
        return {**update, "messages": [AIMessage(content=text)]}

    def _compose(self, state: dict[str, Any], context: AgentContext) -> str:
        """Texte de la reponse. Le code ne produit que des donnees
        (etat, decision, erreur) et les regles de permission (preferences, hors perimetre)."""
        if state.get("error"):
            return state["error"]["message"]
        result = state.get("last_result") or {}
        kind = result.get("kind")
        if kind in ("question", "text", "status", "status_change", "report"):
            return result["text"]
        if kind == "decision":
            return self._decision_text(result, context)
        intent = (state.get("intent") or {}).get("intent")
        if intent == "preferences" and not state.get("research_followup"):
            return PREFERENCES_MESSAGE
        return self._llm_reply(state, context)

    def _decision_text(self, result: dict[str, Any], context: AgentContext) -> str:
        status = result["status"]
        if status == "applied":
            coach = self.app.coach
            if result["action_type"] == ActionType.PLAN_CREATE.value:
                next_actions = coach.get_next_actions(context.user_id, context.project_id)
                first = next_actions.items[0] if next_actions.items else None
                if first is None:
                    return "Le plan est enregistré."
                task = coach.get_snapshot(context.user_id, context.project_id).tasks[first.task_id]
                how = co.how_to(task.title, task.description, task.acceptance_criteria)
                return (
                    f"Le plan est enregistré. Première action : {first.ref} « {first.title} »."
                    + (f"\n\n{how}" if how else "")
                    + f"\n\nQuand c'est fait, écrivez « J'ai terminé {first.ref} » ou cliquez "
                    f"sur « Marquer terminée {first.ref} » dans l'onglet Plan et tâches."
                )
            summary = coach.get_progress(context.user_id, context.project_id)
            if result["action_type"] == ActionType.PROJECT_PAUSE.value:
                return (
                    f"Le projet est en pause. {format_progress(summary)} Votre plan, vos tâches et"
                    " ce que je retiens de votre projet restent enregistrés. Revenez quand vous "
                    "voulez : on repartira de là où vous en êtes."
                )
            if result["action_type"] == ActionType.PROJECT_RESUME.value:
                return f"Le projet a repris. {format_progress(summary)}"
            if result["action_type"] == ActionType.TASKS_COMPLETE.value:
                refs = (result.get("result") or {}).get("task_refs") or []
                done = " et ".join(refs) if len(refs) <= 2 else ", ".join(refs)
                word = "terminées" if len(refs) > 1 else "terminée"
                return f"C'est enregistré : {done} {word}. {format_progress(summary)}"
            return f"C'est enregistré. {format_progress(summary)}"
        if status == "cancelled" and result.get("implicit"):
            return IMPLICIT_CANCEL
        if status == "cancelled" and result.get("change"):
            return CHANGE_REQUESTED
        if status == "failed":
            code = (result.get("result") or {}).get("error", ErrorCode.STORAGE_ERROR.value)
            return USER_MESSAGES.get(ErrorCode(code), USER_MESSAGES[ErrorCode.STORAGE_ERROR])
        return DECISION_MESSAGES.get(status, DECISION_MESSAGES["pending"])

    def _llm_reply(self, state: dict[str, Any], context: AgentContext, **extra: Any) -> str:
        """Reponse du modele avec le contexte complet ; une erreur remonte (respond l'affiche
        comme une erreur a reessayer, jamais comme une reponse du coach)."""
        text = _last_human_text(state.get("messages", []))
        facts = self._reply_facts(state, context, self._facts(state, **extra))
        reply, _ = self._model_reply(build_messages("coach_reply", text=text, facts=facts), facts)
        return reply
