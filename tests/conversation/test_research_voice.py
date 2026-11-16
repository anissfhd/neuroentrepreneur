"""R5 (D-72) : avis, forums et retours d'experience dans les missions, l'analyse et le coach.

Faux modele, fournisseur simule et doublure HTTP : aucun appel reseau ni payant.
"""

from __future__ import annotations

import json
import socket

import httpx
import pytest

from factories import ALICE
from neurocoach.agent.research_analyst import LLMResearchAnalyst
from neurocoach.application.research_service import MissionRequest
from neurocoach.domain.analysis import IdeaAnalysisDraft
from neurocoach.domain.models import EventType
from neurocoach.domain.research import ResearchCategory
from neurocoach.infra.search_providers import build_research_registry
from neurocoach.research.fake import FakeResearchProvider

C = ResearchCategory
VOICE = [C.REVIEWS, C.TESTIMONIALS, C.PROBLEMS]


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("connexion reseau tentee")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def provider(coach):
    fake = FakeResearchProvider()
    coach.app.research.registry = build_research_registry(simulation=True, extra={"fake": fake})
    return fake


@pytest.fixture
def project(coach, provider):
    return coach.app.coach.create_project(ALICE, "Galettes", "Vendre des galettes maison à Lyon")


def run(coach, project, categories=VOICE):
    request = MissionRequest(project_ids=[project.id], categories=categories)
    mission = coach.app.research.propose_mission(ALICE, request)
    coach.app.research.approve_mission(ALICE, mission.id, mission.scope_hash)
    return mission, coach.app.research.run_mission(ALICE, mission.id)


def analyse(coach, mission):
    return coach.app.research.analyze_mission(ALICE, mission.id, LLMResearchAnalyst(coach.llm))


# --- recherches ciblees et sites non autorises -----------------------------------------------


def test_testimonial_queries_are_targeted_and_exclude_restricted_sites(coach, project, provider):
    mission, report = run(coach, project)
    texts = {q.category: q.text for q in report.queries}
    assert "retour d'expérience forum témoignage" in texts[C.TESTIMONIALS]
    assert all("reddit.com" in call["exclude"] for call in provider.calls)
    assert all("trustpilot.com" in call["exclude"] for call in provider.calls)
    preview = " ".join(mission.preview)
    assert "Reddit : non consulté" in preview and "aucun contournement" in preview


def test_results_from_restricted_sites_are_never_stored(coach, project):
    _, report = run(coach, project)
    assert not [s for s in report.sources if "reddit" in s.domain]
    testimonials = next(q for q in report.queries if q.category is C.TESTIMONIALS)
    assert testimonials.blocked_count == 1
    events = [e for e in coach.app.coach.list_events(ALICE)
              if e.type is EventType.RESEARCH_QUERY_RUN]  # fmt: skip
    assert sum(e.payload["blocked"] for e in events) == 1


def test_price_only_mission_does_not_mention_reviews_policy(coach, project):
    request = MissionRequest(project_ids=[project.id], categories=[C.PRICES])
    draft = coach.app.research.prepare_mission(ALICE, request)
    assert not any("Reddit" in line for line in draft.preview)


def test_real_adapters_send_exclusions_and_results_are_filtered(coach, project, monkeypatch,
                                                                tmp_path):  # fmt: skip
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_RESEARCH", raising=False)
    bodies = []

    def server(request):
        body = json.loads(request.content)
        bodies.append((request.url.host, body))
        return httpx.Response(200, json={
            "results": [
                {"title": "Fil Reddit", "url": "https://www.reddit.com/r/lyon/x",
                 "content": "Discussion sur les galettes, livraison trop lente."},
                {"title": "Avis", "url": "https://fr.trustpilot.com/review/x",
                 "content": "Délais trop longs."},
                {"title": "Forum cuisine", "url": "https://forum-cuisine.example/t/1",
                 "content": "J'ai attendu longtemps ma commande, livraison trop lente."},
            ],
            "usage": {"credits": 1},
        })  # fmt: skip

    coach.app.research.registry = build_research_registry(
        environ={"TAVILY_API_KEY": "tvly-TEST-r5"}, dotenv_path=tmp_path / "absent.env",
        client=httpx.Client(transport=httpx.MockTransport(server)),
    )  # fmt: skip
    _, report = run(coach, project, categories=[C.TESTIMONIALS])
    assert "reddit.com" in bodies[0][1]["exclude_domains"]
    assert [s.domain for s in report.sources] == ["forum-cuisine.example"]
    assert report.queries[0].blocked_count == 2


# --- integration a l'analyse R4 -------------------------------------------------------------


def test_analysis_separates_testimonies_from_corroborated_trends(coach, project):
    mission, _ = run(coach, project)
    analysis = analyse(coach, mission)
    idea = analysis.ideas[0]
    voice = {t.theme: t for t in idea.voice.themes}
    assert voice["delais"].status == "corrobore" and voice["delais"].sentiment == "negatif"
    assert voice["qualite"].sentiment == "partage"  # avis contradictoires
    assert voice["prix"].status == "isole"
    # Le faux modele presente tout comme « tendance » : le code ramene les cas d'un seul site.
    scopes = {p.theme: p.scope for p in idea.pain_points}
    assert scopes["Délais et livraison"] == "tendance"
    assert scopes["Disponibilité de l'offre"] == "temoignage"
    assert any("un seul site : témoignage individuel" in r for r in idea.removed)
    # Avis promotionnel et doublon : signales, jamais comptes.
    assert idea.voice.promotional and idea.voice.duplicates == 1
    notes = " ".join(idea.voice.notes)
    assert "promotionnelle" in notes and "Reddit non consulté" in notes
    assert "sites exclus écarté" in notes


def test_promotional_review_never_reaches_the_model(coach, project, fake_llm):
    mission, _ = run(coach, project)
    fake_llm.calls.clear()
    analyse(coach, mission)
    content = next(m[-1]["content"] for t, m in fake_llm.calls if t == "research_analysis")
    assert "Code promo" not in content and "Meilleur produit au monde" not in content
    payload = json.loads(content.split("<donnees_projet>\n", 1)[1].split("\n</donnees_projet>")[0])
    assert payload["voix_clients"] and payload["avis_ecartes"] == []  # deja retire des sources


def test_invented_testimonials_are_removed(coach, project, fake_llm):
    mission, _ = run(coach, project)
    fake_llm.script("research_analysis", IdeaAnalysisDraft.model_validate({
        "summary": "Résumé.",
        "pain_points": [
            {"theme": "Prix", "statement": "Les clients trouvent tout trop cher.",
             "scope": "tendance", "sources": ["S1", "S2"],
             "quote": "Tout est beaucoup trop cher, je ne reviendrai pas."},
            {"theme": "Délais", "statement": "Attente de 45 jours.", "scope": "temoignage",
             "sources": ["S1"], "quote": "(Simulation) Plusieurs avis fictifs saluent la "
                                         "qualité mais regrettent les délais de livraison."},
        ],
    }))  # fmt: skip
    idea = analyse(coach, mission).ideas[0]
    assert idea.pain_points == []
    assert any("absent des avis cités" in r for r in idea.removed)
    assert any("chiffre non sourcé" in r for r in idea.removed)


def test_insufficient_reviews_are_reported(coach):
    coach.app.research.registry = build_research_registry(
        simulation=True, extra={"fake": FakeResearchProvider(mode="empty")}
    )
    project = coach.app.coach.create_project(ALICE, "Galettes", "Vendre des galettes à Lyon")
    mission, _ = run(coach, project)
    idea = analyse(coach, mission).ideas[0]
    assert idea.voice.themes == []
    assert "Aucun avis ni témoignage exploitable" in " ".join(idea.voice.notes)


def test_rendering_shows_sources_status_and_limits(coach, project):
    say = coach.agent.send_message
    say(ALICE, project.id, "Que disent les clients sur les forums ?")
    mission = coach.agent.research_pending(ALICE, project.id)
    assert mission.scope.categories == [C.TESTIMONIALS]
    coach.agent.approve_research(ALICE, project.id, mission.id, mission.scope_hash)
    reply = say(ALICE, project.id, "analyse").reply.replace("\\", "")
    assert (
        "Ce que disent les clients : Délais et livraison (négatif) : tendance corroborée" in reply
    )
    assert "Limites des avis" in reply and "Reddit non consulté" in reply
    assert "Frustrations et attentes (lecture du coach)" in reply


def test_coach_follow_up_receives_customer_voice(coach, project, fake_llm):
    mission, _ = run(coach, project)
    coach.app.research.analyze_mission(ALICE, mission.id, LLMResearchAnalyst(coach.llm))
    found = coach.app.research.project_analysis(ALICE, project.id)
    from neurocoach.application.research_format import analysis_facts

    facts = analysis_facts(*found)
    voix = facts["idees"][0]["voix_clients"]
    assert {v["statut"] for v in voix} >= {"tendance corroborée", "témoignage individuel"}
    assert facts["idees"][0]["frustrations"]


def test_customer_problems_are_ready_for_r6(coach, project):
    mission, _ = run(coach, project)
    idea = analyse(coach, mission).ideas[0]
    problems = idea.customer_problems()
    assert problems[0].status == "corrobore" and problems[0].is_problem
    assert all(t.sentiment != "positif" for t in problems)


def test_compare_conversation_includes_testimonials(coach, provider):
    project = coach.app.coach.create_project(ALICE, "Choix", "")
    say = coach.agent.send_message
    say(ALICE, project.id, "J'hésite entre deux idées")
    say(ALICE, project.id, "Des bougies parfumées\nUn food truck de galettes")
    say(ALICE, project.id, "je passe")
    turn = say(ALICE, project.id, "France")
    assert "retours d'expérience" in turn.reply


def test_trend_claimed_from_vendor_testimonials_is_downgraded(coach):
    """Finalisation : une « tendance » appuyee sur des avis de vendeurs est ramenee a un
    temoignage, avec la raison."""
    from neurocoach.domain.analysis import validate_idea_analysis
    from neurocoach.domain.research import SourceRecord
    from neurocoach.domain.voice import analyze_voice

    def record(sid, domain, excerpt):
        return SourceRecord(
            id=sid, query_id="q", category=C.REVIEWS, provider="tavily",
            url=f"https://{domain}/x", domain=domain, title="Avis", excerpt=excerpt,
            retrieved_at=coach.app.clock.now(), content_hash=sid, simulated=False,
        )  # fmt: skip

    sources = {
        "a": record("a", "bougies-clea.example", "5/5 Livraison rapide. 5/5 Parfait."),
        "b": record("b", "bougies-lys.example", "5/5 Livraison rapide et soignée. 4/5 Joli."),
    }
    voice = analyze_voice(list(sources.values()), offer="bougies")
    draft = IdeaAnalysisDraft.model_validate(
        {
            "summary": "Résumé.",
            "pain_points": [
                {"theme": "Délais", "statement": "Les clients aiment la livraison rapide.",
                 "scope": "tendance", "sources": ["S1", "S2"], "quote": "5/5 Livraison rapide."}
            ],
        }
    )  # fmt: skip
    idea = validate_idea_analysis(
        draft, idea="Bougies", aliases={"S1": "a", "S2": "b"}, sources=sources, profile={},
        markets=[], voice=voice,
    )  # fmt: skip
    assert idea.pain_points[0].scope == "temoignage"
    assert any("publiés par des vendeurs ne font pas une tendance" in r for r in idea.removed)


def test_summary_labels_vendor_content_in_reviews(coach, project):
    from neurocoach.application.research_format import format_mission_summary

    _, report = run(coach, project, categories=[C.REVIEWS, C.TESTIMONIALS])
    summary = format_mission_summary(report).replace("\\", "")
    assert "Avis" in summary
    # Sources fictives d'avis : forums, comparatifs et blogs ; aucune n'est un vendeur.
    assert "contenu publié par un vendeur" not in summary
    shops = [s.model_copy(update={"domain": "bougies-maison.example"}) for s in report.sources]
    vendor = report.model_copy(update={"sources": shops})
    assert "contenu publié par un vendeur" in format_mission_summary(vendor)
