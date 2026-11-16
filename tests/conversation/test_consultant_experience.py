"""D-82 : experience d'un consultant, de la decouverte au plan suivi (faux modele).

Verifie le contrat du code : brievete en decouverte, aucune annonce d'enregistrement sans
operation reelle, points retenus enregistres et visibles, recherche presentee simplement
(detail au moment du consentement), conclusion courte apres l'analyse, plan detaille
accepte par clic ou mis de cote pour changement, memoire conservee apres confirmation et
redemarrage. La qualite des textes de gpt-5-mini n'est pas jugee ici.
"""

from __future__ import annotations

import socket

import pytest

from neurocoach.agent.schemas import CoachBrief, CoachTurn, ResearchSpec
from neurocoach.application.research_format import DETAILS_MARKER, split_details
from neurocoach.infra.search_providers import build_research_registry
from neurocoach.research.fake import FakeResearchProvider

Q = "Qu'est-ce qui vous attire le plus dans l'IA ?"
# Debut de la reponse reelle du tour 1 (recette du 12/11/2026), donnee de test.
LONG_REPLY = (
    "Bonjour — très bien, merci pour votre franchise : démarrer sans savoir par où commencer "
    "est fréquent et tout à fait normal. Je peux vous accompagner pas à pas, en commençant par "
    "mieux comprendre ce qui vous motive. Pour l'instant je n'émettrai aucun conseil concret "
    "tant que je n'en sais pas un peu plus sur vous."
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("connexion reseau tentee")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def space(coach):
    coach.app.research.registry = build_research_registry(
        simulation=True, extra={"fake": FakeResearchProvider()}
    )
    user = coach.app.coach.register_user("Camille", "Martin", "camille.m")
    project = coach.app.coach.start_project(user.id)
    coach.agent.greet(user.id, project.id)
    return coach, user.id, project.id


def say(coach, user, project, text):
    return coach.agent.send_message(user, project, text)


def turn(stage="decouverte", reply="Bien noté.", question=Q, next_step="conseiller", **values):
    names = ("plan_requested", "ideas_requested", "plan_change")
    flags = {k: values.pop(k) for k in names if k in values}
    return CoachTurn(intent="information_projet", stage=stage, reply=reply, question=question,
                     fiche=CoachBrief(**values), next_step=next_step, **flags)  # fmt: skip


# --- decouverte : courte, sans meta-discours ----------------------------------------------------


def test_a_discovery_turn_is_one_short_sentence_then_one_question(space, fake_llm):
    coach, user, project = space
    fake_llm.script("coach_turn", turn(reply=LONG_REPLY))
    result = say(coach, user, project, "Bonjour, je ne sais pas par où commencer.")
    first = LONG_REPLY.split(". ")[0] + "."
    assert result.reply == f"{first}\n\n{Q}"
    assert "n'émettrai aucun conseil" not in result.reply
    assert "reponse_raccourcie" in result.timings["decision"]["contract"]


def test_ideas_before_a_complete_diagnosis_are_flagged(space, fake_llm):
    coach, user, project = space
    fake_llm.script("coach_turn", turn(stage="pistes", reply="Je vous recommande X.",
                                       interests="l'IA"))  # fmt: skip
    result = say(coach, user, project, "J'aime l'IA.")
    assert "pistes_avant_diagnostic_complet" in result.timings["decision"]["contract"]
    fake_llm.script("coach_turn", turn(stage="pistes", reply="Je vous recommande X.",
                                       ideas_requested=True))  # fmt: skip
    asked = say(coach, user, project, "Que me recommandez-vous tout de suite ?")
    assert "pistes_avant_diagnostic_complet" not in asked.timings["decision"]["contract"]


# --- veracite : rien d'annonce comme enregistre sans operation ---------------------------------


def test_a_claimed_save_without_any_recorded_point_is_removed(space, fake_llm):
    coach, user, project = space
    fake_llm.script("coach_turn", turn(
        stage="idee_precise", question="",
        reply="Corrections prises en compte. J'ai enregistré ce budget dans votre dossier.",
    ))  # fmt: skip
    result = say(coach, user, project, "Mon budget est de 150 €.")
    assert result.reply == "Corrections prises en compte."
    assert "enregistrement_non_fait_retire" in result.timings["decision"]["contract"]


def test_points_to_keep_are_really_recorded_visible_and_survive_a_restart(
    settings, clock, fake_llm
):
    from neurocoach.bootstrap import build_coach_runtime

    first = build_coach_runtime(settings, clock=clock, llm=fake_llm)
    user = first.app.coach.register_user("Camille", "Martin", "camille.m").id
    project = first.app.coach.start_project(user).id
    note = "Les tarifs d'audits de plusieurs jours ne prouvent pas le prix des micro-prestations."
    fake_llm.script("coach_turn", turn(
        stage="idee_precise", question="",
        reply="C'est noté. Je l'ai consigné dans le suivi du projet.", notes=[note],
    ))  # fmt: skip
    result = first.agent.send_message(user, project, "Retenez cette correction.")
    assert "consigné dans le suivi" in result.reply  # vrai : la fiche a recu le point
    first.checkpointer.conn.close()
    again = build_coach_runtime(settings, clock=clock, llm=fake_llm)
    try:
        assert again.agent.retained(user, project)["notes"] == [note]
    finally:
        again.checkpointer.conn.close()


# --- recherche : consentement clair, conclusion courte -------------------------------------------


def _research(coach, user, project, fake_llm):
    fake_llm.script("research_spec", ResearchSpec(
        subject="Création de prompts sur mesure pour TPE", segment="TPE francophones",
        market="France",
    ))  # fmt: skip
    fake_llm.script("coach_turn", turn(stage="idee_precise", question="",
                                       next_step="preparer_recherche"))  # fmt: skip
    proposal = say(coach, user, project, "Oui, proposez cette recherche sur la France.")
    return proposal, coach.agent.research_pending(user, project)


def test_a_research_is_proposed_simply_with_details_at_consent(space, fake_llm):
    coach, user, project = space
    proposal, mission = _research(coach, user, project, fake_llm)
    # D-84 (vision V1, point 5) : la conversation ne montre ni fournisseurs ni requetes ;
    # tout le detail est dans la fiche d'approbation (carte sous la conversation).
    assert proposal.reply.startswith("Voici la recherche que je vous propose")
    assert DETAILS_MARKER not in proposal.reply
    for technical in ("Exa", "Tavily", "Requête", "quotas", "$", "Données transmises"):
        assert technical not in proposal.reply
    assert any(line.startswith("Fournisseurs") for line in mission.preview)  # rien de cache
    assert any(line.startswith("Données transmises") for line in mission.preview)
    # La clientele comprise remplace la cible supposee (« particuliers »).
    assert not any("cible supposée : particuliers" in line for line in mission.preview)


def test_the_research_ends_with_a_short_conclusion_then_the_details(space, fake_llm):
    coach, user, project = space
    _, mission = _research(coach, user, project, fake_llm)
    result = coach.agent.approve_research(user, project, mission.id, mission.scope_hash)
    main, details = split_details(result.reply)
    assert main.startswith("[Conclusion simulée]") and len(main) < 600
    assert DETAILS_MARKER in result.reply and "Niveau de preuve" in details
    # D-84 : aucun journal d'execution dans la conversation ; une simulation reste signalee.
    for log in ("Voici mon analyse critique", "résultat(s) reçu(s)", "recherche(s) faite(s)",
                "Demandez-le simplement", "affirmation(s) retirée(s)"):  # fmt: skip
        assert log not in result.reply
    assert "Résultats simulés, fictifs" in details
    system = [m for t, m in fake_llm.calls if t == "research_conclusion"][-1][0]["content"]
    assert "N'invente aucun chiffre, prix, demande ni concurrent absent de analyse" in system
    assert "un prix affiché n'est pas un prix payé" in system


def test_a_failed_conclusion_falls_back_to_the_validated_analysis(space, fake_llm):
    from neurocoach.domain.errors import DomainError, ErrorCode

    coach, user, project = space
    _, mission = _research(coach, user, project, fake_llm)
    fake_llm.script("research_conclusion", DomainError(ErrorCode.LLM_UNAVAILABLE))
    result = coach.agent.approve_research(user, project, mission.id, mission.scope_hash)
    main, _ = split_details(result.reply)
    assert main.startswith("L'analyse des résultats est terminée.")


# --- plan : detaille, accepter ou demander un changement, suivi --------------------------------


def _plan(coach, user, project, fake_llm):
    fake_llm.script("coach_turn", turn(
        stage="idee_precise", question="", next_step="preparer_plan", plan_requested=True,
        idea_summary="Création de prompts sur mesure pour TPE", available_minutes_per_day=60,
        budget="150 €",
    ))  # fmt: skip
    return say(coach, user, project, "Proposez-moi un plan.")


def test_asking_for_a_change_saves_nothing_and_adapts_the_plan(space, fake_llm):
    coach, user, project = space
    first = _plan(coach, user, project, fake_llm)
    first_id = first.pending["pending_action_id"]
    assert "**Étape 1 :" in first.reply and "Demander un changement" in first.reply
    coach.agent.decide(user, project, first_id, "cancel", reason="change")
    assert coach.app.actions.get_action(user, first_id).status.value == "cancelled"
    assert coach.app.coach.list_tasks(user, project) == []
    history = [m["content"] for m in coach.agent.history(user, project)]
    assert history[-1].startswith("D'accord, je mets cette proposition de côté")
    # Le changement decrit ensuite : le modele en est informe et le plan est adapte.
    fake_llm.script("coach_turn", turn(
        stage="idee_precise", question="", next_step="preparer_plan", plan_requested=True,
    ))  # fmt: skip
    second = say(coach, user, project, "Je préfère commencer par trois clients tests.")
    facts = [m for t, m in fake_llm.calls if t == "coach_turn"][-1][-1]["content"]
    assert '"modification_demandee": true' in facts
    assert second.pending is not None and second.pending["pending_action_id"] != first_id
    plan_facts = [m for t, m in fake_llm.calls if t == "draft_plan"][-1][-1]["content"]
    assert "proposition_precedente" in plan_facts


def test_a_described_change_gets_the_adapted_plan_even_if_the_model_advises(space, fake_llm):
    """Recette reelle (D-83) : apres « Demander un changement », gpt-5-mini a repondu par un
    conseil et une question (next_step conseiller, etape pistes) au changement decrit. Le
    signal plan_change, pris avant la reponse, suffit : le code prepare le plan adapte."""
    coach, user, project = space
    first = _plan(coach, user, project, fake_llm)
    coach.agent.decide(user, project, first.pending["pending_action_id"], "cancel", reason="change")
    fake_llm.script("coach_turn", turn(
        stage="pistes", question="", next_step="conseiller", plan_change=True,
        reply="Très bien, je reprends la proposition avec ce point de départ.",
    ))  # fmt: skip
    second = say(coach, user, project, "Je préfère commencer par 3 audits gratuits.")
    assert second.pending is not None and "**Étape 1 :" in second.reply
    plan_facts = [m for t, m in fake_llm.calls if t == "draft_plan"][-1][-1]["content"]
    assert "proposition_precedente" in plan_facts


def test_a_question_after_asking_for_a_change_prepares_no_plan(space, fake_llm):
    coach, user, project = space
    first = _plan(coach, user, project, fake_llm)
    coach.agent.decide(user, project, first.pending["pending_action_id"], "cancel", reason="change")
    fake_llm.script("coach_turn", turn(
        stage="idee_precise", question="", next_step="conseiller", plan_change=False,
        reply="L'étape 2 sert à préparer vos supports.",
    ))  # fmt: skip
    answer = say(coach, user, project, "À quoi sert l'étape 2 ?")
    assert answer.pending is None
    assert coach.app.coach.list_tasks(user, project) == []
    # Le changement reste attendu : un changement decrit ensuite est encore adapte.
    fake_llm.script("coach_turn", turn(
        stage="idee_precise", question="", next_step="conseiller", plan_change=True,
    ))  # fmt: skip
    assert say(coach, user, project, "Alors retirez l'étape 2.").pending is not None


def test_an_accepted_plan_is_saved_tracked_and_the_profile_kept(settings, clock, fake_llm):
    from neurocoach.bootstrap import build_coach_runtime

    first = build_coach_runtime(settings, clock=clock, llm=fake_llm)
    user = first.app.coach.register_user("Camille", "Martin", "camille.m").id
    project = first.app.coach.start_project(user).id
    fake_llm.script("coach_turn", turn(interests="les outils d'IA", skills="ChatGPT"))
    first.agent.send_message(user, project, "J'aime les outils d'IA, je maîtrise ChatGPT.")
    proposal = _plan(first, user, project, fake_llm)
    confirmed = first.agent.decide(user, project, proposal.pending["pending_action_id"], "confirm")
    assert confirmed.reply.startswith("Le plan est enregistré. Première action : T1")
    first.checkpointer.conn.close()
    again = build_coach_runtime(settings, clock=clock, llm=fake_llm)
    try:
        tasks = again.app.coach.list_tasks(user, project)
        assert len(tasks) >= 3  # enregistrees, relues apres redemarrage
        assert again.app.coach.get_project(user, project).status.value == "active"
        profile = again.agent.retained(user, project)["profil"]
        assert profile["Vos centres d'intérêt"] == "les outils d'IA"  # memoire conservee
        status = again.agent.send_message(user, project, "Où en suis-je ?")
        assert status.reply.startswith("0 tâche terminée sur")
    finally:
        again.checkpointer.conn.close()


# --- defauts trouves pendant le test de bout en bout dans l'interface (12/11/2026) -------------


def test_stating_ones_own_budget_is_never_treated_as_financial_advice(space, fake_llm):
    coach, user, project = space
    # Le faux modele classe « investir » hors perimetre, comme le vrai l'a deja fait.
    result = say(coach, user, project, "Je peux investir 150 € au maximum pour démarrer.")
    assert "avis médical, juridique ou financier" not in result.reply
    assert [t for t, _ in fake_llm.calls] == ["coach_turn"]
    sensitive = say(coach, user, project, "Dois-je placer mon épargne en bourse ?")
    assert "financier" in sensitive.reply  # un vrai conseil financier reste refuse


def test_an_idea_named_in_a_research_request_is_kept(space, fake_llm):
    coach, user, project = space
    say(coach, user, project, "Je souhaite proposer de la création de prompts pour des TPE. "
        "Faites une recherche de marché sur la France.")  # fmt: skip
    assert coach.agent.research_pending(user, project) is not None  # demande explicite
    assert coach.agent.retained(user, project)["idee"]  # l'idee est dans la fiche
    assert "coach_turn" in [t for t, _ in fake_llm.calls]


def test_a_question_about_results_never_starts_a_new_research(space, fake_llm):
    coach, user, project = space
    say(coach, user, project, "Je veux vendre des bougies à Lyon. Faites une recherche de "
        "marché sur la concurrence.")  # fmt: skip
    mission = coach.agent.research_pending(user, project)
    coach.agent.approve_research(user, project, mission.id, mission.scope_hash)
    say(coach, user, project, "Et quels sont les risques principaux ?")
    assert coach.agent.research_pending(user, project) is None
    say(coach, user, project, "Faites une nouvelle recherche sur les prix.")
    assert coach.agent.research_pending(user, project) is not None  # explicite : proposee


def test_the_research_intro_does_not_repeat_its_categories(space, fake_llm):
    coach, user, project = space
    proposal, _ = _research(coach, user, project, fake_llm)
    main, _ = split_details(proposal.reply)
    assert ") : :" not in main and main.count("concurrence") == 1


def test_creating_a_project_never_reopens_a_started_conversation(space, fake_llm):
    coach, user, project = space
    say(coach, user, project, "Bonjour, je ne sais pas par où commencer.")
    fresh = coach.agent.start_project(user)
    assert fresh.id != project  # conversation commencee : un nouveau projet
    assert coach.agent.start_project(user).id == fresh.id  # projet vide : repris, pas double


def test_a_research_asked_to_the_coach_covers_the_named_categories(space, fake_llm):
    coach, user, project = space
    say(coach, user, project, "Je veux proposer des ateliers d'IA à Lyon. Faites une recherche "
        "de marché sur la concurrence et les prix.")  # fmt: skip
    categories = {c.value for c in coach.agent.research_pending(user, project).scope.categories}
    assert {"concurrence", "prix"} <= categories


def test_an_explicit_research_request_wins_over_an_unrequested_plan(space, fake_llm):
    coach, user, project = space
    fake_llm.script("coach_turn", turn(
        stage="idee_precise", question="", next_step="preparer_plan",
        idea_summary="Ateliers d'initiation à l'IA pour commerçants", available_minutes_per_day=90,
        budget="200 €",
    ))  # fmt: skip
    result = say(coach, user, project, "Faites une recherche de marché sur la concurrence à Lyon.")
    assert result.pending is None  # aucun plan propose a sa place
    assert coach.agent.research_pending(user, project) is not None
