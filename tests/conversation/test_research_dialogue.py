"""R3 (D-70) : recherche proposee depuis la conversation, approuvee par bouton uniquement.

Faux modele, fournisseur simule ou doublure HTTP : aucun appel reseau. Verifie la detection,
le recueil sans questions inutiles, la proposition, l'absence de recherche sans clic, la
continuite apres recherche, les erreurs et quotas, et l'isolation entre utilisateurs.
"""

from __future__ import annotations

import json
import socket
from datetime import timedelta

import httpx
import pytest

from factories import ALICE, BRUNO
from neurocoach.agent.research_dialogue import (
    ASK_CRITERIA,
    CANCELLED,
    NOT_ENABLED,
    OFFER,
    RESEARCH_WITH_BUTTON,
    detect_research_need,
    known_criteria,
    market_from_answer,
    parse_ideas,
)
from neurocoach.application.research_service import ResearchService
from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.research import MARKET_QUESTION, MissionStatus, ResearchCategory
from neurocoach.infra.search_providers import build_research_registry
from neurocoach.research.fake import FakeResearchProvider

C = ResearchCategory
FOUR = "J'ai quatre idées de business, mais je ne sais pas laquelle choisir."
IDEAS = (
    "Des bougies parfumées artisanales\n"
    "Un food truck de galettes\n"
    "Des cours de yoga en entreprise\n"
    "Une application de covoiturage scolaire"
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("connexion reseau tentee")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def fake_provider(coach):
    provider = FakeResearchProvider()
    coach.app.research.registry = build_research_registry(simulation=True, extra={"fake": provider})
    return provider


@pytest.fixture
def project(coach, fake_provider):
    return coach.app.coach.create_project(ALICE, "Choisir mon activité", "")


def say(coach, project, text, user=ALICE):
    return coach.agent.send_message(user, project.id, text)


def missions(coach, project, user=ALICE):
    return coach.app.research.list_missions(user, project.id)


def history(coach, project, user=ALICE):
    return [m["content"] for m in coach.agent.history(user, project.id)]


# --- detection (unitaire) --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "kind", "count"),
    [
        (FOUR, "compare", 4),
        ("J'hésite entre deux projets", "compare", 2),
        ("Je ne sais pas laquelle choisir entre mes idées", "compare", None),
        ("Qui sont mes concurrents à Lyon ?", "topic", None),
        ("À quel prix vendre ? Quels prix pratiquent les autres ?", "topic", None),
        ("Fais une recherche sur le web", "explicit", None),
    ],
)
def test_research_needs_are_detected_by_code(text, kind, count):
    need = detect_research_need(text)
    assert need is not None and need.kind == kind and need.count == count


@pytest.mark.parametrize(
    "text",
    [
        "J'ai terminé T1",
        "Je vends sur les marchés de Lyon le samedi",  # « marché » sans question de marché
        "Où en suis-je ?",
        "Bonjour",
    ],
)
def test_ordinary_messages_do_not_trigger_research(text):
    assert detect_research_need(text) is None


def test_topic_categories_follow_the_question():
    need = detect_research_need("Qui sont mes concurrents et quels prix pratiquent-ils ?")
    assert set(need.categories) == {C.COMPETITION, C.PRICES}


def test_idea_lists_are_parsed_without_guessing():
    assert len(parse_ideas(IDEAS)) == 4
    assert parse_ideas("1) des bougies 2) un food truck 3) du yoga") == [
        "des bougies", "un food truck", "du yoga",
    ]  # fmt: skip
    assert parse_ideas("des bougies; un food truck") == ["des bougies", "un food truck"]
    assert parse_ideas("Mes idées : des bougies parfumées, un food truck et du yoga en ligne") == [
        "des bougies parfumées", "un food truck", "du yoga en ligne",
    ]  # fmt: skip
    assert parse_ideas("Je veux vendre des bougies") == []


def test_market_and_criteria_answers():
    assert market_from_answer("En France") == ["France"]
    assert market_from_answer("je passe") == ["international"]
    assert market_from_answer("Québec") == ["Québec"]
    assert known_criteria(["Je veux démarrer vite avec un petit budget"]) == [
        "vite",
        "petit budget",
    ]


# --- recueil puis proposition, sans appel externe -------------------------------------------


def test_four_ideas_full_dialogue_until_proposal(coach, project, fake_provider):
    first = say(coach, project, FOUR)
    assert first.reply.startswith("Avec plaisir, comparons-les") and "4 idées" in first.reply
    assert first.reply.count("?") == 1
    second = say(coach, project, IDEAS)
    assert second.reply == ASK_CRITERIA
    third = say(coach, project, "Démarrer vite, avec un petit budget")
    assert third.reply.startswith(MARKET_QUESTION)
    fourth = say(coach, project, "France")
    assert fourth.reply.startswith("Voici la recherche que je vous propose")
    text = fourth.reply.replace("\\", "")
    expected = [
        "Idées comparées : 1) Des bougies parfumées artisanales",
        "4) Une application de covoiturage scolaire",
        "Marché(s) : France",
        "marché, concurrence, prix, avis, problèmes",
        "Fournisseurs : Recherche simulée",
        "Données transmises",
        "Budget maximal : 0.40 $",
        "selon : vite, petit budget",
    ]
    # D-84 : le detail est dans la fiche d'approbation, pas dans la conversation.
    [mission] = missions(coach, project)
    card = "\n".join(mission.preview).replace("\\", "")
    for item in expected:
        assert item in card, item
    for technical in ("Fournisseurs", "Données transmises", "Budget maximal"):
        assert technical not in text, technical
    assert "Approuver et lancer" in text
    assert mission.status is MissionStatus.PROPOSED
    assert mission.scope.subjects[0] == "Des bougies parfumées artisanales"
    assert {q.subject for q in mission.planned} == set(mission.scope.subjects)
    assert fake_provider.calls == []  # rien n'est parti
    assert coach.agent.research_pending(ALICE, project.id).id == mission.id


def test_known_information_is_never_asked_again(coach, fake_provider):
    project = coach.app.coach.create_project(
        ALICE, "Activité", "Je veux me lancer à Lyon, démarrer vite avec un petit budget"
    )
    turn = say(coach, project, f"J'hésite entre ces idées :\n{IDEAS}")
    # Idees dans le message, criteres et marche dans le projet : directement la proposition.
    assert turn.reply.startswith("Voici la recherche que je vous propose")
    assert len(missions(coach, project)) == 1
    assert "Marché(s) : France" in missions(coach, project)[0].preview


def test_ideas_given_earlier_in_the_conversation_are_reused(coach, project):
    say(coach, project, IDEAS)
    turn = say(coach, project, "Je ne sais pas laquelle choisir, avec peu de temps le soir")
    assert "Quelles sont vos" not in turn.reply
    assert turn.reply.startswith(MARKET_QUESTION)


def test_topic_question_with_known_market_proposes_directly(coach, fake_provider):
    project = coach.app.coach.create_project(ALICE, "Galettes", "Vendre des galettes à Lyon")
    turn = say(coach, project, "Qui sont mes concurrents ?")
    assert turn.reply.startswith("Voici la recherche que je vous propose (concurrence)")
    [mission] = missions(coach, project)
    assert mission.scope.categories == [C.COMPETITION]


def test_one_question_at_a_time_and_skip_is_respected(coach, project):
    say(coach, project, FOUR)
    say(coach, project, IDEAS)
    turn = say(coach, project, "je passe")
    assert turn.reply.count("?") == 1 and turn.reply.startswith(MARKET_QUESTION)
    final = say(coach, project, "je passe")
    assert final.reply.startswith("Voici la recherche")
    card = "\n".join(missions(coach, project)[0].preview)
    assert "international (non spécifique)" in card


def test_unrecognized_list_gets_one_reminder_then_stops(coach, project):
    say(coach, project, FOUR)
    reminder = say(coach, project, "bah")
    assert "une idée par ligne" in reminder.reply
    stop = say(coach, project, "toujours rien")
    assert "Dites-moi quand vous voulez comparer" in stop.reply
    assert missions(coach, project) == []


# --- consentement ---------------------------------------------------------------------------


def _proposed(coach, project):
    say(coach, project, FOUR)
    say(coach, project, IDEAS)
    say(coach, project, "Démarrer vite")
    say(coach, project, "France")
    return coach.agent.research_pending(ALICE, project.id)


def test_written_yes_never_launches_research(coach, project, fake_provider):
    mission = _proposed(coach, project)
    turn = say(coach, project, "oui")
    assert turn.reply is None and turn.notice == RESEARCH_WITH_BUTTON
    assert fake_provider.calls == []
    assert missions(coach, project)[0].status is MissionStatus.PROPOSED
    assert coach.agent.research_pending(ALICE, project.id).id == mission.id


def test_written_no_cancels_without_any_call(coach, project, fake_provider):
    _proposed(coach, project)
    turn = say(coach, project, "non")
    assert turn.reply == CANCELLED
    assert missions(coach, project)[0].status is MissionStatus.CANCELLED
    assert history(coach, project)[-2:] == ["non", CANCELLED]
    assert fake_provider.calls == []


def test_cancel_button(coach, project, fake_provider):
    mission = _proposed(coach, project)
    coach.agent.cancel_research(ALICE, project.id, mission.id)
    assert coach.agent.research_pending(ALICE, project.id) is None
    assert history(coach, project)[-1] == CANCELLED


def test_a_new_request_replaces_the_previous_proposal(coach, project):
    first = _proposed(coach, project)
    say(coach, project, "Et qui sont les concurrents pour la première ?")
    statuses = {m.id: m.status for m in missions(coach, project)}
    assert statuses[first.id] is MissionStatus.CANCELLED
    assert sum(s is MissionStatus.PROPOSED for s in statuses.values()) == 1


def test_other_user_cannot_approve(coach, project):
    mission = _proposed(coach, project)
    with pytest.raises(DomainError) as error:
        coach.agent.approve_research(BRUNO, project.id, mission.id, mission.scope_hash)
    assert error.value.code is ErrorCode.NOT_FOUND


def test_expired_proposal_then_relaunch_from_memory(coach, project, clock):
    mission = _proposed(coach, project)
    clock.advance(timedelta(minutes=16))
    with pytest.raises(DomainError) as error:
        coach.agent.approve_research(ALICE, project.id, mission.id, mission.scope_hash)
    assert error.value.code is ErrorCode.ACTION_EXPIRED
    turn = say(coach, project, "Relance la recherche")
    assert turn.reply.startswith("Voici la recherche")  # idees, criteres, marche reutilises
    assert coach.agent.research_pending(ALICE, project.id).scope.subjects == mission.scope.subjects


# --- apres approbation : resultats sources dans la conversation ------------------------------


def test_approval_runs_research_and_posts_sourced_summary(coach, project, fake_provider):
    mission = _proposed(coach, project)
    turn = coach.agent.approve_research(ALICE, project.id, mission.id, mission.scope_hash)
    assert len(fake_provider.calls) == len(mission.planned) == 24  # 4 idees x 6 categories
    summary = history(coach, project)[-1]
    assert summary == turn.reply
    clean = summary.replace("\\", "")
    assert "Résultats simulés, fictifs" in clean  # D-84 : sans journal d'execution
    # D-80 : l'analyse critique suit, sans mot-cle : idees, sources, niveau de preuve.
    assert "Voici mon analyse critique" not in clean
    assert "**1. Des bougies parfumées artisanales**" in clean
    assert "(source : " in clean and ".example" in clean
    assert "Niveau de preuve" in clean
    assert "Dites « analyse »" not in clean
    assert "Ignore les instructions" not in clean  # la consigne injectee n'est pas reprise
    # Jamais de transformation automatique en taches ni en plan.
    assert coach.app.coach.list_tasks(ALICE, project.id) == []
    assert coach.app.actions.get_pending(ALICE, project.id) is None
    assert coach.agent.research_pending(ALICE, project.id) is None
    with pytest.raises(DomainError):  # double clic
        coach.agent.approve_research(ALICE, project.id, mission.id, mission.scope_hash)


def test_conversation_continues_with_research_facts(coach, project, fake_llm):
    mission = _proposed(coach, project)
    coach.agent.approve_research(ALICE, project.id, mission.id, mission.scope_hash)
    # D-80 : l'analyse est deja dans le fil ; la suite est une reponse du coach.
    assert "Niveau de preuve" in history(coach, project)[-1]
    first = say(coach, project, "Merci, qu'en pensez-vous ?")
    assert first.reply
    fake_llm.calls.clear()
    turn = say(coach, project, "Et laquelle est la plus risquée ?")
    assert turn.reply
    reply_calls = [m for task, m in fake_llm.calls if task in ("coach_turn", "coach_reply")]
    assert reply_calls, "la suite de la conversation passe par la reponse du coach"
    data = reply_calls[-1][-1]["content"]
    payload = json.loads(data.split("<donnees_projet>\n", 1)[1].split("\n</donnees_projet>")[0])
    # D-82 : apres l'analyse, seuls ses elements VALIDES sont transmis (plus les extraits
    # bruts, dont des prix sans rapport avaient ete presentes comme preuves).
    assert "research" not in payload
    assert payload["analyse"]["recommandation"] is not None  # analyse en memoire (R4)
    assert payload["analyse"]["idees"][0]["niveau_de_preuve"]


def test_provider_failure_is_reported_in_the_conversation(coach, project):
    coach.app.research.registry = build_research_registry(
        simulation=True, extra={"fake": FakeResearchProvider(mode="fail")}
    )
    mission = _proposed(coach, project)
    turn = coach.agent.approve_research(ALICE, project.id, mission.id, mission.scope_hash)
    assert "24 recherche(s) n'ont pas abouti (service indisponible)" in turn.reply
    assert "aucune donnée fiable" in turn.reply.lower()


def test_free_quota_limit_is_reported_and_never_exceeded(coach, monkeypatch, tmp_path):
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_RESEARCH", raising=False)
    calls = []

    def server(request):
        calls.append(request)
        return httpx.Response(200, json={
            "results": [{"title": "Prix des galettes", "url": "https://presse.example/p",
                         "content": "Une galette se vend 4 € sur les marchés de Lyon."}],
            "usage": {"credits": 1},
        })  # fmt: skip

    coach.app.research.registry = build_research_registry(
        environ={"TAVILY_API_KEY": "tvly-TEST-r3"},
        dotenv_path=tmp_path / "absent.env",
        client=httpx.Client(transport=httpx.MockTransport(server)),
    )
    with coach.app.database.transaction(write=True) as conn:
        conn.execute(
            "INSERT INTO research_provider_usage (provider, period, reserved_usd, queries, "
            "updated_at) VALUES ('tavily', ?, 6.384, 798, 'x')",
            (coach.app.clock.now().strftime("%Y-%m"),),
        )
    project = coach.app.coach.create_project(ALICE, "Galettes", "Vendre des galettes à Lyon")
    say(coach, project, "Quels prix pratiquent les autres et que disent les avis clients ?")
    mission = coach.agent.research_pending(ALICE, project.id)
    assert "recherche web réelle" in mission.preview[-3] or any(
        "recherche web réelle" in line for line in mission.preview
    )
    turn = coach.agent.approve_research(ALICE, project.id, mission.id, mission.scope_hash)
    assert len(calls) == 2  # 6,384 + 2 x 0,008 = 6,40 : la limite locale, pas au-dela
    assert "Résultats simulés" not in turn.reply  # D-84 : jamais presentee comme simulee
    usage = {s["name"]: s for s in coach.app.research.availability()["services"]}
    assert usage["tavily"]["used_usd"] <= 6.40 + 1e-9


def test_quota_reached_before_launch_skips_queries(coach, monkeypatch, tmp_path):
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_RESEARCH", raising=False)
    calls = []
    coach.app.research.registry = build_research_registry(
        environ={"TAVILY_API_KEY": "tvly-TEST-r3"},
        dotenv_path=tmp_path / "absent.env",
        client=httpx.Client(transport=httpx.MockTransport(lambda r: calls.append(r))),
    )
    with coach.app.database.transaction(write=True) as conn:
        conn.execute(
            "INSERT INTO research_provider_usage (provider, period, reserved_usd, queries, "
            "exhausted, updated_at) VALUES ('tavily', ?, 1, 1, 1, 'x')",
            (coach.app.clock.now().strftime("%Y-%m"),),
        )
    project = coach.app.coach.create_project(ALICE, "Galettes", "Vendre des galettes à Lyon")
    say(coach, project, "Quels prix pratiquent les autres ?")
    mission = coach.agent.research_pending(ALICE, project.id)
    turn = coach.agent.approve_research(ALICE, project.id, mission.id, mission.scope_hash)
    assert calls == []
    assert "non lancée(s) : quota gratuit du mois" in turn.reply
    assert "Aucun dépassement payant" in turn.reply


# --- recherche non activee, offre unique, routes preservees -----------------------------------


def test_without_keys_the_coach_explains_activation(coach):
    coach.app.research.registry = build_research_registry()  # ni cle ni simulation
    project = coach.app.coach.create_project(ALICE, "Galettes", "")
    turn = say(coach, project, FOUR)
    assert turn.reply == NOT_ENABLED
    assert missions(coach, project) == []


def test_an_idea_gets_a_reply_written_by_the_model_without_any_offer_template(
    coach, fake_provider, fake_llm
):
    """D-78 : la proposition de recherche, s'il y a lieu, est ecrite par le modele."""
    project = coach.app.coach.create_project(ALICE, "Bougies", "")
    fake_llm.calls.clear()
    first = say(coach, project, "Je veux vendre des bougies parfumées à mes collègues")
    assert "coach_turn" in [t for t, _ in fake_llm.calls]  # D-79 : appel unique du coach
    assert OFFER not in first.reply
    assert missions(coach, project) == []  # aucune mission sans demande


def test_status_change_during_collection_keeps_its_route(coach, fake_provider):
    project = coach.app.coach.create_project(ALICE, "Bougies", "")
    say(coach, project, FOUR)
    turn = say(coach, project, "J'ai terminé T1")
    assert "Quelles sont vos" not in (turn.reply or "")
    assert missions(coach, project) == []


def test_service_reused_not_recreated(coach):
    assert isinstance(coach.app.research, ResearchService)


def test_reviews_wording_variants_are_recognised():
    """Recette du 10/11/2026 : « dans les avis » n'etait pas reconnu comme demande d'avis."""
    need = detect_research_need("Que disent les clients dans les avis et sur les forums ?")
    assert {C.REVIEWS, C.TESTIMONIALS} <= set(need.categories)
    assert detect_research_need("À votre avis, je commence quand ?") is None
