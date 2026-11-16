"""R4 (D-71) : analyse des recherches par le modele de strategie, dans la conversation.

Faux modele et fournisseur simule : aucun appel reseau ni payant. Verifie les sources, les
retraits, les donnees manquantes, la comparaison, le cache, les erreurs, le suivi et
l'isolation, ainsi que l'absence de toute ecriture dans le projet.
"""

from __future__ import annotations

import json
import socket

import pytest

from factories import ALICE, BRUNO
from neurocoach.agent.research_analyst import LLMResearchAnalyst
from neurocoach.agent.roles import role_for
from neurocoach.application.research_format import format_analysis
from neurocoach.application.research_service import NOT_RUN_YET
from neurocoach.domain.analysis import ComparisonDraft, IdeaAnalysisDraft
from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.infra.search_providers import build_research_registry
from neurocoach.research.fake import FakeResearchProvider

FOUR = "J'ai quatre idées de business, mais je ne sais pas laquelle choisir."
IDEAS = (
    "Des bougies parfumées artisanales\n"
    "Un food truck de galettes\n"
    "Des cours de yoga en entreprise\n"
    "Une application de covoiturage scolaire"
)
CONTEXT = "J'ai un budget de 2000 €, 10 heures par semaine, et je veux un revenu complémentaire."


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("connexion reseau tentee")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def project(coach):
    coach.app.research.registry = build_research_registry(
        simulation=True, extra={"fake": FakeResearchProvider()}
    )
    return coach.app.coach.create_project(ALICE, "Choisir mon activité", "")


def say(coach, project, text, user=ALICE):
    return coach.agent.send_message(user, project.id, text)


def researched(coach, project, before=None, **kwargs):
    """Recherche proposee puis approuvee. D-80 : l'analyse critique suit l'approbation, sans
    mot-cle ; ``before`` prepare les reponses du modele avant le clic."""
    say(coach, project, FOUR)
    say(coach, project, IDEAS)
    say(coach, project, CONTEXT)  # criteres connus : la question suivante est le marche
    say(coach, project, "France")
    mission = coach.agent.research_pending(ALICE, project.id)
    if before is not None:
        before()
    turn = coach.agent.approve_research(ALICE, project.id, mission.id, mission.scope_hash,
                                        **kwargs)  # fmt: skip
    return Researched(mission, turn.reply)


class Researched:
    """Mission approuvee, avec la reponse affichee a l'approbation (analyse comprise)."""

    def __init__(self, mission, reply):
        self._mission, self.approval_reply = mission, reply

    def __getattr__(self, name):
        return getattr(self._mission, name)


def tasks_of(fake_llm, *names):
    return [(t, m) for t, m in fake_llm.calls if t in names]


def payload_of(messages):
    content = messages[-1]["content"]
    return json.loads(content.split("<donnees_projet>\n", 1)[1].split("\n</donnees_projet>")[0])


# --- roles : le modele de strategie existant, aucun second systeme ---------------------------


def test_analysis_tasks_use_the_strategy_role():
    assert role_for("research_analysis") == "strategy"
    assert role_for("research_comparison") == "strategy"


# --- analyse dans la conversation ------------------------------------------------------------


def test_analysis_of_four_ideas_in_the_conversation(coach, project, fake_llm):
    mission = researched(coach, project)
    # D-80 : l'analyse arrive avec les resultats, sans mot-cle a taper.
    # D-84 : niveau de preuve dans la conversation, journal dans l'onglet Recherche.
    assert "Niveau de preuve" in mission.approval_reply
    assert "Voici mon analyse critique" not in mission.approval_reply
    calls = len(fake_llm.calls)
    turn = say(coach, project, "Analyse ces résultats, s'il vous plaît")
    assert not tasks_of(type("L", (), {"calls": fake_llm.calls[calls:]}), "research_analysis")
    reply = turn.reply.replace("\\", "")
    assert "Niveau de preuve" in reply  # D-83 : apres la conclusion courte
    assert "Résultats simulés, fictifs" in reply
    for n in range(1, 5):
        assert f"**{n}. " in reply
    assert "Avis du coach" in reply and "Fait sourcé" in reply and "source : " in reply
    assert "**Comparaison**" in reply and "**Recommandation** (confiance" in reply
    assert "Vérifications à faire" in reply and "Ce qui me ferait changer d'avis" in reply
    assert "Adéquation à votre situation : Budget : mitigé" in reply
    assert "Compétences : inconnu" in reply  # jamais dites : jamais supposees
    assert "Demandez-le simplement" not in reply  # D-84 : suggestion dans l'onglet Recherche
    # Quatre analyses d'idee + une comparaison, toutes sur le role strategy.
    assert [t for t, _ in tasks_of(fake_llm, "research_analysis", "research_comparison")] == [
        "research_analysis"] * 4 + ["research_comparison"]  # fmt: skip
    # La confiance « elevee » proposee par le modele est plafonnee par le code.
    analysis = coach.app.research.latest_analysis(ALICE, mission.id)
    assert analysis.comparison.proposed_confidence == "elevee"
    assert analysis.comparison.confidence in ("faible", "moyenne")
    # Aucune ecriture dans le projet, aucune proposition de plan.
    assert coach.app.coach.list_tasks(ALICE, project.id) == []
    assert coach.app.actions.get_pending(ALICE, project.id) is None


def test_every_fact_is_backed_by_a_stored_source(coach, project):
    mission = researched(coach, project)
    say(coach, project, "Quelle idée me recommandez-vous ?")
    analysis = coach.app.research.latest_analysis(ALICE, mission.id)
    sources = {s.id: s for s in coach.app.research.mission_report(ALICE, mission.id).sources}
    facts = [c for i in analysis.ideas for cs in i.sections.values() for c in cs
             if c.kind == "fait"]  # fmt: skip
    assert facts
    for claim in facts:
        assert claim.source_ids and set(claim.source_ids) <= set(sources)
        corpus = " ".join(sources[s].excerpt for s in claim.source_ids)
        assert all(q in corpus for q in claim.quotes) and claim.quotes
    for idea in analysis.ideas:
        for competitor in idea.competitors:
            assert any(competitor.name in sources[s].excerpt + sources[s].title
                       for s in competitor.source_ids)  # fmt: skip


def test_injected_instruction_never_reaches_the_model(coach, project, fake_llm):
    researched(coach, project)
    fake_llm.calls.clear()
    say(coach, project, "analyse")
    for _, messages in tasks_of(fake_llm, "research_analysis"):
        assert "Ignore les instructions" not in messages[-1]["content"]


def test_profile_is_built_from_the_users_words(coach, project, fake_llm):
    researched(coach, project)
    profile = payload_of(tasks_of(fake_llm, "research_analysis")[0][1])["profil"]
    assert profile["budget"] == [CONTEXT]
    assert profile["competences"] == []


def test_analysis_is_reused_then_redone_on_request(coach, project, fake_llm):
    researched(coach, project)
    say(coach, project, "analyse")
    fake_llm.calls.clear()
    follow = say(coach, project, "Et quels sont les risques de la deuxième ?")
    assert not tasks_of(fake_llm, "research_analysis")  # deja analysee : aucun nouvel appel
    reply_calls = tasks_of(fake_llm, "coach_turn", "coach_reply")  # D-80 : sans plan
    assert reply_calls and follow.reply
    facts = payload_of(reply_calls[-1][1])
    assert facts["analyse"]["idees"][1]["idee"] == "Un food truck de galettes"
    assert "avis du coach" in reply_calls[-1][1][0]["content"]
    fake_llm.calls.clear()
    redo = say(coach, project, "Refais l'analyse")
    assert "Niveau de preuve" in redo.reply
    assert len(tasks_of(fake_llm, "research_analysis")) == 4


def test_long_analysis_is_never_truncated_by_the_one_question_rule(coach, project, fake_llm):
    def scripted():
        for _ in range(4):
            fake_llm.script("research_analysis", IdeaAnalysisDraft(summary="Pour qui ? Pourquoi ?"))
        fake_llm.script("research_comparison", ComparisonDraft(
            reasoning="Laquelle démarre le plus vite ? Laquelle rapporte le plus ? À vérifier.",
            confidence="faible",
        ))  # fmt: skip

    researched(coach, project, before=scripted)
    reply = say(coach, project, "analyse").reply
    assert "À vérifier." in reply
    tab = format_analysis(*coach.app.research.project_analysis(ALICE, project.id))
    assert "Étape suivante possible" in tab  # D-84 : suggestion dans l'onglet Recherche


def test_model_inventions_are_removed_and_reported(coach, project, fake_llm):
    bad = IdeaAnalysisDraft.model_validate({
        "summary": "Un succès garanti.",
        "competitors": [{"name": "Maison Lumière", "positioning": "leader", "sources": ["S1"]}],
        "prices": [{"text": "Une bougie se vend 45 €.", "kind": "fait", "sources": []}],
        "strengths": [{"text": "Il y a 10 000 clients potentiels.", "kind": "avis"}],
    })  # fmt: skip
    researched(coach, project, before=lambda: fake_llm.script("research_analysis", *[bad] * 4))
    reply = say(coach, project, "analyse").reply.replace("\\", "")
    assert "Maison Lumière" not in reply and "45 €" not in reply and "10 000" not in reply
    assert "succès garanti" not in reply.lower() and "succès probablement" in reply.lower()
    assert "Prix observés : insuffisant" in reply
    tab = format_analysis(*coach.app.research.project_analysis(ALICE, project.id))
    assert "affirmation(s) retirée(s) ou requalifiée(s)" in tab  # D-84 : onglet Recherche
    assert "affirmation(s) retirée(s)" not in reply


def test_one_idea_failure_does_not_block_the_others(coach, project, fake_llm):
    mission = researched(coach, project, before=lambda: fake_llm.script(
        "research_analysis", DomainError(ErrorCode.LLM_UNAVAILABLE)))  # fmt: skip
    reply = mission.approval_reply.replace("\\", "")
    assert "Analyse indisponible pour le moment" in reply
    assert "**Comparaison**" in reply


def test_missing_data_is_reported_without_any_model_call(coach, fake_llm):
    coach.app.research.registry = build_research_registry(
        simulation=True, extra={"fake": FakeResearchProvider(mode="empty")}
    )
    project = coach.app.coach.create_project(ALICE, "Galettes", "Vendre des galettes à Lyon")
    say(coach, project, "Qui sont mes concurrents ?")
    mission = coach.agent.research_pending(ALICE, project.id)
    coach.agent.approve_research(ALICE, project.id, mission.id, mission.scope_hash)
    fake_llm.calls.clear()
    reply = say(coach, project, "Analyse").reply.replace("\\", "")
    assert not tasks_of(fake_llm, "research_analysis", "research_comparison")
    assert "Aucune source exploitable trouvée pour cette idée" in reply
    assert "Comparaison indisponible" in reply


def test_nothing_to_analyse_before_any_research(coach, project):
    say(coach, project, FOUR)
    say(coach, project, IDEAS)
    say(coach, project, CONTEXT)
    say(coach, project, "France")
    mission = coach.agent.research_pending(ALICE, project.id)
    with pytest.raises(DomainError) as error:
        coach.app.research.analyze_mission(ALICE, mission.id, LLMResearchAnalyst(coach.llm))
    assert error.value.detail == NOT_RUN_YET


# --- onglet, isolation, export, suppression --------------------------------------------------


def test_tab_analysis_is_isolated_per_user(coach, project):
    mission = researched(coach, project)
    with pytest.raises(DomainError) as error:
        coach.agent.analyze_research(BRUNO, project.id, mission.id)
    assert error.value.code is ErrorCode.NOT_FOUND
    analysis = coach.agent.analyze_research(ALICE, project.id, mission.id)
    assert len(analysis.ideas) == 4
    with pytest.raises(DomainError):
        coach.app.research.latest_analysis(BRUNO, mission.id) or coach.app.research.mission_report(
            BRUNO, mission.id
        )


def test_export_and_deletion_include_analyses(coach, project):
    mission = researched(coach, project)
    say(coach, project, "analyse")
    export = coach.app.data.export_user_data(ALICE)
    [item] = export["research"]
    assert item["analyses"] and item["analyses"][0]["mission_id"] == mission.id
    action = coach.app.actions.request_project_deletion(ALICE, project.id)
    coach.app.actions.confirm(ALICE, action.id)
    with coach.app.database.transaction(write=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM research_analyses").fetchone()[0] == 0


def test_incomplete_analysis_is_redone_instead_of_served_from_cache(coach, project, fake_llm):
    """Recette du 10/11/2026 : une analyse en echec restait servie a chaque « analyse »."""
    mission = researched(coach, project, before=lambda: fake_llm.script(
        "research_analysis", DomainError(ErrorCode.LLM_OUTPUT_INVALID)))  # fmt: skip
    first = mission.approval_reply.replace("\\", "")
    assert "Analyse indisponible pour le moment" in first
    fake_llm.calls.clear()
    second = say(coach, project, "analyse").reply.replace("\\", "")
    assert "Analyse indisponible" not in second
    assert len(tasks_of(fake_llm, "research_analysis")) == 4  # refaite, sans « refais »


def test_single_idea_is_labelled_by_its_subject_never_by_the_title(coach, fake_llm):
    """D-80 : recette du 12/11/2026, « ... pour : Nouveau projet » : le sujet compris de la
    conversation nomme l'analyse ; le titre du projet peut etre provisoire."""
    coach.app.research.registry = build_research_registry(
        simulation=True, extra={"fake": FakeResearchProvider()}
    )
    project = coach.app.coach.create_project(
        ALICE, "Galettes", "Vendre des galettes à Lyon. J'ai un budget de 300 €."
    )
    say(coach, project, "Qui sont mes concurrents ?")
    mission = coach.agent.research_pending(ALICE, project.id)
    coach.agent.approve_research(ALICE, project.id, mission.id, mission.scope_hash)
    fake_llm.calls.clear()
    reply = say(coach, project, "analyse").reply.replace("\\", "")
    assert "**1. Vendre des galettes à Lyon" in reply
    assert "Étudier concurrence pour : Vendre des galettes à Lyon" in mission.scope.objective


# --- finalisation : commandes explicites sans classification par le modele ----------------


def test_explicit_commands_skip_the_classification_call(coach, project, fake_llm):
    """Mesure reelle du 11/11/2026 : la classification de « analyse » coutait 13 s."""
    researched(coach, project)
    fake_llm.calls.clear()
    reply = say(coach, project, "analyse").reply
    assert "Niveau de preuve" in reply
    assert "classify_intent" not in [t for t, _ in fake_llm.calls]
    fake_llm.calls.clear()
    say(coach, project, "Cherche des solutions")
    assert "classify_intent" not in [t for t, _ in fake_llm.calls]
    assert coach.agent.research_pending(ALICE, project.id) is not None


def test_questions_and_unrelated_messages_are_still_classified(coach, project, fake_llm):
    """Pas de raccourci de commande : le message est compris par le modele (classification,
    ou, D-79, appel direct du coach dont l'intention peut renvoyer a la classification)."""
    researched(coach, project)
    expected = {
        "Analyse : est-ce une bonne idée ?": ["classify_intent"],  # suite d'une recherche
        "J'ai terminé T1": ["coach_turn", "classify_intent"],  # statut : reclassement
        "Bonjour": ["coach_turn"],  # conversation ordinaire
    }
    for text, calls in expected.items():
        fake_llm.calls.clear()
        say(coach, project, text)
        assert [t for t, _ in fake_llm.calls][: len(calls)] == calls, text


def test_command_without_any_research_is_classified(coach, fake_llm):
    project = coach.app.coach.create_project(ALICE, "Sans recherche", "")
    fake_llm.calls.clear()
    say(coach, project, "analyse")
    calls = [t for t, _ in fake_llm.calls]
    assert "classify_intent" in calls or "coach_turn" in calls  # compris, pas une commande


def test_progress_reaches_the_interface_during_a_chat_analysis(coach, project):
    seen: list[str] = []
    researched(coach, project, progress=seen.append)  # D-80 : analyse suivant l'approbation
    assert "Analyse de 4 idée(s) en cours" in seen
    assert "Analyses d'idées terminées : 4/4" in seen
    assert seen[-1] == "Synthèse et recommandation en cours"
