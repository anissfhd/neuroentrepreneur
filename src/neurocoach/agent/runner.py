"""Point d'entree unique de l'interface vers le graphe (tests techniques S-01, S-02, S-04).

Le lanceur :
- verifie que le fil de conversation appartient a l'utilisateur de la session (S-04) ;
- fournit l'identite par le contexte d'execution a chaque appel, reprise comprise ;
- avant un nouveau message, annule la proposition en attente et clot l'execution interrompue,
  car LangGraph abandonnerait sinon l'interruption en silence (S-02) ;
- ne reprend le graphe que s'il attend reellement la decision concernee (S-01, double clic).
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from neurocoach.agent.context import AgentContext
from neurocoach.agent.llm import METRICS, STREAM
from neurocoach.agent.research_dialogue import CANCELLED, RESEARCH_WITH_BUTTON
from neurocoach.application.research_format import (
    DETAILS_MARKER,
    format_analysis,
    format_mission_summary,
    format_solutions,
)
from neurocoach.application.research_service import PROGRESS, Progress
from neurocoach.bootstrap import Application
from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.plans import PlanEdits
from neurocoach.domain.profiles import is_generic_title, valid_title
from neurocoach.domain.research import MissionStatus, ResearchMission

MAX_MESSAGE_LENGTH = 2000
AFFIRMATIVE = re.compile(
    r"^\s*(oui|ok|okay|d'accord|je confirme|confirme|je valide|valide|c'est bon|parfait|"
    r"vas-y|go|👍|✅|✔️?)\s*[.!]*\s*$",  # emoji d'accord : traites comme « oui » (D-44)
    re.IGNORECASE,
)
NEGATIVE = re.compile(
    r"^\s*(non|annule|annuler|j'annule|pas maintenant|stop|non merci)\s*[.!]*\s*$", re.IGNORECASE
)
CONFIRM_WITH_BUTTON = (
    "Pour enregistrer cette proposition, utilisez le bouton « Confirmer ». "
    "Je n'applique jamais un changement sans ce clic."
)
# D-85 : un projet laisse de cote au moins ce nombre de jours recoit un resume de retour.
RETURN_AFTER_DAYS = 14
# D-76 : premier message d'un projet ouvert par « Créer votre projet ». Texte fixe, ajoute au
# fil sans appel au modele, une seule fois par projet.
# D-84 : accueil court (vision V1 : pas de longue introduction).
WELCOME_MESSAGE = (
    "Bonjour, je suis votre coach entrepreneurial. Parlez-moi de votre projet, même s'il "
    "n'est pas encore clair : on avancera ensemble, étape par étape."
)
_TOLERATED_DECISION_ERRORS = frozenset(
    {
        ErrorCode.ACTION_ALREADY_DECIDED,
        ErrorCode.ACTION_EXPIRED,
        ErrorCode.VERSION_CONFLICT,
        ErrorCode.STORAGE_ERROR,
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.CYCLE_DETECTED,
        ErrorCode.DONE_TASK_PROTECTED,
    }
)


@dataclass(frozen=True)
class TurnResult:
    reply: str | None
    pending: dict[str, Any] | None = None
    last_result: dict[str, Any] | None = None
    notice: str | None = None
    # D-78 : erreur explicite du tour (a reessayer) et mesures : un element par appel au
    # modele (tache, duree, premier fragment) plus la duree totale du tour.
    error: dict[str, Any] | None = None
    timings: dict[str, Any] = field(default_factory=dict)

    @property
    def undo_event_id(self) -> str | None:
        result = self.last_result or {}
        return result.get("event_id") if result.get("kind") == "status_change" else None


class CoachAgent:
    def __init__(self, app: Application, graph: Any, llm: Any = None) -> None:
        self.app = app
        self.graph = graph
        self.llm = llm  # R4 : modele de strategie pour l'analyse demandee depuis l'onglet

    def _session(self, user_id: str, project_id: str) -> tuple[dict, AgentContext]:
        # Leve NOT_FOUND si le projet n'appartient pas a l'utilisateur.
        thread = self.app.coach.get_conversation_thread(user_id, project_id)
        return {"configurable": {"thread_id": thread.id}}, AgentContext(user_id, project_id)

    def pending_confirmation(self, user_id: str, project_id: str) -> dict[str, Any] | None:
        config, _ = self._session(user_id, project_id)
        state = self.graph.get_state(config)
        for task in state.tasks:
            for item in task.interrupts:
                return dict(item.value)
        return None

    # --- D-76 : projet commence par la conversation --------------------------------------
    def greet(self, user_id: str, project_id: str) -> bool:
        """Ajoute le message d'accueil si le fil est vide (aucun appel au modele). Un fil deja
        commence n'est jamais modifie ; l'accueil n'apparait donc qu'une fois par projet."""
        config, _ = self._session(user_id, project_id)
        if self.graph.get_state(config).values.get("messages"):
            return False
        self.graph.update_state(
            config, {"messages": [AIMessage(content=WELCOME_MESSAGE)]}, as_node="respond"
        )
        return True

    # --- D-85 : retour sur un projet en pause ou laisse de cote --------------------------
    def welcome_back(self, user_id: str, project_id: str) -> bool:
        """Resume de retour, ajoute au fil sans appel au modele, une fois par pause ou par
        absence d'au moins RETURN_AFTER_DAYS jours. Tout vient de la base et de la fiche
        enregistree ; jamais pendant une proposition en attente."""
        config, _ = self._session(user_id, project_id)
        state = self.graph.get_state(config)
        if not any(isinstance(m, HumanMessage) for m in state.values.get("messages", [])):
            return False
        if self.pending_confirmation(user_id, project_id) is not None:
            return False
        project = self.app.coach.get_project(user_id, project_id)
        now = self.app.clock.now()
        moments = [project.updated_at]
        if (event := self.app.coach.last_activity(user_id).get(project_id)) is not None:
            moments.append(event)
        if turn_at := state.values.get("last_turn_at"):
            moments.append(datetime.fromisoformat(turn_at))  # dernier message de la personne
        last = max(moments)
        triggers = [project.paused_at] if project.paused_at else []
        if now - last >= timedelta(days=RETURN_AFTER_DAYS):
            triggers.append(last)
        if not triggers:
            return False
        shown = state.values.get("return_recap_at")
        if shown and datetime.fromisoformat(shown) >= max(triggers):
            return False
        self.graph.update_state(
            config,
            {
                "messages": [AIMessage(content=self.return_recap(user_id, project_id))],
                "return_recap_at": now.isoformat(),
            },
            as_node="respond",
        )
        return True

    def return_recap(self, user_id: str, project_id: str) -> str:
        """Ce qui est reellement enregistre : sujet, taches terminees et bloquees, pause et sa
        raison, points a retenir, echeances, prochaine action. Aucune information supposee."""
        from neurocoach.agent.coaching import lower_first
        from neurocoach.domain.clock import local_today
        from neurocoach.domain.models import TaskStatus
        from neurocoach.domain.preview import format_date_fr
        from neurocoach.domain.project_profile import extract_known

        coach = self.app.coach
        project = coach.get_project(user_id, project_id)
        tasks = coach.get_snapshot(user_id, project_id).ordered_tasks()
        prefs = coach.get_preferences(user_id)
        kept = self.retained(user_id, project_id)
        texts = [m["content"] for m in self.history(user_id, project_id) if m["role"] == "user"]
        subject = kept["idee"] or project.idea or project.title
        # Le sujet tel qu'enregistre, limite a sa premiere phrase (une idee saisie a la creation
        # peut etre un long message).
        subject = (
            re.split(r"[.;!?](?:\s|$)", subject.strip(), maxsplit=1)[0].strip() or project.title
        )
        facts = [f"Bon retour ! Voici où nous en étions sur votre projet : {lower_first(subject)}."]
        done = [task for task in tasks if task.status is TaskStatus.DONE]
        if done:
            word = "tâche" if len(done) == 1 else "tâches"
            facts.append(
                f"Vous avez terminé {len(done)} {word} sur {len(tasks)} : "
                + ", ".join(f"{task.ref} « {task.title} »" for task in done)
                + "."
            )
        elif tasks:
            facts.append(f"Aucune des {len(tasks)} tâches du plan n'est encore terminée.")
        else:
            facts.append("Aucun plan n'est encore enregistré.")
        facts += [
            f"{task.ref} « {task.title} » est bloquée : « {task.blocked_reason} »."
            for task in tasks
            if task.status is TaskStatus.BLOCKED
        ]
        if project.paused_at:
            day = format_date_fr(local_today(project.paused_at, prefs.display_timezone))
            said = (project.pause_note or "").strip().rstrip(".")
            note = f" : « {said} »" if said else ""
            facts.append(f"Nous avions mis le projet en pause le {day}{note}.")
        if kept["notes"]:
            # D-86 (campagne reelle V1) : sept notes du modele presentees comme « demandées »
            # par la personne ; seules les trois dernieres, sans lui attribuer la demande.
            facts.append(
                "Points notés pendant nos échanges : "
                + " ; ".join(f"« {note} »" for note in kept["notes"][-3:])
                + "."
            )
        if not prefs.deadlines_enabled and extract_known(texts).no_deadlines:
            facts.append("Vos tâches restent sans échéance, comme vous le souhaitiez.")
        next_actions = coach.get_next_actions(user_id, project_id)
        if next_actions.items and not project.paused_at:
            first = next_actions.items[0]
            facts.append(f"La prochaine action serait {first.ref} « {first.title} ».")
        question = (
            "Souhaitez-vous reprendre ? Dites-moi aussi ce qui a changé (temps, budget, envies) : "
            "j'adapterai les prochaines tâches en gardant celles qui sont terminées."
            if project.paused_at
            else "On reprend avec cette action, ou faut-il adapter le plan ?"
        )
        return " ".join(facts) + "\n\n" + question

    def resume_project(self, user_id: str, project_id: str) -> str:
        """Bouton « Reprendre le projet » : meme action que la carte de reprise (journal)."""
        from neurocoach.application.formatting import format_progress

        if self.pending_confirmation(user_id, project_id) is not None:
            raise DomainError(
                ErrorCode.VALIDATION_ERROR, "Une proposition attend d'abord votre décision."
            )
        action = self.app.actions.request_resume(user_id, project_id)
        self.app.actions.confirm(user_id, action.id)
        progress = format_progress(self.app.coach.get_progress(user_id, project_id))
        text = f"Le projet a repris. {progress}"
        config, _ = self._session(user_id, project_id)
        self.graph.update_state(config, {"messages": [AIMessage(content=text)]}, as_node="respond")
        return text

    def title_suggestion(self, user_id: str, project_id: str) -> str | None:
        """Titre PROPOSE : celui du modele au dernier tour, sinon une reformulation des
        messages les plus recents. Pour un projet deja titre, un nouveau titre n'est propose
        que si l'ancien est generique ou sans rapport avec le sujet compris (recette du
        11/11/2026 : « Accompagnement création entreprise » pour des bougies). Rien n'est
        enregistre ici : l'interface demande le clic de l'utilisateur."""
        project = self.app.coach.get_project(user_id, project_id)
        config, _ = self._session(user_id, project_id)
        values = self.graph.get_state(config).values
        brief = values.get("brief_draft") or {}
        # D-80 : seul le titre du modele, verifie (complet, concret), et seulement une fois
        # une idee retenue ; plus de titre taille dans une phrase (« Son propre business
        # (offre et cible »).
        proposed = valid_title(brief.get("project_title")) or ""
        if project.title_pending:
            return proposed or None if brief.get("idea_summary") else None
        if project.status.value != "draft" or not proposed or is_generic_title(proposed):
            return None
        subject = str(brief.get("idea_summary") or project.idea or "").lower()
        words = {w for w in project.title.lower().replace("-", " ").split() if len(w) > 3}
        unrelated = not any(w in subject for w in words)
        if proposed.lower() != project.title.lower() and (
            is_generic_title(project.title) or unrelated
        ):
            return proposed
        return None

    def start_project(self, user_id: str) -> Any:
        """Nouveau projet : un projet vide (aucun message echange) est repris, jamais un projet
        dont la conversation a commence."""
        return self.app.coach.start_project(
            user_id,
            unused=lambda p: self.conversation_summary(user_id, p.id)["user_count"] == 0,
        )

    def retained(self, user_id: str, project_id: str) -> dict[str, Any]:
        """D-82 : ce que le coach a retenu de la personne et du projet, tel qu'enregistre
        (fiche de l'etat LangGraph) ; l'interface l'affiche pour que tout soit verifiable."""
        from neurocoach.agent.nodes import DISCOVERY_DISPLAY, discovery_values
        from neurocoach.agent.schemas import ProjectBrief
        from neurocoach.domain.project_profile import extract_known

        config, _ = self._session(user_id, project_id)
        brief = ProjectBrief(**(self.graph.get_state(config).values.get("brief_draft") or {}))
        texts = [m["content"] for m in self.history(user_id, project_id) if m["role"] == "user"]
        values = discovery_values(brief, extract_known(texts))
        return {
            "profil": {DISCOVERY_DISPLAY[k]: v for k, v in values.items() if v},
            "idee": brief.idea_summary,
            "notes": list(brief.notes),
        }

    def conversation_summary(self, user_id: str, project_id: str) -> dict[str, Any]:
        """Historique reellement enregistre : nombre de messages, dernier message et date du
        dernier enregistrement du fil (les messages ne sont pas horodates un par un)."""
        config, _ = self._session(user_id, project_id)
        state = self.graph.get_state(config)
        messages = [
            m for m in state.values.get("messages", []) if isinstance(m, HumanMessage | AIMessage)
        ]
        last = messages[-1] if messages else None
        return {
            "count": len(messages),
            "user_count": sum(isinstance(m, HumanMessage) for m in messages),
            "last_role": None
            if last is None
            else ("user" if isinstance(last, HumanMessage) else "assistant"),
            "last_text": str(last.content) if last is not None else "",
            "saved_at": state.created_at,
        }

    def history(
        self, user_id: str, project_id: str, *, include_ids: bool = False
    ) -> list[dict[str, str]]:
        config, _ = self._session(user_id, project_id)
        values = self.graph.get_state(config).values
        return [
            {
                "role": "user" if isinstance(message, HumanMessage) else "assistant",
                "content": str(message.content),
                **({"id": message.id or ""} if include_ids else {}),
            }
            for message in values.get("messages", [])
            if isinstance(message, HumanMessage | AIMessage)
        ]

    def edit_message(
        self,
        user_id: str,
        project_id: str,
        message_id: str,
        text: str,
        *,
        stream: Callable[[str], None] | None = None,
    ) -> TurnResult:
        """Repart du checkpoint antérieur au message, sans rejouer les écritures métier."""
        text = text.strip()
        if not text or len(text) > MAX_MESSAGE_LENGTH:
            raise DomainError(ErrorCode.VALIDATION_ERROR, "Message vide ou trop long.")
        config, _ = self._session(user_id, project_id)
        checkpoint = self.graph.get_state(config)
        if not any(
            isinstance(message, HumanMessage) and message.id == message_id
            for message in checkpoint.values.get("messages", [])
        ):
            raise DomainError(ErrorCode.NOT_FOUND, "Message introuvable dans cette conversation.")
        while any(m.id == message_id for m in checkpoint.values.get("messages", [])):
            if not checkpoint.parent_config:
                raise DomainError(ErrorCode.NOT_FOUND, "Le point de reprise est introuvable.")
            checkpoint = self.graph.get_state(checkpoint.parent_config)
        pending = self.pending_confirmation(user_id, project_id)
        if pending:
            self.decide(user_id, project_id, pending["pending_action_id"], "cancel", implicit=True)
        mission = self.research_pending(user_id, project_id)
        previous_flow = checkpoint.values.get("research_flow") or {}
        if mission and mission.id != previous_flow.get("mission_id"):
            self.app.research.cancel_mission(user_id, mission.id)
        self.graph.update_state(checkpoint.config, {"pending_action_id": None}, as_node="respond")
        return self.send_message(user_id, project_id, text, stream=stream)

    # --- recherche (R3, D-70) : approbation par bouton uniquement ---------------------------
    def research_pending(self, user_id: str, project_id: str) -> ResearchMission | None:
        """Mission proposee dans CETTE conversation et toujours en attente d'approbation."""
        config, _ = self._session(user_id, project_id)
        flow = self.graph.get_state(config).values.get("research_flow") or {}
        mission_id = flow.get("mission_id")
        if flow.get("stage") != "proposed" or not mission_id:
            return None
        for mission in self.app.research.list_missions(user_id, project_id):
            if mission.id == mission_id and mission.status is MissionStatus.PROPOSED:
                return mission
        return None

    def approve_research(
        self,
        user_id: str,
        project_id: str,
        mission_id: str,
        scope_hash: str,
        *,
        progress: Progress | None = None,
    ) -> TurnResult:
        """Clic « Approuver et lancer » : approbation a usage unique de l'apercu affiche, puis
        recherches dans le perimetre, puis resume source dans la conversation."""
        mission = self.research_pending(user_id, project_id)
        if mission is None or mission.id != mission_id:
            raise DomainError(ErrorCode.ACTION_ALREADY_DECIDED)
        self.app.research.approve_mission(user_id, mission_id, scope_hash)
        report = self.app.research.run_mission(user_id, mission_id, progress=progress)
        summary = format_mission_summary(report)
        if mission.scope.purpose == "solutions" and self.llm is not None:
            # R6 : les solutions sont proposees par le modele de strategie, validees par le
            # code, a partir des sources que cette mission vient de collecter.
            from neurocoach.agent.research_analyst import LLMResearchAnalyst

            try:
                plan = self.app.research.solve_mission(
                    user_id, mission_id, LLMResearchAnalyst(self.llm), progress=progress
                )
                summary = format_solutions(plan, report.sources)
            except DomainError as exc:
                summary = f"{summary}\n\n{exc.user_message}"
        elif self.llm is not None and any(q.status == "done" for q in report.queries):
            # D-80 : la recherche approuvee aboutit a son analyse critique (pertinence des
            # sources, prix chiffres, niveau de preuve), sans mot-cle a taper. Aucune nouvelle
            # recherche ni ecriture dans le projet : un appel au modele, sur les sources deja
            # collectees.
            from neurocoach.agent.research_analyst import LLMResearchAnalyst

            texts = [m["content"] for m in self.history(user_id, project_id) if m["role"] == "user"]
            try:
                analysis = self.app.research.analyze_mission(
                    user_id, mission_id, LLMResearchAnalyst(self.llm),
                    context_texts=texts, progress=progress,
                )  # fmt: skip
                # D-84 : pas de journal d'execution dans la conversation (nombre de
                # recherches et de resultats) : il reste dans l'onglet Recherche.
                details = format_analysis(analysis, report.sources, log=False)
                conclusion = self._research_conclusion(user_id, project_id, analysis, report)
                summary = f"{conclusion}\n\n{DETAILS_MARKER}\n\n{details}"
            except DomainError as exc:
                summary = f"{summary}\n\nAnalyse non réalisée : {exc.user_message}"
        notice = self._post(user_id, project_id, summary, "done", mission_id)
        return TurnResult(reply=summary, notice=notice)

    def _research_conclusion(
        self, user_id: str, project_id: str, analysis: Any, report: Any
    ) -> str:
        """D-82 : conclusion d'expert, courte, ecrite par le modele a partir des seuls elements
        VALIDES de l'analyse (le detail reste consultable). En cas d'echec : un resume factuel
        de l'analyse validee, jamais un conseil invente."""
        from neurocoach.agent.nodes import research_conclusion
        from neurocoach.agent.schemas import ProjectBrief

        config, _ = self._session(user_id, project_id)
        values = self.graph.get_state(config).values
        brief = ProjectBrief(**(values.get("brief_draft") or {}))
        texts = [m["content"] for m in self.history(user_id, project_id) if m["role"] == "user"]
        return research_conclusion(self.llm, analysis, report.sources, brief, texts)

    def cancel_research(self, user_id: str, project_id: str, mission_id: str) -> TurnResult:
        mission = self.research_pending(user_id, project_id)
        if mission is None or mission.id != mission_id:
            raise DomainError(ErrorCode.ACTION_ALREADY_DECIDED)
        self.app.research.cancel_mission(user_id, mission_id)
        notice = self._post(user_id, project_id, CANCELLED, "cancelled", mission_id)
        return TurnResult(reply=CANCELLED, notice=notice)

    def analyze_research(
        self,
        user_id: str,
        project_id: str,
        mission_id: str,
        *,
        force: bool = False,
        progress: Progress | None = None,
    ) -> Any:
        """Bouton « Analyser ces résultats » (onglet Recherche) : meme analyse que dans la
        conversation, sur les sources deja collectees ; aucune ecriture dans le projet."""
        from neurocoach.agent.research_analyst import LLMResearchAnalyst

        if not any(
            m.id == mission_id for m in self.app.research.list_missions(user_id, project_id)
        ):
            raise DomainError(ErrorCode.NOT_FOUND, "Mission introuvable dans ce projet.")
        if self.llm is None:
            raise DomainError(ErrorCode.LLM_UNAVAILABLE)
        texts = [m["content"] for m in self.history(user_id, project_id) if m["role"] == "user"]
        return self.app.research.analyze_mission(
            user_id,
            mission_id,
            LLMResearchAnalyst(self.llm),
            context_texts=texts[-40:],
            force=force,
            progress=progress,
        )

    def solve_research(
        self, user_id: str, project_id: str, mission_id: str, *, progress: Progress | None = None
    ) -> Any:
        """Bouton « Proposer les solutions » (onglet) : sources deja collectees seulement."""
        from neurocoach.agent.research_analyst import LLMResearchAnalyst

        if not any(
            m.id == mission_id for m in self.app.research.list_missions(user_id, project_id)
        ):
            raise DomainError(ErrorCode.NOT_FOUND, "Mission introuvable dans ce projet.")
        if self.llm is None:
            raise DomainError(ErrorCode.LLM_UNAVAILABLE)
        return self.app.research.solve_mission(
            user_id, mission_id, LLMResearchAnalyst(self.llm), progress=progress
        )

    def _post(
        self,
        user_id: str,
        project_id: str,
        text: str,
        stage: str,
        mission_id: str,
        human: str | None = None,
    ) -> str | None:
        """Ajoute la reponse au fil, hors execution du graphe. Si une proposition de plan
        attend une decision, le fil n'est pas touche (l'interruption resterait coherente)."""
        if self.pending_confirmation(user_id, project_id) is not None:
            return "Résultats enregistrés : consultez l'onglet Recherche."
        config, _ = self._session(user_id, project_id)
        flow = dict(self.graph.get_state(config).values.get("research_flow") or {})
        flow.update(stage=stage, mission_id=mission_id)
        messages = [HumanMessage(content=human)] if human else []
        self.graph.update_state(
            config,
            {"messages": [*messages, AIMessage(content=text)], "research_flow": flow},
            as_node="respond",
        )
        return None

    def send_message(
        self,
        user_id: str,
        project_id: str,
        text: str,
        *,
        progress: Progress | None = None,
        stream: Callable[[str], None] | None = None,
    ) -> TurnResult:
        text = text.strip()
        if not text or len(text) > MAX_MESSAGE_LENGTH:
            raise DomainError(
                ErrorCode.VALIDATION_ERROR, f"Message vide ou trop long ({MAX_MESSAGE_LENGTH} max)."
            )
        config, context = self._session(user_id, project_id)
        pending = self.pending_confirmation(user_id, project_id)
        research = self.research_pending(user_id, project_id) if pending is None else None
        if research is not None:
            if AFFIRMATIVE.match(text):
                # Un « oui » ecrit n'approuve jamais une recherche : seul le bouton le fait.
                return TurnResult(reply=None, notice=RESEARCH_WITH_BUTTON)
            if NEGATIVE.match(text):
                self.app.research.cancel_mission(user_id, research.id)
                self._post(user_id, project_id, CANCELLED, "cancelled", research.id, human=text)
                return TurnResult(reply=CANCELLED)
        if pending is not None:
            action_id = pending["pending_action_id"]
            from neurocoach.agent.nodes import PLAN_SAVED_QUESTION

            if PLAN_SAVED_QUESTION.match(text):
                return TurnResult(
                    reply=None,
                    pending=pending,
                    notice="Les tâches seront enregistrées après votre confirmation.",
                )
            if AFFIRMATIVE.match(text):
                # D-40 : un « oui » ecrit ne confirme jamais (R-SEC-04) et n'annule pas non plus.
                return TurnResult(reply=None, pending=pending, notice=CONFIRM_WITH_BUTTON)
            if NEGATIVE.match(text):
                return self.decide(user_id, project_id, action_id, "cancel")
            # S-02 / D-32 : annuler en base, clore l'execution interrompue, puis traiter le message.
            self.decide(user_id, project_id, action_id, "cancel", implicit=True)
        # D-81 : plus d'« idee » enregistree par motif sur le premier message (« j'aimerais
        # creer mon business, mais je ne sais pas par ou commencer » devenait l'idee du projet,
        # et le modele, croyant le sujet connu, conseillait au lieu de decouvrir la personne).
        # L'idee du projet est celle que le coach a comprise (fiche, D-78).
        # Finalisation : une analyse declenchee par la conversation signale sa progression ;
        # D-78 : la reponse du coach est diffusee a l'interface et chaque appel est mesure.
        calls: list[dict[str, Any]] = []
        started = time.monotonic()
        marks: dict[str, float] = {}

        def timed(partial: str) -> None:
            # D-79 : premier fragment visible et fin de la reponse, cote utilisateur.
            now = time.monotonic()
            marks.setdefault("first", now)
            marks["last"] = now
            if stream is not None:
                stream(partial)

        tokens = (
            PROGRESS.set(progress),
            STREAM.set(timed if stream is not None else None),
            METRICS.set(calls),
        )
        try:
            result = self.graph.invoke(
                {"messages": [HumanMessage(content=text)]}, config, context=context
            )
        finally:
            PROGRESS.reset(tokens[0])
            STREAM.reset(tokens[1])
            METRICS.reset(tokens[2])
        turn = self._turn(result)
        total = time.monotonic() - started
        timings: dict[str, Any] = {"total": round(total, 3), "calls": calls}
        if marks:
            reply_done = marks["last"] - started
            timings.update(
                first_visible=round(marks["first"] - started, 3),
                reply_complete=round(reply_done, 3),
                after_reply=round(total - reply_done, 3),  # plan, recherche : apres la reponse
            )
        if result.get("coach_decision"):
            timings["decision"] = result["coach_decision"]
        # D-79 : une decision du coach refusee par le code est dite (avis factuel).
        notice = turn.notice or (turn.last_result or {}).get("notice")
        return TurnResult(
            reply=turn.reply,
            pending=turn.pending,
            last_result=turn.last_result,
            notice=notice,
            error=result.get("error"),
            timings=timings,
        )

    def revise_plan(
        self, user_id: str, project_id: str, action_id: str, edits: PlanEdits
    ) -> TurnResult:
        """5.5 : remplace la proposition en attente par une version corrigee, sans l'appliquer."""
        pending = self.pending_confirmation(user_id, project_id)
        if pending is None or pending.get("pending_action_id") != action_id:
            raise DomainError(ErrorCode.ACTION_ALREADY_DECIDED)
        revised = self.app.actions.revise_plan(user_id, action_id, edits)
        config, context = self._session(user_id, project_id)
        result = self.graph.invoke(
            Command(resume={"decision": "revised", "action_id": revised.id}),
            config,
            context=context,
        )
        return self._turn(result)

    def decide(
        self,
        user_id: str,
        project_id: str,
        action_id: str,
        decision: Literal["confirm", "cancel"],
        *,
        implicit: bool = False,
        reason: str | None = None,
    ) -> TurnResult:
        notice = None
        # D-44 : une decision ne vaut que pour une action du projet de la conversation.
        if self.app.actions.get_action(user_id, action_id).project_id != project_id:
            raise DomainError(ErrorCode.NOT_FOUND, "Proposition introuvable dans ce projet.")
        try:
            if decision == "confirm":
                self.app.actions.confirm(user_id, action_id)
            else:
                self.app.actions.cancel(user_id, action_id)
        except DomainError as exc:
            if exc.code not in _TOLERATED_DECISION_ERRORS:
                raise
            notice = exc.user_message
        pending = self.pending_confirmation(user_id, project_id)
        if pending is None or pending.get("pending_action_id") != action_id:
            # Rien a reprendre (double clic, apercu perime) : aucune execution du graphe.
            return TurnResult(reply=None, notice=notice)
        config, context = self._session(user_id, project_id)
        resume = {"decision": decision, "implicit": implicit, "reason": reason}
        result = self.graph.invoke(Command(resume=resume), config, context=context)
        turn = self._turn(result)
        return TurnResult(turn.reply, turn.pending, turn.last_result, notice)

    @staticmethod
    def _turn(result: dict[str, Any]) -> TurnResult:
        messages = result.get("messages", [])
        reply = next((str(m.content) for m in reversed(messages) if isinstance(m, AIMessage)), None)
        interrupts = result.get("__interrupt__") or []
        pending = dict(interrupts[0].value) if interrupts else None
        return TurnResult(reply=reply, pending=pending, last_result=result.get("last_result"))
