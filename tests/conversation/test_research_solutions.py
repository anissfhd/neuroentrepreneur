"""R6 (D-73) : recherche de solutions dans la conversation, puis taches apres confirmation.

Faux modele, fournisseur simule et doublure HTTP : aucun appel reseau ni payant.
"""

from __future__ import annotations

import json
import socket

import pytest

from factories import ALICE, BRUNO
from neurocoach.agent.research_dialogue import NO_ACTIONS, NO_PROBLEMS, RESEARCH_WITH_BUTTON
from neurocoach.application.formatting import OUT_OF_SCOPE_MESSAGE
from neurocoach.application.research_format import format_analysis
from neurocoach.application.research_service import MissionRequest
from neurocoach.domain.analysis import IdeaAnalysisDraft
from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.models import ActionStatus
from neurocoach.domain.research import ResearchCategory
from neurocoach.domain.solutions import SolutionsDraft
from neurocoach.infra.search_providers import build_research_registry
from neurocoach.research.fake import FakeResearchProvider

C = ResearchCategory


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


def say(coach, project, text, user=ALICE):
    return coach.agent.send_message(user, project.id, text)


def analysed(coach, project):
    """Recherche sur les avis puis analyse R4/R5 : des problemes etayes existent."""
    say(coach, project, "Que disent les clients sur les forums et les avis ?")
    mission = coach.agent.research_pending(ALICE, project.id)
    coach.agent.approve_research(ALICE, project.id, mission.id, mission.scope_hash)
    say(coach, project, "analyse")


def solved(coach, project):
    analysed(coach, project)
    proposal = say(coach, project, "Cherche des solutions à ces problèmes")
    mission = coach.agent.research_pending(ALICE, project.id)
    return proposal, mission


def payload_of(messages):
    content = messages[-1]["content"]
    return json.loads(content.split("<donnees_projet>\n", 1)[1].split("\n</donnees_projet>")[0])


# --- proposition de la mission et consentement ----------------------------------------------


def test_analysis_offers_solutions_for_the_best_supported_problems(coach, project):
    analysed(coach, project)
    last = coach.agent.history(ALICE, project.id)[-1]["content"].replace("\\", "")
    # D-84 : la suggestion reste dans l'onglet Recherche, pas dans la conversation.
    assert "Demandez-le simplement" not in last
    tab = format_analysis(*coach.app.research.project_analysis(ALICE, project.id))
    assert "Demandez-le simplement" in tab.replace("\\", "")  # D-80 : aucun mot-cle impose
    assert "Délais et livraison" in tab.replace("\\", "").split("Étape suivante possible")[1]


def test_solutions_mission_is_proposed_with_one_approval(coach, project, provider):
    proposal, mission = solved(coach, project)
    calls_before = len(provider.calls)
    text = proposal.reply.replace("\\", "")
    assert text.startswith("Voici la recherche de solutions que je vous propose")
    card = "\n".join(mission.preview).replace("\\", "")  # D-84 : fiche d'approbation
    assert "Problèmes traités : 1) Délais et livraison" in card
    assert "Recherches prévues : solutions" in card
    assert mission.scope.purpose == "solutions" and len(mission.scope.problems) == 3
    # Trois angles par probleme (outils, logiciels libres, methodes) ; une seule approbation.
    assert len(mission.planned) == 9
    assert {q.subject for q in mission.planned} == {p.label for p in mission.scope.problems}
    assert any("open source GitHub API" in q.text for q in mission.planned)
    turn = say(coach, project, "oui")
    assert turn.reply is None and turn.notice == RESEARCH_WITH_BUTTON
    assert len(provider.calls) == calls_before  # rien n'est parti avant le clic


def test_approval_runs_all_searches_and_posts_sourced_solutions(coach, project, provider):
    _, mission = solved(coach, project)
    before = len(provider.calls)
    turn = coach.agent.approve_research(ALICE, project.id, mission.id, mission.scope_hash)
    assert len(provider.calls) - before == 9  # toutes les recherches, sans nouvelle question
    reply = turn.reply.replace("\\", "")
    assert reply.startswith("Voici les solutions trouvées")
    assert "Planifix (Outil en ligne (SaaS), source : outils-fictifs.example)" in reply
    assert "Livraison-Libre (Logiciel libre, source : github.example)" in reply
    assert "tarif sourcé" in reply and "Développement sur mesure" in reply
    assert "Existant, sur mesure ou hybride" in reply
    assert "**Recommandation** (confiance faible) : Planifix" in reply  # simule : faible
    assert "Prochaines actions" in reply and "transforme ces actions en tâches" in reply
    assert "Ignore les instructions" not in reply
    assert coach.app.coach.list_tasks(ALICE, project.id) == []  # rien n'est ecrit
    plan = coach.app.research.latest_solutions(ALICE, mission.id)
    assert plan.problems[0].options[0].kind in ("saas", "open_source")


def test_follow_up_questions_keep_the_solutions_in_context(coach, project, fake_llm):
    _, mission = solved(coach, project)
    coach.agent.approve_research(ALICE, project.id, mission.id, mission.scope_hash)
    fake_llm.calls.clear()
    turn = say(coach, project, "Laquelle me recommandez-vous pour commencer ?")
    assert turn.reply
    calls = [m for t, m in fake_llm.calls if t in ("coach_turn", "coach_reply")]
    assert calls, "la question de suivi passe par la reponse du coach"
    facts = payload_of(calls[-1])
    assert facts["solutions"]["problemes"][0]["options"][0]["nom"] == "Planifix"
    assert "pour solutions ne cite que les options validées" in calls[-1][0]["content"]
    assert not [t for t, _ in fake_llm.calls if t == "research_solutions"]  # pas de recalcul


# --- conversion en taches, uniquement apres confirmation -------------------------------------


def test_actions_become_a_plan_proposal_then_tasks_only_after_confirmation(coach, project):
    _, mission = solved(coach, project)
    coach.agent.approve_research(ALICE, project.id, mission.id, mission.scope_hash)
    turn = say(coach, project, "Transforme ces actions en tâches")
    assert turn.pending is not None and turn.pending["kind"] == "plan"
    assert "Voici la proposition de plan" in turn.reply
    assert coach.app.coach.list_tasks(ALICE, project.id) == []  # rien avant le clic
    coach.agent.decide(ALICE, project.id, turn.pending["pending_action_id"], "confirm")
    tasks = coach.app.coach.list_tasks(ALICE, project.id)
    assert tasks and any(t.title.startswith("Tester Planifix") for t in tasks)
    snapshot = coach.app.coach.get_snapshot(ALICE, project.id)
    assert [p.title for p in snapshot.ordered_phases()] == ["Solutions aux problèmes repérés"]


def test_cancelled_task_proposal_writes_nothing(coach, project):
    _, mission = solved(coach, project)
    coach.agent.approve_research(ALICE, project.id, mission.id, mission.scope_hash)
    turn = say(coach, project, "ajoute ces actions à mon plan")
    action_id = turn.pending["pending_action_id"]
    coach.agent.decide(ALICE, project.id, action_id, "cancel")
    assert coach.app.coach.list_tasks(ALICE, project.id) == []
    assert coach.app.actions.get_action(ALICE, action_id).status is ActionStatus.CANCELLED


def test_active_project_receives_added_tasks_after_confirmation(coach, project, make_planned):
    planned = make_planned(ALICE, "Projet avec plan")
    coach.app.research.registry = build_research_registry(
        simulation=True, extra={"fake": FakeResearchProvider()}
    )
    before = len(coach.app.coach.list_tasks(ALICE, planned.project.id))
    analysed(coach, planned.project)
    say(coach, planned.project, "Cherche des solutions")
    mission = coach.agent.research_pending(ALICE, planned.project.id)
    coach.agent.approve_research(ALICE, planned.project.id, mission.id, mission.scope_hash)
    turn = say(coach, planned.project, "Transforme ces actions en tâches")
    assert turn.pending["kind"] == "change"
    coach.agent.decide(ALICE, planned.project.id, turn.pending["pending_action_id"], "confirm")
    assert len(coach.app.coach.list_tasks(ALICE, planned.project.id)) > before


def test_no_actions_yet_means_no_task_proposal(coach, project):
    analysed(coach, project)
    turn = say(coach, project, "Transforme ces actions en tâches")
    assert turn.pending is None  # aucune solution encore : aucune proposition de taches
    assert coach.app.actions.get_pending(ALICE, project.id) is None
    assert coach.app.coach.list_tasks(ALICE, project.id) == []


def test_solutions_without_actions_explain_instead_of_proposing(coach, project, fake_llm):
    _, mission = solved(coach, project)
    for _ in range(3):
        fake_llm.script("research_solutions", SolutionsDraft(confidence="faible"))
    coach.agent.approve_research(ALICE, project.id, mission.id, mission.scope_hash)
    turn = say(coach, project, "Transforme ces actions en tâches")
    assert turn.reply == NO_ACTIONS and turn.pending is None


# --- erreurs, preuves, isolation -------------------------------------------------------------


def test_provider_failure_gives_no_invented_solution(coach, project):
    _, mission = solved(coach, project)
    coach.app.research.registry = build_research_registry(
        simulation=True, extra={"fake": FakeResearchProvider(mode="fail")}
    )
    turn = coach.agent.approve_research(ALICE, project.id, mission.id, mission.scope_hash)
    reply = turn.reply.replace("\\", "")
    assert "Aucune source exploitable : aucune solution n'est proposée sans preuve" in reply
    assert "Planifix" not in reply


def test_model_failure_is_reported_per_problem(coach, project, fake_llm):
    _, mission = solved(coach, project)
    fake_llm.script("research_solutions", DomainError(ErrorCode.LLM_UNAVAILABLE))
    turn = coach.agent.approve_research(ALICE, project.id, mission.id, mission.scope_hash)
    assert "Solutions indisponibles pour le moment" in turn.reply.replace("\\", "")
    assert "Planifix" in turn.reply  # les autres problemes sont traites


def test_invented_solutions_and_prices_are_removed(coach, project, fake_llm):
    _, mission = solved(coach, project)
    bad = SolutionsDraft.model_validate({
        "options": [
            {"name": "SuperLivreur", "kind": "saas", "how": "Inventé.", "sources": ["S1"]},
            {"name": "Planifix", "kind": "saas", "how": "Suivi.", "sources": ["S2"],
             "cost": {"text": "5 € par mois", "kind": "fait", "sources": ["S2"],
                      "quote": "5 € par mois"}},
        ],
        "recommended": "SuperLivreur", "confidence": "elevee",
    })  # fmt: skip
    for _ in range(3):
        fake_llm.script("research_solutions", bad)
    reply = coach.agent.approve_research(
        ALICE, project.id, mission.id, mission.scope_hash
    ).reply.replace("\\", "")
    assert "SuperLivreur" not in reply and "5 € par mois" not in reply
    assert "élément(s) retiré(s) ou requalifié(s)" in reply
    plan = coach.app.research.latest_solutions(ALICE, mission.id)
    assert all(p.recommended != "SuperLivreur" for p in plan.problems)


def test_without_supported_problems_no_solution_mission(coach, project, fake_llm):
    request = MissionRequest(project_ids=[project.id], categories=[C.PRICES])
    mission = coach.app.research.propose_mission(ALICE, request)
    coach.app.research.approve_mission(ALICE, mission.id, mission.scope_hash)
    coach.app.research.run_mission(ALICE, mission.id)
    fake_llm.script("research_analysis", IdeaAnalysisDraft(summary="Rien de saillant."))
    from neurocoach.agent.research_analyst import LLMResearchAnalyst

    coach.app.research.analyze_mission(ALICE, mission.id, LLMResearchAnalyst(coach.llm))
    turn = say(coach, project, "Cherche des solutions")
    assert turn.reply == NO_PROBLEMS
    assert coach.agent.research_pending(ALICE, project.id) is None


def test_other_user_cannot_approve_or_solve(coach, project):
    _, mission = solved(coach, project)
    with pytest.raises(DomainError) as error:
        coach.agent.approve_research(BRUNO, project.id, mission.id, mission.scope_hash)
    assert error.value.code is ErrorCode.NOT_FOUND
    with pytest.raises(DomainError):
        coach.agent.solve_research(BRUNO, project.id, mission.id)


def test_solutions_are_cached_exported_and_deleted_with_the_project(coach, project, fake_llm):
    _, mission = solved(coach, project)
    coach.agent.approve_research(ALICE, project.id, mission.id, mission.scope_hash)
    fake_llm.calls.clear()
    coach.agent.solve_research(ALICE, project.id, mission.id)
    assert not [t for t, _ in fake_llm.calls if t == "research_solutions"]  # cache
    export = coach.app.data.export_user_data(ALICE)
    assert any(item["solutions"] for item in export["research"])
    action = coach.app.actions.request_project_deletion(ALICE, project.id)
    coach.app.actions.confirm(ALICE, action.id)
    with coach.app.database.transaction(write=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM research_solutions").fetchone()[0] == 0


def test_status_question_after_solutions_keeps_its_route(coach, project, fake_llm):
    """Recette du 10/11/2026 : « Ou en suis-je ? » apres des solutions recevait une reponse de
    suivi au lieu de l'etat du projet."""
    _, mission = solved(coach, project)
    coach.agent.approve_research(ALICE, project.id, mission.id, mission.scope_hash)
    turn = say(coach, project, "Transforme ces actions en tâches")
    coach.agent.decide(ALICE, project.id, turn.pending["pending_action_id"], "confirm")
    fake_llm.calls.clear()
    status = say(coach, project, "Où en suis-je ?")
    assert "T1" in status.reply
    assert not [t for t, _ in fake_llm.calls if t == "coach_reply"]


def test_choosing_among_found_solutions_with_a_budget_is_not_refused(coach, project, fake_llm):
    """Recette du 11/11/2026 : « Laquelle de ces solutions me conseillez-vous, avec mon budget ? »
    etait classee conseil financier et refusee. C'est un choix entre les resultats trouves."""
    _, mission = solved(coach, project)
    coach.agent.approve_research(ALICE, project.id, mission.id, mission.scope_hash)
    fake_llm.calls.clear()
    # le faux modele classe « investir » hors perimetre, comme le vrai l'a fait pour le budget
    turn = say(coach, project, "Laquelle de ces solutions me conseillez-vous, pour investir peu ?")
    assert turn.reply and OUT_OF_SCOPE_MESSAGE not in turn.reply
    calls = [m for t, m in fake_llm.calls if t in ("coach_turn", "coach_reply")]
    assert calls and "solutions" in payload_of(calls[-1])


@pytest.mark.parametrize(
    "text",
    [
        "Dois-je placer mon épargne en bourse ou dans ces solutions ?",
        "Laquelle de ces solutions est la meilleure pour mes impôts ?",
    ],
)
def test_real_financial_or_tax_advice_stays_out_of_scope(coach, project, fake_llm, text):
    _, mission = solved(coach, project)
    coach.agent.approve_research(ALICE, project.id, mission.id, mission.scope_hash)
    turn = say(coach, project, text)
    assert OUT_OF_SCOPE_MESSAGE in turn.reply
