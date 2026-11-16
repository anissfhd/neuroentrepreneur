"""Racine de composition : assemble base, horloge et services (ARCHITECTURE section 2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from neurocoach.application.base import ServiceSettings
from neurocoach.application.export import DataService
from neurocoach.application.pending_actions import PendingActionService
from neurocoach.application.ports import ConversationStore, NullConversationStore
from neurocoach.application.research_service import ResearchService
from neurocoach.application.services import CoachService
from neurocoach.config import Settings
from neurocoach.domain.clock import Clock
from neurocoach.infra.clock import SystemClock
from neurocoach.infra.db import Database
from neurocoach.infra.search_providers import build_research_registry


@dataclass(frozen=True)
class Application:
    settings: Settings
    database: Database
    clock: Clock
    coach: CoachService
    actions: PendingActionService
    data: DataService
    research: ResearchService


def build_application(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    conversations: ConversationStore | None = None,
) -> Application:
    settings = settings or Settings.from_env()
    database = Database(settings.business_db_path)
    database.migrate()
    clock = clock or SystemClock()
    # Sans checkpointer (tests du domaine), aucun message n'est conserve.
    conversations = conversations or NullConversationStore()
    service_settings = ServiceSettings(
        pending_action_ttl_minutes=settings.pending_action_ttl_minutes,
        default_timezone=settings.default_timezone,
    )
    args = (database, clock, service_settings, conversations)
    return Application(
        settings=settings,
        database=database,
        clock=clock,
        coach=CoachService(*args),
        actions=PendingActionService(*args),
        data=DataService(*args),
        research=ResearchService(
            *args,
            registry=build_research_registry(settings),
            parallelism=settings.research_parallelism,
        ),
    )


@dataclass(frozen=True)
class CoachRuntime:
    app: Application
    checkpointer: Any
    graph: Any
    agent: Any
    llm: Any
    # M3 : configuration des modeles reellement chargee (``None`` si le fournisseur est
    # injecte, par exemple par un test ou le harnais d'evaluation).
    llm_config: Any = None


def build_coach_runtime(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    llm: Any = None,
) -> CoachRuntime:
    """Application complete : services, checkpointer distinct, graphe et lanceur (phase 2).

    Les imports sont locaux pour que le domaine et les services restent utilisables sans les
    extras ``agent`` (D-30).
    """
    from neurocoach.agent.graph import build_coach_graph
    from neurocoach.agent.llm import build_role_providers
    from neurocoach.agent.runner import CoachAgent
    from neurocoach.domain.clock import local_today
    from neurocoach.infra.checkpoint import SqliteConversationStore, open_checkpointer
    from neurocoach.infra.llm_history import record_if_changed
    from neurocoach.llm_catalog import loaded_config

    settings = settings or Settings.from_env()
    loaded = None
    if llm is None:
        # M2 : fournisseur par role, valide avant toute construction. Sans variable de role,
        # strictement le fournisseur d'avant M2. Une erreur arrete le demarrage, sans appel.
        today = local_today((clock or SystemClock()).now(), settings.default_timezone)
        llm = build_role_providers(settings, today=today)
        loaded = loaded_config(settings)
        # D-83 : plafond de depense de session, seulement s'il est demande au lancement.
        from neurocoach.agent.spending import capped

        llm = capped(
            llm,
            models=tuple(a.model for a in loaded.assignments.values() if a.provider != "fake"),
            output_tokens=max(
                settings.llm_max_output_tokens, settings.llm_max_output_tokens_analysis
            ),
        )
    checkpointer = open_checkpointer(settings.checkpoint_db_path)
    app = build_application(
        settings, clock=clock, conversations=SqliteConversationStore(checkpointer)
    )
    if loaded is not None:
        # M3 : trace de la configuration chargee, une ligne par role modifie seulement.
        record_if_changed(
            app.database,
            loaded.triples(),
            catalog_version=loaded.catalog_version,
            fingerprint=loaded.fingerprint,
            now=app.clock.now(),
        )
    provider = llm
    graph = build_coach_graph(app, provider, checkpointer)
    return CoachRuntime(
        app, checkpointer, graph, CoachAgent(app, graph, provider), provider, loaded
    )
