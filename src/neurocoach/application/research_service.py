"""Service du Business Researcher (R1, D-68) : missions de recherche approuvees, simulees.

Independant de Streamlit et du graphe : l'interface l'appelle aujourd'hui, le coach
conversationnel pourra l'appeler en R3 avec les memes garanties.

Parcours :
1. ``prepare_mission`` : fiche construite a partir du projet, requetes exactes, apercu du
   perimetre (objectif, projets, marches, categories, fournisseurs, donnees transmises,
   budget et limites). Rien n'est enregistre ; au plus une question si le marche manque.
2. ``propose_mission`` : la proposition est enregistree avec son empreinte et une echeance.
3. ``approve_mission`` : approbation EXPLICITE, a usage unique (transition conditionnelle),
   liee a l'empreinte affichee ; un « oui » ecrit ne declenche rien.
4. ``run_mission`` / ``run_query`` : dans le perimetre approuve, plusieurs recherches sans
   nouvelle confirmation ; perimetre et budget verifies AVANT chaque requete.
5. ``extend_mission`` : toute extension (projet, marche, categorie, fournisseur, budget,
   limites) cree une nouvelle proposition a approuver.

Une recherche n'ecrit jamais dans les projets, les phases ni les taches. Tout est journalise
dans ``activity_events``.
"""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import Annotated, Any, Protocol, TypeVar

from pydantic import Field

from neurocoach.application.base import BaseService, make_event
from neurocoach.domain.analysis import (
    ComparisonDraft,
    IdeaAnalysis,
    IdeaAnalysisDraft,
    ResearchAnalysis,
    build_profile,
    sources_fingerprint,
    validate_comparison,
    validate_idea_analysis,
)
from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.models import DomainModel, EventType, Project, new_id
from neurocoach.domain.research import (
    CATEGORY_LABELS,
    CORE_CATEGORIES,
    DEFAULT_BUDGET_USD,
    DEFAULT_MAX_QUERIES,
    DEFAULT_RESULTS_PER_QUERY,
    DEFAULT_VALIDITY_DAYS,
    VOICE_CATEGORIES,
    Finding,
    MissionScope,
    MissionStatus,
    Nature,
    PlannedQuery,
    ProblemTarget,
    QueryRecord,
    RequestedQuery,
    ResearchBrief,
    ResearchCategory,
    ResearchMission,
    SourceRecord,
    build_brief,
    check_in_scope,
    content_hash,
    domain_of,
    excerpt_of,
    is_suspicious,
    mark_contradictions,
    minimize,
    missing_question,
    mission_fingerprint,
    plan_queries,
    scope_extension,
    scope_lines,
    spec_queries,
    validate_finding,
)
from neurocoach.domain.solutions import (
    ProblemSolutions,
    SolutionPlan,
    SolutionsDraft,
    solution_queries,
    validate_solutions,
)
from neurocoach.domain.voice import STATUS_LABELS, analyze_voice, is_promotional
from neurocoach.infra.repositories import SqliteRepository
from neurocoach.infra.research_repository import ResearchRepository
from neurocoach.research.extract import ExtractiveFindingExtractor
from neurocoach.research.policy import DomainPolicy, load_domain_policy
from neurocoach.research.ports import (
    FindingExtractor,
    ProviderError,
    ProviderRegistry,
    RawResult,
)

TRANSMITTED = [
    "le texte exact des requêtes listées (mots-clés de l'offre, type de recherche, marché)",
    "aucun message, nom, e-mail, téléphone, identifiant interne ni terme de santé",
]
NOT_CONFIGURED = (
    "La recherche web n'est pas activée : aucune clé Tavily ou Exa n'est configurée "
    "(voir .env.example), et la simulation n'est pas demandée."
)
MIXED = "Une mission ne mélange jamais résultats simulés et recherche réelle."
MAX_SOURCES_PER_IDEA = 12
# Progression (finalisation) : message court a afficher pendant une operation longue.
Progress = Callable[[str], None]
PROGRESS: ContextVar[Progress | None] = ContextVar("research_progress", default=None)
_T = TypeVar("_T")
_R = TypeVar("_R")
NOT_RUN_YET = "Aucune recherche n'a encore été faite pour cette mission : rien à analyser."


class ResearchAnalyst(Protocol):
    """Port du modele de strategie (R4) : propose, le code valide. Implementation : agent."""

    def analyze_idea(self, payload: dict[str, Any]) -> IdeaAnalysisDraft: ...

    def compare(self, payload: dict[str, Any]) -> ComparisonDraft: ...

    def propose_solutions(self, payload: dict[str, Any]) -> SolutionsDraft: ...


OUT_OF_BUDGET = (
    "Le budget ou le nombre de recherches de la mission est atteint : une extension doit "
    "être approuvée."
)
NO_DATA = "Aucune donnée fiable trouvée."


class MissionRequest(DomainModel):
    """Ce que l'utilisateur demande ; le perimetre exact est recalcule par le service."""

    project_ids: list[str] = Field(min_length=1, max_length=5)
    objective: str | None = Field(default=None, max_length=300)
    categories: list[ResearchCategory] = Field(default_factory=lambda: list(CORE_CATEGORIES))
    markets: list[str] = Field(default_factory=list, max_length=5)
    providers: list[str] | None = None
    max_budget_usd: float = Field(default=DEFAULT_BUDGET_USD, gt=0, le=10)
    max_queries: int | None = Field(default=None, gt=0, le=50)
    max_results_per_query: int = Field(default=DEFAULT_RESULTS_PER_QUERY, gt=0, le=10)
    validity_days: int = Field(default=DEFAULT_VALIDITY_DAYS, gt=0, le=30)
    # R3 : idees a comparer dans le projet (une fiche par idee), et textes deja ecrits par
    # l'utilisateur dans la conversation (memoire : marche, cible, canal). Ces textes ne
    # sont jamais transmis tels quels : seules les requetes minimisees partent.
    ideas: list[Annotated[str, Field(min_length=2, max_length=200)]] = Field(
        default_factory=list, max_length=5
    )
    context_texts: list[Annotated[str, Field(max_length=2000)]] = Field(
        default_factory=list, max_length=40
    )
    # R6 : problemes a resoudre (mission de solutions) ; categorie « solutions » seule.
    problems: list[ProblemTarget] = Field(default_factory=list, max_length=3)
    # D-80 : ce que le modele a compris de la conversation (jamais le titre du projet) :
    # sujet precis, cible, requetes redigees et sens homonymes a ecarter.
    subject: str | None = Field(default=None, max_length=200)
    segment: str | None = Field(default=None, max_length=150)
    queries: list[RequestedQuery] = Field(default_factory=list, max_length=12)
    exclude_senses: list[Annotated[str, Field(max_length=80)]] = Field(
        default_factory=list, max_length=5
    )


class MissionDraft(DomainModel):
    question: str | None = None  # une seule, si une information indispensable manque
    briefs: dict[str, ResearchBrief]
    scope: MissionScope | None = None
    planned: list[PlannedQuery] = Field(default_factory=list)
    preview: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    estimated_cost_usd: float = 0.0
    scope_hash: str | None = None


class CategoryReport(DomainModel):
    category: ResearchCategory
    label: str
    findings: list[Finding]
    no_data: bool


class MissionReport(DomainModel):
    mission: ResearchMission
    queries: list[QueryRecord]
    sources: list[SourceRecord]
    categories: list[CategoryReport]
    hypotheses: list[str]
    simulated: bool
    authorization_active: bool
    subject_of: dict[str, str] = Field(default_factory=dict)  # source -> idee comparee
    not_run: int = 0  # recherches prevues non lancees (quota gratuit ou budget)


class ResearchService(BaseService):
    def __init__(
        self,
        *args: Any,
        registry: ProviderRegistry,
        extractor: FindingExtractor | None = None,
        policy: DomainPolicy | None = None,
        parallelism: int = 4,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.parallelism = max(1, parallelism)
        # Durees de la derniere operation, par etape (mesures avant/apres, en secondes).
        self.last_timings: dict[str, float] = {}
        # R5 (D-72) : sites exclus des requetes et filtres a la reception.
        self.policy = policy or load_domain_policy()
        # Registre explicite (bootstrap) : aucun repli silencieux vers la simulation.
        self.registry = registry
        self.extractor = extractor or ExtractiveFindingExtractor()

    # --- execution parallele et progression (finalisation) ------------------------------
    @staticmethod
    def _notify(progress: Progress | None, message: str) -> None:
        callback = progress or PROGRESS.get()
        if callback is None:
            return
        with contextlib.suppress(Exception):  # l'affichage n'interrompt jamais une recherche
            callback(message)

    def _parallel(
        self,
        fn: Callable[[_T], _R],
        items: Sequence[_T],
        *,
        label: str,
        progress: Progress | None = None,
    ) -> list[_R]:
        """``fn`` sur chaque element, au plus ``parallelism`` a la fois ; resultats dans
        l'ordre des elements. La progression est signalee depuis le fil appelant (le seul qui
        peut mettre a jour l'interface). Une erreur arrete tout : les appels non commences
        sont annules, ceux en cours se terminent et sont comptes."""
        total = len(items)
        if total == 0:
            return []
        results: list[Any] = [None] * total
        width = min(self.parallelism, total)
        if width == 1:
            for index, item in enumerate(items):
                results[index] = fn(item)
                self._notify(progress, f"{label} : {index + 1}/{total}")
            return results
        pool = ThreadPoolExecutor(max_workers=width, thread_name_prefix="recherche")
        try:
            futures = {
                pool.submit(contextvars.copy_context().run, fn, item): index
                for index, item in enumerate(items)
            }
            for done, future in enumerate(as_completed(futures), start=1):
                results[futures[future]] = future.result()
                self._notify(progress, f"{label} : {done}/{total}")
        except BaseException:
            pool.shutdown(wait=True, cancel_futures=True)
            raise
        pool.shutdown(wait=True)
        return results

    # --- etat des services ---------------------------------------------------------------
    @staticmethod
    def period(now: datetime) -> str:
        return now.strftime("%Y-%m")

    def availability(self) -> dict[str, Any]:
        """Services branches et quota mensuel local restant (jamais aucune cle)."""
        now = self.clock.now()
        with self._read() as repo:
            usage = ResearchRepository(repo.conn).provider_usage(self.period(now))
        services = []
        for name in self.registry.names():
            entry = self.registry.catalog.entry(name)
            used = usage.get(name, {})
            services.append(
                {
                    "name": name,
                    "label": entry.label,
                    "simulated": entry.simulated,
                    "monthly_cap_usd": entry.monthly_cap_usd,
                    "used_usd": used.get("reserved_usd", 0.0),
                    "queries": used.get("queries", 0),
                    "exhausted": used.get("exhausted", False),
                    "free_tier": entry.free_tier,
                }
            )
        return {
            "enabled": bool(services),
            "real": bool(self.registry.real_names()),
            "services": services,
        }

    # --- preparation ---------------------------------------------------------------------
    def prepare_mission(self, user_id: str, request: MissionRequest) -> MissionDraft:
        now = self.clock.now()
        with self._read() as repo:
            return self._prepare(repo, user_id, request, now)

    def _prepare(
        self, repo: SqliteRepository, user_id: str, request: MissionRequest, now: datetime
    ) -> MissionDraft:
        self._preferences(repo, user_id, now)  # utilisateur existant
        if len(set(request.project_ids)) != len(request.project_ids):
            raise DomainError(ErrorCode.VALIDATION_ERROR, "Projet en double.")
        user = repo.get_user(user_id)
        assert user is not None
        projects = [repo.get_project(user_id, pid) for pid in request.project_ids]
        if request.problems:
            request = request.model_copy(update={"categories": [ResearchCategory.SOLUTIONS]})
        categories = list(dict.fromkeys(request.categories))
        if not categories:
            raise DomainError(ErrorCode.VALIDATION_ERROR, "Choisissez au moins une recherche.")
        if not self.registry.names():
            raise DomainError(ErrorCode.VALIDATION_ERROR, NOT_CONFIGURED)
        providers = request.providers or self.registry.default_names()
        kinds = {self.registry.get(name).simulated for name in providers}  # branche, sinon refus
        if len(kinds) > 1:
            raise DomainError(ErrorCode.VALIDATION_ERROR, MIXED)
        forbidden = user.display_name.split()
        if request.problems:
            if len(projects) != 1:
                raise DomainError(ErrorCode.VALIDATION_ERROR, "Solutions : un seul projet.")
            request = request.model_copy(update={"categories": [ResearchCategory.SOLUTIONS],
                                                 "ideas": []})  # fmt: skip
        if request.ideas and len(projects) != 1:
            raise DomainError(ErrorCode.VALIDATION_ERROR, "Idées comparées : un seul projet.")
        ideas = [" ".join(i.replace("?", "").split()) for i in request.ideas]
        if request.ideas:
            project = projects[0]
            briefs = {
                f"{project.id}#{n}": self._brief(
                    project, request.markets, request.context_texts, idea=idea
                )
                for n, idea in enumerate(ideas, 1)
            }
        else:
            subject = request.subject if len(projects) == 1 else None
            briefs = {
                p.id: self._brief(
                    p,
                    request.markets,
                    request.context_texts,
                    idea=subject,
                    segment=request.segment if subject else None,
                )
                for p in projects
            }
        question = next(
            (q for b in briefs.values() if (q := missing_question(b, categories))), None
        )
        hypotheses = [h for b in briefs.values() for h in b.hypotheses]
        if question:
            return MissionDraft(question=question, briefs=briefs, hypotheses=hypotheses)
        routing = self.registry.routing(providers)
        uncovered = [c for c in categories if not routing.get(c)]
        if uncovered:
            raise DomainError(
                ErrorCode.VALIDATION_ERROR,
                "Aucun fournisseur choisi ne couvre : "
                + ", ".join(CATEGORY_LABELS[c] for c in uncovered)
                + ".",
            )
        if request.problems:
            # R6 : pour chaque probleme, outils existants, logiciels libres et methodes.
            exa_angles = {"outils", "libre"}
            planned = []
            for problem in request.problems:
                for angle, text in solution_queries(problem, forbidden):
                    for provider in routing.get(ResearchCategory.SOLUTIONS, []):
                        if provider == "exa" and angle not in exa_angles:
                            continue
                        planned.append(
                            PlannedQuery(category=ResearchCategory.SOLUTIONS, text=text,
                                         provider=provider, project_id=projects[0].id,
                                         subject=problem.label)
                        )  # fmt: skip
        elif request.ideas:
            planned = [
                q
                for n, idea in enumerate(ideas, 1)
                for q in plan_queries(briefs[f"{projects[0].id}#{n}"], categories, routing,
                                      forbidden, project_id=projects[0].id, subject=idea)
            ]  # fmt: skip
        elif request.subject and request.queries and len(projects) == 1:
            planned = spec_queries(request.queries, briefs[projects[0].id], categories,
                                   routing, forbidden, project_id=projects[0].id)  # fmt: skip
        else:
            planned = [
                q
                for p in projects
                for q in plan_queries(briefs[p.id], categories, routing, forbidden, project_id=p.id)
            ]
        markets = list(dict.fromkeys(m for b in briefs.values() for m in b.markets))
        estimated = round(sum(self.registry.cost(q.provider) for q in planned), 6)
        max_queries = request.max_queries or min(50, max(DEFAULT_MAX_QUERIES, len(planned)))
        if len(planned) > max_queries:
            raise DomainError(
                ErrorCode.VALIDATION_ERROR,
                f"{len(planned)} recherches prévues pour une limite de {max_queries} : "
                "réduisez les recherches ou augmentez la limite.",
            )
        if estimated > request.max_budget_usd + 1e-9:
            raise DomainError(
                ErrorCode.VALIDATION_ERROR,
                f"Coût estimé {estimated:.3f} $ supérieur au budget "
                f"{request.max_budget_usd:.2f} $.",
            )
        if request.problems and not request.objective:
            request = request.model_copy(
                update={
                    "objective": (
                        "Trouver des solutions concrètes à : "
                        + " ; ".join(p.label for p in request.problems)
                    )[:300]
                }
            )
        named = [request.subject] if request.subject else [p.idea or p.title for p in projects]
        objective = request.objective or (
            "Étudier " + ", ".join(CATEGORY_LABELS[c] for c in categories)
            + " pour : " + ", ".join(named)
        )[:300]  # fmt: skip
        simulated = all(self.registry.get(n).simulated for n in providers)
        scope = MissionScope(
            objective=objective,
            project_ids=[p.id for p in projects],
            markets=markets,
            categories=categories,
            providers=list(providers),
            transmitted=[*TRANSMITTED, *self._destinations(providers)],
            max_budget_usd=request.max_budget_usd,
            max_queries=max_queries,
            max_results_per_query=request.max_results_per_query,
            validity_days=request.validity_days,
            simulated=simulated,
            subjects=[p.label for p in request.problems] if request.problems else ideas,
            purpose="solutions" if request.problems else "research",
            problems=list(request.problems),
            subject=None if request.ideas or request.problems else request.subject,
            segment=None if request.ideas or request.problems else request.segment,
            exclude_senses=[] if request.ideas or request.problems else request.exclude_senses,
        )
        titles = {p.id: p.title for p in projects}
        preview = [
            *scope_lines(scope, titles, self.registry.labels()),
            f"Coût estimé des {len(planned)} recherches prévues : {estimated:.3f} $"
            + (" (fictif)" if simulated else ""),
            *(f"Hypothèse : {h}" for h in hypotheses),
            *(self.policy.preview_lines() if set(categories) & VOICE_CATEGORIES else []),
            *(
                f"Requête ({CATEGORY_LABELS[q.category]}, {q.provider}) : « {q.text} »"
                for q in planned
            ),
        ]
        return MissionDraft(
            briefs=briefs,
            scope=scope,
            planned=planned,
            preview=preview,
            hypotheses=hypotheses,
            estimated_cost_usd=estimated,
            scope_hash=mission_fingerprint(scope, planned),
        )

    def _destinations(self, providers: list[str]) -> list[str]:
        lines = []
        for name in providers:
            entry = self.registry.catalog.entry(name)
            if entry.simulated:
                continue
            kept = "extraits conservés" if entry.store_excerpts else "références seules conservées"
            lines.append(f"envoyé à {entry.label} ({entry.hosting or 'hébergement inconnu'}) ; "
                         f"{kept}")  # fmt: skip
        return lines

    @staticmethod
    def _brief(
        project: Project,
        markets: list[str],
        context_texts: list[str] | None = None,
        *,
        idea: str | None = None,
        segment: str | None = None,
    ) -> ResearchBrief:
        texts = [
            project.title,
            project.idea or "",
            project.target_outcome or "",
            *project.facts,
            *project.assumptions,
            *project.constraints,
            *(context_texts or []),
        ]
        return build_brief(
            title=idea or project.title,
            idea=idea or project.idea or None,
            user_texts=texts,
            constraints=project.constraints,
            markets=markets,
            segment=segment,
        )

    # --- proposition et approbation ------------------------------------------------------
    def propose_mission(
        self, user_id: str, request: MissionRequest, *, parent_mission_id: str | None = None
    ) -> ResearchMission:
        now = self.clock.now()
        with self._write() as repo:
            draft = self._prepare(repo, user_id, request, now)
            if draft.question or draft.scope is None or draft.scope_hash is None:
                raise DomainError(
                    ErrorCode.VALIDATION_ERROR, draft.question or "Mission incomplète."
                )
            research = ResearchRepository(repo.conn)
            preview = list(draft.preview)
            if parent_mission_id is not None:
                parent = research.get_mission(user_id, parent_mission_id)
                added = scope_extension(parent.scope, draft.scope)
                preview = [
                    "Extension de la mission précédente : "
                    + ("; ".join(added) if added else "aucun ajout de périmètre"),
                    f"Déjà dépensé par la mission précédente : {parent.spent_usd:.3f} $",
                    *preview,
                ]
            mission = ResearchMission(
                id=new_id("rsm"),
                user_id=user_id,
                status=MissionStatus.PROPOSED,
                scope=draft.scope,
                briefs=draft.briefs,
                planned=draft.planned,
                preview=preview,
                scope_hash=draft.scope_hash,
                parent_mission_id=parent_mission_id,
                created_at=now,
                expires_at=now + timedelta(minutes=self.settings.pending_action_ttl_minutes),
            )
            research.insert_mission(mission)
            self._journal(
                repo,
                mission,
                EventType.RESEARCH_MISSION_PROPOSED,
                now,
                planned=len(mission.planned),
                max_budget_usd=mission.scope.max_budget_usd,
                simulated=mission.simulated,
            )
        return mission

    def extend_mission(
        self, user_id: str, mission_id: str, request: MissionRequest
    ) -> ResearchMission:
        """Nouvelle proposition, a approuver, pour tout elargissement du perimetre."""
        with self._read() as repo:
            ResearchRepository(repo.conn).get_mission(user_id, mission_id)
        return self.propose_mission(user_id, request, parent_mission_id=mission_id)

    def approve_mission(self, user_id: str, mission_id: str, scope_hash: str) -> ResearchMission:
        """Approbation explicite, a usage unique, de l'apercu dont l'empreinte est fournie."""
        now = self.clock.now()
        refusal: DomainError | None = None
        with self._write() as repo:
            research = ResearchRepository(repo.conn)
            mission = research.get_mission(user_id, mission_id)
            valid_until = now + timedelta(days=mission.scope.validity_days)
            approved = research.transition(
                user_id,
                mission_id,
                source=MissionStatus.PROPOSED,
                target=MissionStatus.APPROVED,
                now=now,
                not_after=now,
                valid_until=valid_until,
                scope_hash=scope_hash,
            )
            if not approved:
                # L'expiration eventuelle est enregistree (transaction validee), puis refus.
                refusal = self._refusal(research, repo, mission, scope_hash, now)
            else:
                if mission.parent_mission_id:
                    parent = research.get_mission(user_id, mission.parent_mission_id)
                    if research.transition(
                        user_id,
                        parent.id,
                        source=MissionStatus.APPROVED,
                        target=MissionStatus.SUPERSEDED,
                        now=now,
                    ):
                        self._journal(repo, parent, EventType.RESEARCH_MISSION_SUPERSEDED, now,
                                      by=mission.id)  # fmt: skip
                self._journal(
                    repo,
                    mission,
                    EventType.RESEARCH_MISSION_APPROVED,
                    now,
                    valid_until=valid_until.isoformat(),
                    max_budget_usd=mission.scope.max_budget_usd,
                    max_queries=mission.scope.max_queries,
                )
                result = research.get_mission(user_id, mission_id)
        if refusal is not None:
            raise refusal
        return result

    def _refusal(
        self,
        research: ResearchRepository,
        repo: SqliteRepository,
        mission: ResearchMission,
        scope_hash: str,
        now: datetime,
    ) -> DomainError:
        if mission.status is not MissionStatus.PROPOSED:
            return DomainError(ErrorCode.ACTION_ALREADY_DECIDED)
        if mission.expires_at <= now:
            if research.transition(
                mission.user_id,
                mission.id,
                source=MissionStatus.PROPOSED,
                target=MissionStatus.EXPIRED,
                now=now,
            ):
                self._journal(repo, mission, EventType.RESEARCH_MISSION_EXPIRED, now)
            return DomainError(ErrorCode.ACTION_EXPIRED)
        if mission.scope_hash != scope_hash:
            return DomainError(
                ErrorCode.VERSION_CONFLICT, "L'aperçu approuvé ne correspond pas à la mission."
            )
        return DomainError(ErrorCode.ACTION_ALREADY_DECIDED)  # pragma: no cover - concurrence

    def cancel_mission(self, user_id: str, mission_id: str) -> ResearchMission:
        """Annule une proposition, ou retire une autorisation en cours."""
        now = self.clock.now()
        with self._write() as repo:
            research = ResearchRepository(repo.conn)
            mission = research.get_mission(user_id, mission_id)
            for source in (MissionStatus.PROPOSED, MissionStatus.APPROVED):
                if research.transition(
                    user_id, mission_id, source=source, target=MissionStatus.CANCELLED, now=now
                ):
                    self._journal(repo, mission, EventType.RESEARCH_MISSION_CANCELLED, now,
                                  previous=source.value)  # fmt: skip
                    return research.get_mission(user_id, mission_id)
        raise DomainError(ErrorCode.ACTION_ALREADY_DECIDED)

    def close_mission(self, user_id: str, mission_id: str) -> ResearchMission:
        """Met fin a l'autorisation (aucune nouvelle recherche) en gardant les resultats."""
        now = self.clock.now()
        with self._write() as repo:
            research = ResearchRepository(repo.conn)
            mission = research.get_mission(user_id, mission_id)
            if not self._finish(research, repo, mission, now):
                raise DomainError(ErrorCode.ACTION_ALREADY_DECIDED)
            return research.get_mission(user_id, mission_id)

    def _finish(
        self,
        research: ResearchRepository,
        repo: SqliteRepository,
        mission: ResearchMission,
        now: datetime,
    ) -> bool:
        queries = research.list_queries(mission.user_id, mission.id)
        done = [q for q in queries if q.status == "done"]
        complete = len(done) >= len(mission.planned) and len(done) == len(queries)
        target = MissionStatus.COMPLETED if complete else MissionStatus.PARTIAL
        if not research.transition(
            mission.user_id, mission.id, source=MissionStatus.APPROVED, target=target, now=now
        ):
            return False
        self._journal(repo, mission, EventType.RESEARCH_MISSION_CLOSED, now,
                      status=target.value, queries=len(queries))  # fmt: skip
        return True

    # --- execution dans le perimetre -----------------------------------------------------
    def run_mission(
        self, user_id: str, mission_id: str, *, progress: Progress | None = None
    ) -> MissionReport:
        """Execute les requetes prevues et pas encore faites, sans nouvelle confirmation.

        Finalisation : les requetes sont independantes et partent en parallele, sauf la
        premiere de chaque service, envoyee seule : un quota epuise est ainsi detecte avant
        d'envoyer les autres. Chaque requete reserve son cout et son quota avant l'appel."""
        start = time.monotonic()
        with self._read() as repo:
            research = ResearchRepository(repo.conn)
            mission = research.get_mission(user_id, mission_id)
            done = research.list_queries(user_id, mission_id)
        remaining = list(mission.planned)
        for query in done:
            key = (query.project_id, query.category, query.provider, query.market, query.text,
                   query.subject)  # fmt: skip
            for planned in remaining:
                if (planned.project_id, planned.category, planned.provider, planned.market,
                        planned.text, planned.subject) == key:  # fmt: skip
                    remaining.remove(planned)
                    break

        def one(planned: PlannedQuery) -> None:
            assert planned.project_id is not None
            try:
                self.run_query(
                    user_id,
                    mission_id,
                    project_id=planned.project_id,
                    category=planned.category,
                    provider=planned.provider,
                    market=planned.market,
                    text=planned.text,
                    refresh=False,
                    subject=planned.subject,
                )
            except DomainError as exc:
                # Budget de mission ou quota gratuit atteint : refuse AVANT l'appel, sans cout.
                if exc.detail == OUT_OF_BUDGET or exc.data.get("quota"):
                    return
                raise

        first: dict[str, PlannedQuery] = {}
        for planned in remaining:
            first.setdefault(planned.provider, planned)
        probes = list(first.values())
        rest = [p for p in remaining if all(p is not probe for probe in probes)]
        total = len(remaining)
        label = "Recherches web"
        done = 0
        for probe in probes:
            one(probe)
            done += 1
            self._notify(progress, f"{label} : {done}/{total}")
        if rest:
            offset = done

            def relay(message: str) -> None:
                count = int(message.rsplit(" ", 1)[1].split("/")[0])
                self._notify(progress, f"{label} : {offset + count}/{total}")

            self._parallel(one, rest, label=label, progress=relay)
        self._refresh_findings(user_id, mission_id)
        self.last_timings = {"recherches_web": round(time.monotonic() - start, 2)}
        return self.mission_report(user_id, mission_id)

    def run_query(
        self,
        user_id: str,
        mission_id: str,
        *,
        project_id: str,
        category: ResearchCategory,
        provider: str,
        market: str | None,
        text: str,
        refresh: bool = True,
        subject: str | None = None,
    ) -> QueryRecord:
        """Une recherche dans le perimetre approuve (point d'entree reutilisable en R3).

        Ordre : verification (statut, validite, perimetre), reservation du cout et du quota,
        appel au fournisseur HORS transaction, enregistrement des sources bornees."""
        now = self.clock.now()
        with self._read() as repo:
            user = repo.get_user(user_id)
            if user is None:
                raise DomainError(ErrorCode.NOT_FOUND, "Utilisateur introuvable.")
            forbidden = user.display_name.split()
        cleaned = minimize(text, forbidden)
        if not cleaned:
            raise DomainError(ErrorCode.VALIDATION_ERROR, "Requête vide après minimisation.")
        backend = self.registry.get(provider)  # fournisseur branche, sinon refus
        entry = self.registry.catalog.entry(provider)
        cost = self.registry.cost(provider)
        period = self.period(now)
        self._authorize(user_id, mission_id, project_id, category, provider, market, cost, now)
        error = error_kind = None
        actual: float | None = None
        results: list[RawResult] = []
        try:
            response = backend.search(
                cleaned,
                category=category,
                market=market,
                max_results=self._max_results(user_id, mission_id),
                exclude_domains=self.policy.excluded_domains,
            )
            results, actual = response.results, response.cost_usd
        except ProviderError as exc:  # message sans cle ni en-tete
            error, error_kind = str(exc)[:200], exc.kind
        except Exception as exc:  # panne inattendue : seule la categorie est conservee
            error, error_kind = type(exc).__name__, "error"
        retrieved = self.clock.now()
        # R5 : un resultat d'un site exclu (Reddit, plateformes d'avis restrictives) est
        # ecarte avant tout stockage, meme si le service l'a renvoye.
        blocked = [r for r in results if self.policy.blocked_site(r.url) is not None]
        results = [r for r in results if self.policy.blocked_site(r.url) is None]
        record = QueryRecord(
            id=new_id("rsq"),
            mission_id=mission_id,
            user_id=user_id,
            project_id=project_id,
            category=category,
            provider=provider,
            market=market,
            text=cleaned,
            status="failed" if error else "done",
            estimated_cost_usd=cost,
            result_count=len(results),
            error=error,
            simulated=backend.simulated,
            created_at=retrieved,
            actual_cost_usd=actual,
            error_kind=error_kind,
            subject=subject,
            blocked_count=len(blocked),
        )
        with self._write() as repo:
            research = ResearchRepository(repo.conn)
            mission = research.get_mission(user_id, mission_id)
            research.insert_query(record)
            if actual is not None and abs(actual - cost) > 1e-9:
                # Le cout reel annonce remplace l'estimation, pour la mission et le quota.
                research.adjust_spent(user_id, mission_id, actual - cost)
                if not backend.simulated:
                    research.settle_provider(provider, period, actual - cost, retrieved)
            if error_kind == "quota" and not backend.simulated:
                research.mark_exhausted(provider, period, retrieved)
            known = {s.content_hash for s in research.list_sources(user_id, mission_id)}
            for raw in results[: mission.scope.max_results_per_query]:
                # Conditions du service : texte conserve seulement s'il est autorise.
                excerpt = excerpt_of(raw.content) if entry.store_excerpts else ""
                digest = content_hash(raw.url, excerpt)
                if digest in known:
                    continue
                known.add(digest)
                research.insert_source(
                    user_id,
                    mission_id,
                    SourceRecord(
                        id=new_id("rss"),
                        query_id=record.id,
                        category=category,
                        provider=provider,
                        url=raw.url,
                        domain=domain_of(raw.url),
                        title=" ".join(raw.title.split())[:300],
                        excerpt=excerpt,
                        published_date=raw.published_date,
                        retrieved_at=retrieved,
                        market=raw.market,
                        content_hash=digest,
                        suspicious=is_suspicious(f"{raw.title} {excerpt}"),
                        simulated=backend.simulated,
                    ),
                )
            self._journal(repo, mission, EventType.RESEARCH_QUERY_RUN, retrieved,
                          query_id=record.id, status=record.status,
                          results=record.result_count, blocked=len(blocked),
                          cost_usd=actual if actual is not None else cost)  # fmt: skip
        if refresh:
            self._refresh_findings(user_id, mission_id)
        return record

    def _max_results(self, user_id: str, mission_id: str) -> int:
        with self._read() as repo:
            mission = ResearchRepository(repo.conn).get_mission(user_id, mission_id)
        return mission.scope.max_results_per_query

    def _authorize(
        self,
        user_id: str,
        mission_id: str,
        project_id: str,
        category: ResearchCategory,
        provider: str,
        market: str | None,
        cost: float,
        now: datetime,
    ) -> None:
        refusal: DomainError | None = None
        with self._write() as repo:
            research = ResearchRepository(repo.conn)
            mission = research.get_mission(user_id, mission_id)
            if mission.status is not MissionStatus.APPROVED:
                refusal = DomainError(
                    ErrorCode.VALIDATION_ERROR,
                    "Cette mission n'est pas approuvée : aucune recherche n'est lancée.",
                )
            elif mission.valid_until is not None and mission.valid_until <= now:
                self._finish(research, repo, mission, now)
                refusal = DomainError(
                    ErrorCode.ACTION_EXPIRED, "L'autorisation de la mission est terminée."
                )
            else:
                try:
                    check_in_scope(
                        mission.scope,
                        project_id=project_id,
                        category=category,
                        provider=provider,
                        market=market,
                    )
                except DomainError as exc:
                    refusal = exc
                else:
                    refusal = self._reserve(research, user_id, mission_id, provider, cost, now)
            if refusal is not None and mission.status is MissionStatus.APPROVED:
                self._journal(repo, mission, EventType.RESEARCH_QUERY_REFUSED, now,
                              reason=refusal.detail or str(refusal.code))  # fmt: skip
        if refusal is not None:
            raise refusal

    def _reserve(
        self,
        research: ResearchRepository,
        user_id: str,
        mission_id: str,
        provider: str,
        cost: float,
        now: datetime,
    ) -> DomainError | None:
        """Quota mensuel du service PUIS budget de la mission, dans la meme transaction :
        si la mission refuse, la reservation du quota est rendue."""
        entry = self.registry.catalog.entry(provider)
        period = self.period(now)
        real = not entry.simulated
        if real and not research.reserve_provider(
            provider, period, cost, entry.monthly_cap_usd, now
        ):
            return DomainError(
                ErrorCode.VALIDATION_ERROR,
                f"Quota gratuit mensuel de {entry.label} atteint (plafond local "
                f"{entry.monthly_cap_usd or 0:.2f} $) : service suspendu jusqu'au mois "
                "prochain, aucun dépassement payant n'est tenté.",
                quota=True,
            )
        if not research.reserve(user_id, mission_id, cost, now):
            if real:
                research.settle_provider(provider, period, -cost, now, queries=-1)
            return DomainError(ErrorCode.VALIDATION_ERROR, OUT_OF_BUDGET)
        return None

    def _refresh_findings(self, user_id: str, mission_id: str) -> None:
        now = self.clock.now()
        with self._write() as repo:
            research = ResearchRepository(repo.conn)
            mission = research.get_mission(user_id, mission_id)
            sources = research.list_sources(user_id, mission_id)
            by_id = {s.id: s for s in sources}
            brief = next(iter(mission.briefs.values()))
            findings = [
                validate_finding(
                    candidate,
                    by_id,
                    finding_id=new_id("rsf"),
                    project_markets=mission.scope.markets,
                )
                for candidate in self.extractor.extract(brief, sources)
            ]
            research.replace_findings(user_id, mission_id, mark_contradictions(findings), now)

    # --- lecture -------------------------------------------------------------------------
    def list_missions(self, user_id: str, project_id: str | None = None) -> list[ResearchMission]:
        with self._read() as repo:
            if project_id is not None:
                repo.get_project(user_id, project_id)
            return ResearchRepository(repo.conn).list_missions(user_id, project_id)

    def mission_report(self, user_id: str, mission_id: str) -> MissionReport:
        now = self.clock.now()
        with self._read() as repo:
            research = ResearchRepository(repo.conn)
            mission = research.get_mission(user_id, mission_id)
            queries = research.list_queries(user_id, mission_id)
            sources = research.list_sources(user_id, mission_id)
            findings = research.list_findings(user_id, mission_id)
        ran = {q.category for q in queries}
        categories = []
        for category in mission.scope.categories:
            items = sorted(
                (f for f in findings if f.category is category),
                key=lambda f: list(Nature).index(f.nature),
            )
            categories.append(
                CategoryReport(
                    category=category,
                    label=CATEGORY_LABELS[category],
                    findings=items,
                    no_data=category in ran and not items,
                )
            )
        active = mission.status is MissionStatus.APPROVED and (
            mission.valid_until is None or mission.valid_until > now
        )
        subject_by_query = {q.id: q.subject for q in queries if q.subject}
        return MissionReport(
            mission=mission,
            queries=queries,
            sources=sources,
            categories=categories,
            hypotheses=list(
                dict.fromkeys(h for b in mission.briefs.values() for h in b.hypotheses)
            ),
            simulated=mission.simulated,
            authorization_active=active,
            subject_of={
                s.id: subject_by_query[s.query_id]
                for s in sources
                if s.query_id in subject_by_query
            },
            not_run=max(0, len(mission.planned) - len(queries)),
        )

    def latest_mission(self, user_id: str, project_id: str) -> ResearchMission | None:
        missions = self.list_missions(user_id, project_id)
        return missions[-1] if missions else None

    def conversation_findings(
        self, user_id: str, project_id: str, limit: int = 12
    ) -> list[dict[str, Any]]:
        """Constats de la derniere mission executee du projet, pour la conversation (R3) :
        textes sources, nature et domaines. Aucune URL, aucun texte non cite."""
        missions = [m for m in self.list_missions(user_id, project_id) if m.queries_used > 0]
        if not missions:
            return []
        report = self.mission_report(user_id, missions[-1].id)
        domains = {s.id: s.domain for s in report.sources}
        items = []
        for category in report.categories:
            for finding in category.findings[:3]:
                subjects = {report.subject_of.get(s) for s in finding.source_ids} - {None}
                items.append(
                    {
                        "categorie": category.label,
                        "idee": next(iter(subjects)) if len(subjects) == 1 else None,
                        "constat": finding.statement[:240],
                        "nature": finding.nature.value,
                        "sources": sorted({domains[s] for s in finding.source_ids if s in domains}),
                        "simule": "simulé" in finding.flags,
                    }
                )
        return items[:limit]

    # --- analyse (R4, D-71) --------------------------------------------------------------
    def project_analysis(
        self, user_id: str, project_id: str
    ) -> tuple[ResearchAnalysis, list[SourceRecord]] | None:
        """Derniere analyse d'une mission du projet, avec ses sources (conversation, R4)."""
        for mission in reversed(self.list_missions(user_id, project_id)):
            analysis = self.latest_analysis(user_id, mission.id)
            if analysis is not None:
                with self._read() as repo:
                    sources = ResearchRepository(repo.conn).list_sources(user_id, mission.id)
                return analysis, sources
        return None

    def latest_analysis(self, user_id: str, mission_id: str) -> ResearchAnalysis | None:
        with self._read() as repo:
            found = ResearchRepository(repo.conn).latest_analysis(user_id, mission_id)
        return found[0] if found else None

    def analyze_mission(
        self,
        user_id: str,
        mission_id: str,
        analyst: ResearchAnalyst,
        *,
        context_texts: list[str] | None = None,
        force: bool = False,
        progress: Progress | None = None,
    ) -> ResearchAnalysis:
        """Analyse des sources DEJA collectees par le modele de strategie, validee par le code.

        Aucune nouvelle recherche, aucune ecriture dans le projet. Une analyse identique (memes
        sources, meme profil) est reutilisee sans nouvel appel au modele."""
        now = self.clock.now()
        with self._read() as repo:
            research = ResearchRepository(repo.conn)
            mission = research.get_mission(user_id, mission_id)
            project = repo.get_project(user_id, mission.scope.project_ids[0])
            queries = research.list_queries(user_id, mission_id)
            sources = research.list_sources(user_id, mission_id)
            findings = research.list_findings(user_id, mission_id)
            latest = research.latest_analysis(user_id, mission_id)
        if not any(q.status == "done" for q in queries):
            raise DomainError(ErrorCode.VALIDATION_ERROR, NOT_RUN_YET)
        profile = build_profile(
            [project.title, project.idea, *project.constraints, *project.facts,
             *project.assumptions, *(context_texts or [])],
            minutes_per_day=project.available_minutes_per_day,
            target_outcome=project.target_outcome,
        )  # fmt: skip
        profile_hash = hashlib.sha256(
            json.dumps(profile, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        sources_hash = sources_fingerprint(sources)
        if latest and not force:
            previous, previous_profile = latest
            complete = all(idea.available for idea in previous.ideas)
            # Une analyse incomplete (panne ou reponse tronquee pour une idee) est refaite a
            # la demande suivante, au lieu d'etre resservie indefiniment.
            if (
                complete
                and previous.sources_hash == sources_hash
                and previous_profile == profile_hash
            ):
                return previous
        subject_by_query = {q.id: q.subject for q in queries}
        subjects = mission.scope.subjects or [None]
        started = time.monotonic()

        def analyse_subject(subject: str | None) -> IdeaAnalysis:
            # D-80 : le sujet compris de la mission, jamais le titre provisoire du projet.
            scoped = mission.scope.subject
            label = subject or scoped or project.idea or project.title
            description = None  # le sujet compris suffit (le titre peut etre provisoire)
            pool = [
                s for s in sources if subject is None or subject_by_query.get(s.query_id) == subject
            ]
            blocked = sum(
                q.blocked_count for q in queries if subject is None or q.subject == subject
            )
            return self._analyze_one(
                analyst, label, pool, findings, profile, mission.scope.markets,
                voice_wanted=bool(set(mission.scope.categories) & VOICE_CATEGORIES),
                blocked=blocked,
                description=description,
                segment=mission.scope.segment,
                exclude=mission.scope.exclude_senses,
            )  # fmt: skip

        # Finalisation : les idees sont analysees en parallele (independantes) ; la comparaison
        # attend toutes les analyses validees.
        self._notify(progress, f"Analyse de {len(subjects)} idée(s) en cours")
        ideas: list[IdeaAnalysis] = self._parallel(
            analyse_subject, subjects, label="Analyses d'idées terminées", progress=progress
        )
        timings = {"analyses_idees": round(time.monotonic() - started, 2)}
        comparison = None
        compared = time.monotonic()
        if any(i.available and i.source_count for i in ideas):
            self._notify(progress, "Synthèse et recommandation en cours")
            payload = {
                "objectif": mission.scope.objective,
                "profil": profile,
                "idees": [self._compact(n, idea) for n, idea in enumerate(ideas, 1)],
            }
            try:
                comparison = validate_comparison(
                    analyst.compare(payload), ideas, profile, simulated=mission.simulated
                )
            except DomainError:
                comparison = None
        timings["synthese"] = round(time.monotonic() - compared, 2)
        self.last_timings = timings
        analysis = ResearchAnalysis(
            id=new_id("rsa"),
            mission_id=mission_id,
            user_id=user_id,
            created_at=now,
            ideas=ideas,
            comparison=comparison,
            profile=profile,
            sources_hash=sources_hash,
            simulated=mission.simulated,
        )
        with self._write() as repo:
            research = ResearchRepository(repo.conn)
            research.get_mission(user_id, mission_id)  # toujours la sienne, toujours presente
            research.insert_analysis(analysis, profile_hash)
            self._journal(repo, mission, EventType.RESEARCH_ANALYSIS_CREATED, now,
                          analysis_id=analysis.id, ideas=len(ideas),
                          removed=analysis.removed_count)  # fmt: skip
        return analysis

    def _analyze_one(
        self,
        analyst: ResearchAnalyst,
        label: str,
        pool: list[SourceRecord],
        findings: list[Finding],
        profile: dict[str, list[str]],
        markets: list[str],
        *,
        voice_wanted: bool = False,
        blocked: int = 0,
        description: str | None = None,
        segment: str | None = None,
        exclude: list[str] | None = None,
    ) -> IdeaAnalysis:
        # R5 : voix des clients calculee par le code (themes, corroboration, faux avis).
        voice = analyze_voice(pool, offer=f"{label} {description or ''}")
        if voice_wanted:
            notes = [*voice.notes]
            if blocked:
                notes.append(f"{blocked} résultat(s) de sites exclus écarté(s) avant stockage.")
            notes.append("Reddit non consulté : accès soumis à l'approbation de Reddit.")
            voice = voice.model_copy(update={"notes": notes})
        # Une source contenant une consigne reste stockee et signalee, mais n'est jamais
        # transmise au modele : le Web est une donnee, jamais une instruction.
        # R5 : un avis d'apparence promotionnelle n'est pas transmis au modele et ne peut
        # etayer aucune affirmation.
        promotional = set(voice.promotional)
        excluded = [s for s in pool if s.suspicious]
        usable = [s for s in pool if not s.suspicious and s.id not in promotional][
            :MAX_SOURCES_PER_IDEA
        ]
        aliases = {f"S{i}": s.id for i, s in enumerate(usable, 1)}
        by_id = {s.id: s for s in usable}
        note = (
            [f"{len(excluded)} source(s) contenant une consigne exclue(s) de l'analyse"]
            if excluded
            else []
        )
        if not usable:
            empty = validate_idea_analysis(
                IdeaAnalysisDraft(summary=""), idea=label, aliases={}, sources={},
                profile=profile, markets=markets,
            )  # fmt: skip
            return empty.model_copy(
                update={
                    "unknowns": ["Aucune source exploitable trouvée pour cette idée.",
                                 *empty.unknowns],
                    "removed": note,
                    "voice": voice,
                }
            )  # fmt: skip
        reverse = {sid: alias for alias, sid in aliases.items()}
        payload = {
            "idee": f"{label} : {description}" if description else label,
            "clientele_visee": segment,
            "sens_a_ecarter": exclude or [],
            "profil": profile,
            "marches": markets,
            "sources": [
                {
                    "id": reverse[s.id],
                    "domaine": s.domain,
                    "titre": s.title,
                    "extrait": s.excerpt or "(référence seule : contenu non conservé)",
                    "date": s.published_date.isoformat() if s.published_date else None,
                    "marche": s.market,
                    "categorie": s.category.value,
                }
                for s in usable
            ],
            # Premieres phrases par categorie de requete : NON verifiees (D-80).
            "extraits_non_verifies": [
                {
                    "constat": f.statement,
                    "nature": f.nature.value,
                    "sources": [reverse[s] for s in f.source_ids if s in reverse],
                    "signalements": f.flags,
                }
                for f in findings
                if any(s in reverse for s in f.source_ids)
            ][:20],
            # R5 : themes recurrents (deja verifies) et avis ecartes, pour les pain_points.
            "voix_clients": [
                {
                    "theme": t.label,
                    "sentiment": t.sentiment,
                    "statut": STATUS_LABELS[t.status],
                    "sites": t.domains,
                    "citations": [
                        {"source": reverse[m.source_id], "phrase": m.sentence, "origine": m.origin}
                        for m in t.mentions
                        if m.source_id in reverse
                    ],
                    "sites_independants": t.independent_domains,
                    "sites_vendeurs": t.vendor_domains,
                }
                for t in voice.themes
            ],
            "avis_ecartes": [reverse[s] for s in voice.promotional if s in reverse],
            "avis_de_vendeurs": [reverse[s] for s in voice.vendor_sources if s in reverse],
        }
        try:
            draft = analyst.analyze_idea(payload)
        except DomainError as exc:
            return IdeaAnalysis(
                idea=label,
                available=False,
                unknowns=[f"Analyse indisponible pour le moment ({exc.user_message})"],
                source_count=len(usable),
                removed=note,
                voice=voice,
            )
        analysis = validate_idea_analysis(
            draft, idea=label, aliases=aliases, sources=by_id, profile=profile, markets=markets,
            voice=voice,
        )  # fmt: skip
        return analysis.model_copy(update={"removed": [*note, *analysis.removed]})

    @staticmethod
    def _compact(number: int, idea: IdeaAnalysis) -> dict[str, Any]:
        """Ce que la comparaison recoit : uniquement l'analyse VALIDEE de chaque idee."""
        return {
            "numero": number,
            "idee": idea.idea,
            "analyse_disponible": idea.available,
            "resume": idea.summary,
            "affirmations": {
                section: [{"texte": c.text, "nature": c.kind} for c in claims]
                for section, claims in idea.sections.items()
                if claims
            },
            "concurrents": [c.name for c in idea.competitors],
            "inconnues": idea.unknowns,
            "adequation": [
                {"critere": f.criterion, "note": f.rating, "raison": f.reason} for f in idea.fit
            ],
            "faits_sources": idea.sourced_facts,
            "voix_clients": [
                {"theme": t.label, "sentiment": t.sentiment, "statut": STATUS_LABELS[t.status],
                 "sites": len(t.domains)}
                for t in (idea.voice.themes if idea.voice else [])
            ],
            "frustrations": [
                {"texte": p.statement, "portee": p.scope} for p in idea.pain_points
            ],
        }  # fmt: skip

    # --- solutions (R6, D-73) -------------------------------------------------------------
    def latest_solutions(self, user_id: str, mission_id: str) -> SolutionPlan | None:
        with self._read() as repo:
            return ResearchRepository(repo.conn).latest_solutions(user_id, mission_id)

    def project_solutions(
        self, user_id: str, project_id: str
    ) -> tuple[SolutionPlan, list[SourceRecord]] | None:
        for mission in reversed(self.list_missions(user_id, project_id)):
            plan = self.latest_solutions(user_id, mission.id)
            if plan is not None:
                with self._read() as repo:
                    sources = ResearchRepository(repo.conn).list_sources(user_id, mission.id)
                return plan, sources
        return None

    def solve_mission(
        self,
        user_id: str,
        mission_id: str,
        analyst: ResearchAnalyst,
        *,
        force: bool = False,
        progress: Progress | None = None,
    ) -> SolutionPlan:
        """Solutions par probleme, a partir des sources DEJA collectees par la mission de
        solutions approuvee ; validees par le code. Aucune ecriture dans le projet."""
        now = self.clock.now()
        with self._read() as repo:
            research = ResearchRepository(repo.conn)
            mission = research.get_mission(user_id, mission_id)
            project = repo.get_project(user_id, mission.scope.project_ids[0])
            queries = research.list_queries(user_id, mission_id)
            sources = research.list_sources(user_id, mission_id)
            latest = research.latest_solutions(user_id, mission_id)
        if mission.scope.purpose != "solutions" or not mission.scope.problems:
            raise DomainError(
                ErrorCode.VALIDATION_ERROR, "Cette mission ne cherche pas de solutions."
            )
        if not queries:
            raise DomainError(ErrorCode.VALIDATION_ERROR, NOT_RUN_YET)
        # Recherches echouees : chaque probleme est rendu « sans source exploitable ».
        sources_hash = sources_fingerprint(sources)
        if (
            latest
            and not force
            and latest.sources_hash == sources_hash
            and all(p.available for p in latest.problems)
        ):
            return latest
        profile = build_profile(
            [project.title, project.idea, *project.constraints, *project.facts],
            minutes_per_day=project.available_minutes_per_day,
            target_outcome=project.target_outcome,
        )
        subject_by_query = {q.id: q.subject for q in queries}
        angle_by_query = {q.id: q.text for q in queries}
        started = time.monotonic()

        def solve(problem: ProblemTarget) -> ProblemSolutions:
            pool = [
                s for s in sources
                if subject_by_query.get(s.query_id) == problem.label and not s.suspicious
                and not is_promotional(f"{s.title} {s.excerpt}")
            ][:MAX_SOURCES_PER_IDEA]  # fmt: skip
            aliases = {f"S{i}": s.id for i, s in enumerate(pool, 1)}
            by_id = {s.id: s for s in pool}
            if not pool:
                return ProblemSolutions(
                    problem=problem, unknowns=["Aucune source exploitable : aucune solution "
                                               "n'est proposée sans preuve."],
                )  # fmt: skip
            payload = {
                "probleme": problem.model_dump(mode="json", exclude={"source_ids"}),
                "projet": {"titre": project.title, "idee": project.idea,
                           "contraintes": project.constraints},
                "profil": profile,
                "sources": [
                    {
                        "id": f"S{i}",
                        "domaine": s.domain,
                        "titre": s.title,
                        "extrait": s.excerpt or "(référence seule : contenu non conservé)",
                        "recherche": angle_by_query.get(s.query_id),
                    }
                    for i, s in enumerate(pool, 1)
                ],
            }  # fmt: skip
            try:
                draft = analyst.propose_solutions(payload)
            except DomainError as exc:
                return ProblemSolutions(
                    problem=problem, available=False, source_count=len(pool),
                    unknowns=[f"Solutions indisponibles pour le moment ({exc.user_message})"],
                )  # fmt: skip
            return validate_solutions(
                draft, problem=problem, aliases=aliases, sources=by_id,
                markets=mission.scope.markets, simulated=mission.simulated,
            )  # fmt: skip

        # Finalisation : les problemes sont independants et traites en parallele.
        self._notify(progress, f"Recherche de solutions pour {len(mission.scope.problems)} "
                               "problème(s)")  # fmt: skip
        problems = self._parallel(
            solve, list(mission.scope.problems), label="Problèmes traités", progress=progress
        )
        self.last_timings = {"solutions": round(time.monotonic() - started, 2)}
        plan = SolutionPlan(
            id=new_id("rsp"), mission_id=mission_id, user_id=user_id, created_at=now,
            problems=problems, sources_hash=sources_hash, simulated=mission.simulated,
        )  # fmt: skip
        with self._write() as repo:
            research = ResearchRepository(repo.conn)
            research.get_mission(user_id, mission_id)
            research.insert_solutions(plan)
            self._journal(repo, mission, EventType.RESEARCH_SOLUTIONS_CREATED, now,
                          plan_id=plan.id, problems=len(problems),
                          removed=plan.removed_count)  # fmt: skip
        return plan

    # --- journal -------------------------------------------------------------------------
    @staticmethod
    def _journal(
        repo: SqliteRepository,
        mission: ResearchMission,
        event_type: EventType,
        now: datetime,
        **payload: Any,
    ) -> None:
        repo.insert_event(
            make_event(
                mission.user_id,
                event_type,
                now=now,
                project_id=mission.scope.project_ids[0],
                payload={"mission_id": mission.id, **payload},
            )
        )
