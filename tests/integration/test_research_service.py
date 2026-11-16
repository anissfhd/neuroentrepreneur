"""R1 du Business Researcher (D-68) : mission approuvee, execution dans le perimetre,
budget, journal, stockage, isolation, export et effacement. Entierement hors ligne."""

from __future__ import annotations

import json
import socket
from datetime import timedelta

import pytest

from factories import NOW
from neurocoach.application.research_service import (
    OUT_OF_BUDGET,
    MissionRequest,
    ResearchService,
)
from neurocoach.bootstrap import build_application
from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.models import EventType
from neurocoach.domain.research import (
    MARKET_QUESTION,
    MissionStatus,
    Nature,
    ResearchCategory,
)
from neurocoach.infra.search_providers import build_research_registry
from neurocoach.research.fake import FakeResearchProvider
from neurocoach.research.ports import ProviderRegistry, load_provider_catalog

C = ResearchCategory
IDEA = "Je veux vendre des galettes maison sur les marchés de Lyon"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Aucune connexion possible pendant ces tests : R1 est entierement simule."""

    def refuse(*args, **kwargs):
        raise AssertionError("connexion reseau tentee")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def project(app, alice):
    return app.coach.create_project(alice, "Galettes", IDEA)


def approved(app, user, project_id, **request):
    mission = app.research.propose_mission(
        user, MissionRequest(project_ids=[project_id], **request)
    )
    return app.research.approve_mission(user, mission.id, mission.scope_hash)


def events(app, user, event_type):
    return [e for e in app.coach.list_events(user) if e.type is event_type]


def counts(app, mission_id):
    with app.database.transaction(write=False) as conn:
        return {
            table: conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE mission_id = ?", (mission_id,)
            ).fetchone()[0]
            for table in ("research_queries", "research_sources", "research_findings")
        }


# --- preparation : rien d'enregistre, une question au plus ----------------------------------


def test_prepare_uses_project_information_without_question(app, alice, project):
    draft = app.research.prepare_mission(alice, MissionRequest(project_ids=[project.id]))
    assert draft.question is None
    assert draft.scope.markets == ["France"]
    assert draft.scope.simulated is True
    preview = "\n".join(draft.preview)
    for expected in ("Objectif", "Projet(s) : Galettes", "Marché(s) : France", "marché",
                     "concurrence", "prix", "avis", "problèmes", "solutions",
                     "Recherche simulée", "Données transmises", "Budget maximal : 0.40 $",
                     "Hypothèse : cible supposée : particuliers", "Requête (prix"):  # fmt: skip
        assert expected in preview
    assert "Alice" not in preview.split("Requête", 1)[1]
    assert app.research.list_missions(alice) == []


def test_single_question_when_market_missing(app, alice):
    vague = app.coach.create_project(alice, "Bougies", "Je veux vendre des bougies")
    draft = app.research.prepare_mission(alice, MissionRequest(project_ids=[vague.id]))
    assert draft.question == MARKET_QUESTION and draft.scope is None
    with pytest.raises(DomainError):
        app.research.propose_mission(alice, MissionRequest(project_ids=[vague.id]))
    # Sans categorie dependant du pays : pas de question, recherche non specifique.
    general = app.research.prepare_mission(
        alice, MissionRequest(project_ids=[vague.id], categories=[C.REVIEWS, C.SOLUTIONS])
    )
    assert general.question is None and general.scope.markets == []
    answered = app.research.prepare_mission(
        alice, MissionRequest(project_ids=[vague.id], markets=["Maroc"])
    )
    assert answered.question is None and answered.scope.markets == ["Maroc"]


def test_planned_cost_must_fit_budget(app, alice, project):
    with pytest.raises(DomainError) as error:
        app.research.prepare_mission(
            alice, MissionRequest(project_ids=[project.id], max_budget_usd=0.01)
        )
    assert "supérieur au budget" in error.value.detail


def test_another_users_project_is_not_found(app, alice, bruno, project):
    with pytest.raises(DomainError) as error:
        app.research.prepare_mission(bruno, MissionRequest(project_ids=[project.id]))
    assert error.value.code is ErrorCode.NOT_FOUND


# --- proposition et approbation explicite ---------------------------------------------------


def test_nothing_runs_before_approval(app, alice, project):
    mission = app.research.propose_mission(alice, MissionRequest(project_ids=[project.id]))
    assert mission.status is MissionStatus.PROPOSED
    with pytest.raises(DomainError) as error:
        app.research.run_mission(alice, mission.id)
    assert "pas approuvée" in error.value.detail
    assert counts(app, mission.id)["research_queries"] == 0
    assert len(events(app, alice, EventType.RESEARCH_MISSION_PROPOSED)) == 1


def test_approval_is_single_use(app, alice, project):
    mission = app.research.propose_mission(alice, MissionRequest(project_ids=[project.id]))
    first = app.research.approve_mission(alice, mission.id, mission.scope_hash)
    assert first.status is MissionStatus.APPROVED
    assert first.valid_until == NOW + timedelta(days=7)
    with pytest.raises(DomainError) as error:  # double clic
        app.research.approve_mission(alice, mission.id, mission.scope_hash)
    assert error.value.code is ErrorCode.ACTION_ALREADY_DECIDED
    assert len(events(app, alice, EventType.RESEARCH_MISSION_APPROVED)) == 1


def test_approval_must_match_the_shown_preview(app, alice, project):
    mission = app.research.propose_mission(alice, MissionRequest(project_ids=[project.id]))
    with pytest.raises(DomainError) as error:
        app.research.approve_mission(alice, mission.id, "0" * 64)
    assert error.value.code is ErrorCode.VERSION_CONFLICT
    assert app.research.list_missions(alice)[0].status is MissionStatus.PROPOSED


def test_expired_proposal_cannot_be_approved(app, alice, project, clock):
    mission = app.research.propose_mission(alice, MissionRequest(project_ids=[project.id]))
    clock.advance(timedelta(minutes=16))
    with pytest.raises(DomainError) as error:
        app.research.approve_mission(alice, mission.id, mission.scope_hash)
    assert error.value.code is ErrorCode.ACTION_EXPIRED
    assert app.research.list_missions(alice)[0].status is MissionStatus.EXPIRED
    assert len(events(app, alice, EventType.RESEARCH_MISSION_EXPIRED)) == 1


def test_other_user_cannot_approve(app, alice, bruno, project):
    mission = app.research.propose_mission(alice, MissionRequest(project_ids=[project.id]))
    with pytest.raises(DomainError) as error:
        app.research.approve_mission(bruno, mission.id, mission.scope_hash)
    assert error.value.code is ErrorCode.NOT_FOUND


def test_cancel_proposal_and_revoke_authorization(app, alice, project):
    mission = app.research.propose_mission(alice, MissionRequest(project_ids=[project.id]))
    assert app.research.cancel_mission(alice, mission.id).status is MissionStatus.CANCELLED
    with pytest.raises(DomainError):
        app.research.approve_mission(alice, mission.id, mission.scope_hash)
    live = approved(app, alice, project.id)
    assert app.research.cancel_mission(alice, live.id).status is MissionStatus.CANCELLED
    with pytest.raises(DomainError):
        app.research.run_mission(alice, live.id)
    with pytest.raises(DomainError) as error:
        app.research.cancel_mission(alice, live.id)
    assert error.value.code is ErrorCode.ACTION_ALREADY_DECIDED


def test_research_proposal_does_not_supersede_a_pending_plan(app, alice, project):
    """Les missions vivent dans leurs propres tables : une proposition de plan en attente
    n'est ni remplacee ni annulee (contrairement a ``PendingActionService._create``)."""
    action = app.actions.request_project_deletion(alice, project.id)
    approved(app, alice, project.id)
    assert app.actions.get_pending(alice, project.id).id == action.id


# --- execution dans le perimetre ------------------------------------------------------------


def test_run_mission_executes_all_planned_queries_without_new_approval(app, alice, project):
    before = app.coach.get_project(alice, project.id)
    mission = approved(app, alice, project.id)
    report = app.research.run_mission(alice, mission.id)
    assert len(report.queries) == 6 and all(q.status == "done" for q in report.queries)
    assert report.mission.queries_used == 6
    assert report.mission.spent_usd == pytest.approx(0.048)
    assert report.simulated and report.authorization_active
    assert all(s.simulated and s.domain.endswith(".example") for s in report.sources)
    assert all(len(s.excerpt) <= 500 for s in report.sources)
    labels = {c.category: c for c in report.categories}
    assert all(not c.no_data for c in report.categories)
    prices = labels[C.PRICES].findings
    assert len(prices) == 2 and all("contradictoire" in f.flags for f in prices)
    assert "date inconnue" in labels[C.REVIEWS].findings[0].flags
    assert "autre marché" in labels[C.PROBLEMS].findings[0].flags
    solutions = labels[C.SOLUTIONS].findings[0]
    assert "Ignore" not in solutions.statement
    assert "source contenant une consigne (ignorée)" in solutions.flags
    assert all("simulé" in f.flags for c in report.categories for f in c.findings)
    # Une recherche n'ecrit jamais dans le projet ni les taches.
    assert app.coach.get_project(alice, project.id) == before
    assert app.coach.list_tasks(alice, project.id) == []
    assert len(events(app, alice, EventType.RESEARCH_QUERY_RUN)) == 6
    # Relancer ne refait pas les recherches deja faites.
    again = app.research.run_mission(alice, mission.id)
    assert len(again.queries) == 6


def test_additional_query_in_scope_needs_no_new_approval(app, alice, project):
    mission = approved(app, alice, project.id)
    record = app.research.run_query(
        alice, mission.id, project_id=project.id, category=C.PRICES, provider="fake",
        market="France", text="galettes bretonnes prix alice@exemple.fr Alice",
    )  # fmt: skip
    assert record.status == "done"
    assert "@" not in record.text and "Alice" not in record.text
    assert len(events(app, alice, EventType.RESEARCH_MISSION_APPROVED)) == 1


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        ({"category": C.COMPETITION}, "concurrence"),
        ({"market": "Maroc"}, "Maroc"),
    ],
)
def test_out_of_scope_query_is_refused_and_journaled(app, alice, project, change, fragment):
    mission = approved(app, alice, project.id, categories=[C.PRICES, C.REVIEWS])
    args = {"project_id": project.id, "category": C.PRICES, "provider": "fake",
            "market": "France", "text": "galettes prix"}  # fmt: skip
    args.update(change)
    with pytest.raises(DomainError) as error:
        app.research.run_query(alice, mission.id, **args)
    assert fragment in error.value.detail
    assert counts(app, mission.id)["research_queries"] == 0
    refused = events(app, alice, EventType.RESEARCH_QUERY_REFUSED)
    assert len(refused) == 1 and fragment in refused[0].payload["reason"]


def test_other_project_is_out_of_scope(app, alice, project):
    other = app.coach.create_project(alice, "Autre", "Bougies à Paris")
    mission = approved(app, alice, project.id)
    with pytest.raises(DomainError) as error:
        app.research.run_query(alice, mission.id, project_id=other.id, category=C.PRICES,
                               provider="fake", market="France", text="bougies prix")  # fmt: skip
    assert "projet" in error.value.detail


def test_budget_is_checked_before_each_query(app, alice, project):
    # 6 recherches prevues a 0,008 $ : budget exact 0,048 $, aucune marge.
    mission = approved(app, alice, project.id, max_budget_usd=0.048)
    report = app.research.run_mission(alice, mission.id)
    assert report.mission.queries_used == 6
    with pytest.raises(DomainError) as error:
        app.research.run_query(alice, mission.id, project_id=project.id, category=C.PRICES,
                               provider="fake", market="France", text="galettes prix")  # fmt: skip
    assert error.value.detail == OUT_OF_BUDGET
    assert app.research.mission_report(alice, mission.id).mission.spent_usd <= 0.048 + 1e-9


def test_query_quota_is_enforced(app, alice, project):
    mission = approved(app, alice, project.id, categories=[C.PRICES], max_queries=1)
    app.research.run_mission(alice, mission.id)
    with pytest.raises(DomainError) as error:
        app.research.run_query(alice, mission.id, project_id=project.id, category=C.PRICES,
                               provider="fake", market="France", text="galettes prix")  # fmt: skip
    assert error.value.detail == OUT_OF_BUDGET


def test_authorization_lapses_after_validity(app, alice, project, clock):
    mission = approved(app, alice, project.id, categories=[C.PRICES], validity_days=1)
    app.research.run_mission(alice, mission.id)
    clock.advance(timedelta(days=1, seconds=1))
    with pytest.raises(DomainError) as error:
        app.research.run_query(alice, mission.id, project_id=project.id, category=C.PRICES,
                               provider="fake", market="France", text="galettes prix")  # fmt: skip
    assert error.value.code is ErrorCode.ACTION_EXPIRED
    closed = app.research.mission_report(alice, mission.id)
    assert closed.mission.status is MissionStatus.COMPLETED
    assert not closed.authorization_active
    assert closed.categories[0].findings  # les resultats restent consultables


def test_close_mission_keeps_results(app, alice, project):
    mission = approved(app, alice, project.id, categories=[C.PRICES])
    app.research.run_mission(alice, mission.id)
    assert app.research.close_mission(alice, mission.id).status is MissionStatus.COMPLETED
    with pytest.raises(DomainError):
        app.research.close_mission(alice, mission.id)
    assert counts(app, mission.id)["research_sources"] == 2


# --- extension : nouvelle approbation -------------------------------------------------------


def test_extension_requires_a_new_approval(app, alice, project):
    mission = approved(app, alice, project.id, categories=[C.PRICES])
    app.research.run_mission(alice, mission.id)
    extension = app.research.extend_mission(
        alice, mission.id,
        MissionRequest(project_ids=[project.id], categories=[C.PRICES, C.COMPETITION],
                       markets=["France", "Maroc"], max_budget_usd=0.8),
    )  # fmt: skip
    assert extension.status is MissionStatus.PROPOSED
    assert extension.parent_mission_id == mission.id
    head = extension.preview[0]
    assert head.startswith("Extension de la mission précédente")
    assert "concurrence" in head and "Maroc" in head and "0.4 → 0.8" in head
    # Tant que l'extension n'est pas approuvee, l'ancien perimetre s'applique.
    with pytest.raises(DomainError):
        app.research.run_query(alice, mission.id, project_id=project.id,
                               category=C.COMPETITION, provider="fake", market="France",
                               text="galettes concurrents")  # fmt: skip
    app.research.approve_mission(alice, extension.id, extension.scope_hash)
    assert app.research.mission_report(alice, mission.id).mission.status is (
        MissionStatus.SUPERSEDED
    )
    report = app.research.run_mission(alice, extension.id)
    assert {q.market for q in report.queries} >= {"France", "Maroc"}


# --- fournisseurs : simules uniquement, pannes et absence de resultats ----------------------


def service_with(app, provider) -> ResearchService:
    registry = build_research_registry(simulation=True, extra={"fake": provider})
    return ResearchService(app.database, app.clock, registry=registry)


def test_provider_failure_gives_partial_mission(app, alice, project):
    service = service_with(app, FakeResearchProvider(mode="fail"))
    mission = service.propose_mission(alice, MissionRequest(project_ids=[project.id],
                                                            categories=[C.PRICES]))  # fmt: skip
    service.approve_mission(alice, mission.id, mission.scope_hash)
    report = service.run_mission(alice, mission.id)
    assert report.queries[0].status == "failed"
    assert report.queries[0].error == "ConnectionError"
    assert report.sources == []
    assert service.close_mission(alice, mission.id).status is MissionStatus.PARTIAL


def test_no_results_means_no_data_and_nothing_invented(app, alice, project):
    service = service_with(app, FakeResearchProvider(mode="empty"))
    mission = service.propose_mission(alice, MissionRequest(project_ids=[project.id]))
    service.approve_mission(alice, mission.id, mission.scope_hash)
    report = service.run_mission(alice, mission.id)
    assert all(c.no_data and not c.findings for c in report.categories)
    assert report.hypotheses == ["cible supposée : particuliers"]


class _Disguised:
    """Doublure qui se dit reelle sous le nom du service simule."""

    name = "fake"
    simulated = False

    def search(self, query, *, category, market, max_results):  # pragma: no cover
        raise AssertionError("jamais appele")


def test_registry_refuses_disabled_and_mismatched_providers():
    registry = ProviderRegistry(load_provider_catalog())
    with pytest.raises(DomainError):
        registry.register(_Disguised())  # reel declare, simule au catalogue
    with pytest.raises(DomainError):
        registry.register(FakeResearchProvider(name="tavily"))  # simule declare, reel attendu
    with pytest.raises(DomainError):
        registry.register(FakeResearchProvider(name="reddit"))  # desactive
    with pytest.raises(DomainError):
        build_research_registry(simulation=True).get("exa")
    assert build_research_registry(simulation=True).names() == ["fake"]
    # Ni cle (verrou de test) ni simulation demandee : aucun service, rien de simule en douce.
    assert build_research_registry().names() == []


def test_catalog_activates_tavily_exa_and_keeps_reddit_and_forums_disabled():
    catalog = load_provider_catalog()
    assert catalog.usable() == ["fake", "tavily", "exa"]
    for name in ("tavily", "exa"):
        entry = catalog.entry(name)
        assert not entry.simulated and entry.monthly_cap_usd is not None
        assert str(entry.verified) == "2026-11-10"
    # Quotas locaux strictement inferieurs aux offres gratuites (1 000 credits ; 10 $).
    assert catalog.entry("tavily").monthly_cap_usd < 1000 * 0.008
    assert catalog.entry("exa").monthly_cap_usd < 10
    assert catalog.entry("exa").store_excerpts is False  # conditions d'Exa, §4.2(a)
    for name in ("reddit", "forums"):
        entry = catalog.entry(name)
        assert entry.status == "disabled"
        assert "conditions" in entry.terms or "autoris" in entry.terms
    with pytest.raises(DomainError):
        catalog.entry("google")


def test_unknown_provider_is_refused_before_any_reservation(app, alice, project):
    mission = approved(app, alice, project.id)
    args = {"project_id": project.id, "category": C.PRICES, "market": "France",
            "text": "galettes prix"}  # fmt: skip
    with pytest.raises(DomainError):
        app.research.run_query(alice, mission.id, provider="tavily", **args)
    assert app.research.mission_report(alice, mission.id).mission.queries_used == 0


# --- stockage : isolation, export, suppression ----------------------------------------------


def test_missions_are_isolated_per_user(app, alice, bruno, project):
    mission = approved(app, alice, project.id)
    app.research.run_mission(alice, mission.id)
    assert app.research.list_missions(bruno) == []
    for call in (app.research.mission_report, app.research.run_mission,
                 app.research.close_mission):  # fmt: skip
        with pytest.raises(DomainError) as error:
            call(bruno, mission.id)
        assert error.value.code is ErrorCode.NOT_FOUND


def test_export_includes_research_of_the_user_only(app, alice, bruno, project):
    mission = approved(app, alice, project.id, categories=[C.PRICES])
    app.research.run_mission(alice, mission.id)
    export = app.data.export_user_data(alice)
    [item] = export["research"]
    assert item["mission"]["id"] == mission.id
    assert len(item["queries"]) == 1 and len(item["sources"]) == 2
    assert {f["nature"] for f in item["findings"]} <= {n.value for n in Nature}
    assert app.data.export_user_data(bruno)["research"] == []
    assert mission.id not in json.dumps(app.data.export_user_data(bruno))


def test_project_deletion_removes_its_research(app, alice, project):
    mission = approved(app, alice, project.id, categories=[C.PRICES])
    app.research.run_mission(alice, mission.id)
    action = app.actions.request_project_deletion(alice, project.id)
    app.actions.confirm(alice, action.id)
    assert app.research.list_missions(alice) == []
    assert counts(app, mission.id) == {
        "research_queries": 0, "research_sources": 0, "research_findings": 0,
    }  # fmt: skip


def test_user_data_deletion_removes_research(app, alice, bruno, project):
    mission = approved(app, alice, project.id, categories=[C.PRICES])
    app.research.run_mission(alice, mission.id)
    kept = app.coach.create_project(bruno, "Bougies", "Bougies à Paris")
    other = approved(app, bruno, kept.id, categories=[C.PRICES])
    action = app.actions.request_user_data_deletion(alice)
    app.actions.confirm(alice, action.id)
    assert app.research.list_missions(alice) == []
    assert counts(app, mission.id)["research_sources"] == 0
    assert [m.id for m in app.research.list_missions(bruno)] == [other.id]


def test_research_survives_restart(settings, clock, alice):
    first = build_application(settings, clock=clock)
    first.coach.ensure_user(alice, "Alice (test)")
    project = first.coach.create_project(alice, "Galettes", IDEA)
    mission = approved(first, alice, project.id, categories=[C.PRICES])
    first.research.run_mission(alice, mission.id)
    second = build_application(settings, clock=clock)
    report = second.research.mission_report(alice, mission.id)
    assert report.mission.status is MissionStatus.APPROVED
    assert len(report.sources) == 2 and report.categories[0].findings
