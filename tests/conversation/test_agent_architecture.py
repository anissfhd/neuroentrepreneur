"""D-78 : le coach est le modele. Tests d'architecture et d'invariants (faux modele).

Ils verifient les appels, le contexte transmis et les protections ; ils ne pretendent pas
mesurer la qualite des reponses du vrai modele, qui se juge en recette reelle. Les sorties du
modele sont imposees quand le test porte sur leur traitement par le code.
"""

from __future__ import annotations

import json

import pytest

from neurocoach.agent.schemas import IntentResult, ProjectBrief
from neurocoach.domain.errors import USER_MESSAGES, DomainError, ErrorCode

# Conversation reelle de la recette manuelle du 11/11/2026 (reponses 2 et 3 venaient du code).
REAL = [
    "Bonjour, j'aimerais créer mon propre business, mais je ne sais pas par où commencer. "
    "Pouvez-vous m'aider ?",
    "J'aimerais vendre des bougies artisanales parfumées, mais je n'ai aucune expérience.",
    "Mon projet est de fabriquer et vendre des bougies artisanales parfumées. Je connais donc "
    "déjà mon idée. Je suis débutant et j'ai besoin que vous me guidiez concrètement, étape par "
    "étape. Que me conseillez-vous de faire en premier ?",
]
CANDLES = "Fabriquer et vendre des bougies artisanales parfumées ; débutant, guidage pas à pas."
# Textes codes en dur retires par D-78 : ils ne doivent plus jamais tenir lieu de reponse.
TEMPLATES = (
    "Piste provisoire, à vérifier",
    "objectif provisoire",
    "Quel premier résultat concret",
    "Ce n'est pas grave de ne pas encore le savoir",
    "Pour démarrer sans vous disperser",
    "Je peux aussi préparer une recherche web",
)


@pytest.fixture
def space(coach):
    user = coach.app.coach.register_user("Camille", "Martin", "camille.m")
    project = coach.app.coach.start_project(user.id)
    coach.agent.greet(user.id, project.id)
    return coach, user.id, project.id


def say(coach, user, project, text, **kwargs):
    return coach.agent.send_message(user, project, text, **kwargs)


def payload(messages) -> dict:
    content = messages[-1]["content"]
    return json.loads(content.split("<donnees_projet>\n", 1)[1].split("\n</donnees_projet>")[0])


def reply_calls(llm):
    """D-79 : sur un projet sans plan, la reponse vient de l'appel unique « coach_turn »."""
    return [m for t, m in llm.calls if t in ("coach_turn", "coach_reply")]


# --- 1. les reponses de coaching viennent du modele ---------------------------------------


def test_the_reply_is_the_model_text_verbatim(space, fake_llm):
    coach, user, project = space
    fake_llm.script("coach_reply", "Texte unique écrit par le modèle 7f3a.")
    turn = say(coach, user, project, REAL[0])
    # D-81 : la reponse du modele, puis sa seule question (champ a part).
    assert turn.reply.startswith("Texte unique écrit par le modèle 7f3a.")
    # D-79 : un seul appel par message ordinaire (reponse, fiche et decision ensemble).
    assert [t for t, _ in fake_llm.calls] == ["coach_turn"]


@pytest.mark.parametrize(
    "text",
    [
        "Je veux ouvrir une boulangerie de quartier à Rennes.",
        "J'aimerais lancer une application de covoiturage pour les étudiants.",
        "Je souhaite proposer du coaching sportif en ligne pour les seniors.",
        "Je pense créer une agence de traduction spécialisée dans le droit.",
    ],
)
def test_no_hard_coded_coaching_text_in_any_domain(space, fake_llm, text):
    coach, user, project = space
    turn = say(coach, user, project, text)
    assert turn.reply.startswith("[Réponse simulée]")  # le (faux) modele a ecrit la reponse
    assert not any(template in turn.reply for template in TEMPLATES)


def test_the_real_failing_conversation_now_reaches_the_model_each_time(space, fake_llm):
    """Reponses 2 et 3 : texte « objectif provisoire » du code, repete. Desormais chaque
    message est repondu par le modele, avec le sujet corrige."""
    coach, user, project = space
    fake_llm.script("clarify", ProjectBrief(idea_summary="Créer une entreprise, idée à préciser."))
    fake_llm.script(
        "clarify",
        ProjectBrief(idea_summary="Vendre des bougies artisanales parfumées ; débutant."),
    )
    fake_llm.script(
        "clarify", ProjectBrief(idea_summary=CANDLES, project_title="Bougies artisanales parfumées")
    )
    replies = [say(coach, user, project, text).reply for text in REAL]
    calls = reply_calls(fake_llm)
    assert len(calls) == 3  # un appel au modele par message, aucun texte du code
    assert len(set(replies)) == 3  # jamais la meme reponse repetee
    assert not any(t in r for r in replies for t in TEMPLATES)
    # Le troisieme appel recoit le sujet corrige au deuxieme message, et le dernier message.
    third = payload(calls[2])
    assert "bougies" in third["sujet"].lower()
    assert "Que me conseillez-vous de faire en premier ?" in calls[2][-1]["content"]
    assert coach.app.coach.get_project(user, project).idea == CANDLES


# --- 2. contexte : sujet, corrections, titre ------------------------------------------------


def test_a_generic_saved_title_never_replaces_the_subject(space, fake_llm):
    coach, user, project = space
    say(coach, user, project, REAL[0])
    coach.app.coach.rename_project(user, project, "Accompagnement création entreprise")
    fake_llm.script(
        "clarify", ProjectBrief(idea_summary=CANDLES, project_title="Bougies artisanales parfumées")
    )
    say(coach, user, project, REAL[2])
    fake_llm.calls.clear()
    say(coach, user, project, "Et ensuite ?")
    facts = payload(reply_calls(fake_llm)[-1])
    assert facts["sujet"] == CANDLES
    assert "jamais par le titre" in reply_calls(fake_llm)[-1][0]["content"]
    # Le titre generique enregistre peut etre remplace, sur proposition et par clic.
    assert coach.agent.title_suggestion(user, project) == "Bougies artisanales parfumées"
    assert coach.app.coach.get_project(user, project).title == "Accompagnement création entreprise"


def test_the_context_is_rebuilt_at_every_message(space, fake_llm):
    coach, user, project = space
    say(coach, user, project, "Je veux vendre des bougies à Lyon avec 500 € de budget.")
    say(coach, user, project, "Finalement je préfère les vendre en ligne.")
    facts = payload(reply_calls(fake_llm)[-1])
    assert facts["history"][-1]["content"].startswith("[Réponse simulée]")
    assert facts["history"][-2]["content"].startswith("Je veux vendre des bougies")
    assert facts["connu"]["budget_eur"] == 500 and facts["connu"]["ville"] == "Lyon"
    assert "Finalement je préfère les vendre en ligne." in reply_calls(fake_llm)[-1][-1]["content"]


def test_two_projects_never_share_their_context(space, fake_llm):
    coach, user, first = space
    say(coach, user, first, "Je veux vendre des bougies artisanales à Lyon.")
    coach.app.coach.rename_project(user, first, "Bougies")
    second = coach.app.coach.start_project(user).id
    say(coach, user, second, "Je veux ouvrir un food truck de galettes à Nantes.")
    last = reply_calls(fake_llm)[-1]
    text = json.dumps(payload(last), ensure_ascii=False) + last[-1]["content"]
    assert "galettes" in text and "bougies" not in text.lower() and "Lyon" not in text


def test_the_context_survives_a_restart(settings, clock, fake_llm):
    from neurocoach.bootstrap import build_coach_runtime

    first = build_coach_runtime(settings, clock=clock, llm=fake_llm)
    user = first.app.coach.register_user("Camille", "Martin", "camille.m").id
    project = first.app.coach.start_project(user).id
    fake_llm.script("clarify", ProjectBrief(idea_summary=CANDLES, target_outcome="10 ventes"))
    first.agent.send_message(user, project, REAL[2])
    first.checkpointer.conn.close()
    again = build_coach_runtime(settings, clock=clock, llm=fake_llm)
    try:
        fake_llm.calls.clear()
        again.agent.send_message(user, project, "On en était où ?")
        facts = payload(reply_calls(fake_llm)[-1])
        assert facts["sujet"] == CANDLES and facts["brief"]["target_outcome"] == "10 ventes"
        assert len(facts["history"]) >= 2
    finally:
        again.checkpointer.conn.close()


# --- 3. le modele decide, le code autorise ------------------------------------------------


def test_a_plan_requested_by_the_model_is_only_a_proposal(space, fake_llm):
    coach, user, project = space
    fake_llm.script("clarify", ProjectBrief(idea_summary=CANDLES, wants_plan_now=True))
    turn = say(coach, user, project, "Proposez-moi un plan pour démarrer.")
    assert turn.pending is not None and turn.pending["kind"] == "plan"
    assert coach.app.coach.list_tasks(user, project) == []
    assert say(coach, user, project, "oui").notice  # un « oui » ecrit ne confirme jamais
    assert coach.app.coach.list_tasks(user, project) == []


def test_a_plan_is_offered_never_imposed_and_not_proposed_again_for_nothing(space, fake_llm):
    """D-84 (6/6 simulations validees) : tout est connu, le coach propose le plan par une
    question ; il le prepare quand elle accepte, et ne le relance pas sans changement."""
    coach, user, project = space
    ready = ProjectBrief(
        idea_summary=CANDLES, target_outcome="10 ventes", available_minutes_per_day=60,
        budget="200 €", ready_for_plan=True,
    )  # fmt: skip
    fake_llm.script("clarify", ready)
    offer = say(coach, user, project, "Voilà ce que je veux faire.")
    assert offer.pending is None and offer.reply.endswith("prépare un plan détaillé ?")
    fake_llm.script("clarify", ready.model_copy(update={"wants_plan_now": True}))
    first = say(coach, user, project, "Oui.")
    assert first.pending is not None
    coach.agent.decide(user, project, first.pending["pending_action_id"], "cancel")
    fake_llm.script("clarify", ready)
    assert say(coach, user, project, "Merci.").pending is None  # rien de neuf : pas de relance
    # Mesure reelle du 11/11/2026 : le modele reformule le resume du sujet a chaque tour ;
    # une reformulation n'est pas une information nouvelle et ne relance pas le plan.
    fake_llm.script("clarify", ready.model_copy(update={"idea_summary": "Bougies parfumées."}))
    assert say(coach, user, project, "D'accord.").pending is None
    update = {"available_minutes_per_day": 120, "wants_plan_now": True}
    fake_llm.script("clarify", ready.model_copy(update=update))
    assert say(coach, user, project, "J'ai 2 heures par séance, refaites le plan.").pending


def test_a_new_message_says_the_pending_plan_was_not_saved(space, fake_llm):
    """Mesure reelle du 11/11/2026 : « D'accord, rien n'a été modifié. » apparaissait alors
    que la personne n'avait rien refuse ; le fil dit desormais ce qui s'est passe."""
    coach, user, project = space
    fake_llm.script("clarify", ProjectBrief(idea_summary=CANDLES, wants_plan_now=True))
    first = say(coach, user, project, "Proposez-moi un plan.")
    action_id = first.pending["pending_action_id"]
    say(coach, user, project, "Je débute, que dois-je faire en premier ?")
    history = [m["content"] for m in coach.agent.history(user, project)]
    assert "D'accord, rien n'a été modifié." not in history
    assert any("n'a pas été enregistrée, car vous avez envoyé un nouveau" in m for m in history)
    assert coach.app.actions.get_action(user, action_id).status.value == "cancelled"
    assert coach.app.coach.list_tasks(user, project) == []


def test_a_research_accepted_in_the_conversation_is_a_mission_to_approve(space, fake_llm):
    coach, user, project = space
    fake_llm.script("clarify", ProjectBrief(idea_summary=CANDLES, research_request=True))
    say(coach, user, project, "D'accord, faites cette vérification du marché à Lyon.")
    mission = coach.agent.research_pending(user, project)
    assert mission is not None
    assert coach.app.research.mission_report(user, mission.id).queries == []  # rien de lance


def test_out_of_scope_and_preferences_stay_deterministic(space, fake_llm):
    coach, user, project = space
    fake_llm.script("classify_intent", IntentResult(intent="hors_perimetre"))
    seen: list[str] = []
    turn = say(coach, user, project, "Quel médicament pour dormir ?", stream=seen.append)
    assert "avis médical" in turn.reply
    # D-79 : l'intention lue en tete de la sortie du coach arrete la generation avant tout
    # texte affiche ; hors perimetre, la reponse est deterministe, sans second appel.
    assert [t for t, _ in fake_llm.calls] == ["coach_turn"]
    assert seen == []


# --- 4. erreurs explicites, jamais de fausse reponse ----------------------------------------


def test_a_model_failure_is_an_explicit_error_to_retry(space, fake_llm):
    coach, user, project = space
    fake_llm.script("coach_reply", DomainError(ErrorCode.LLM_UNAVAILABLE))
    turn = say(coach, user, project, REAL[1])
    assert turn.reply == USER_MESSAGES[ErrorCode.LLM_UNAVAILABLE]
    assert turn.error and turn.error["code"] == "LLM_UNAVAILABLE"
    assert not any(t in turn.reply for t in TEMPLATES)


def test_an_invalid_coach_output_is_an_explicit_error_and_changes_nothing(space, fake_llm):
    """D-79 : reponse et fiche viennent du meme appel ; une sortie invalide n'enregistre
    rien (ni fiche, ni sujet) et s'affiche comme une erreur a reessayer."""
    coach, user, project = space
    fake_llm.script("coach_turn", DomainError(ErrorCode.LLM_OUTPUT_INVALID))
    turn = say(coach, user, project, REAL[1])
    assert turn.reply == USER_MESSAGES[ErrorCode.LLM_OUTPUT_INVALID] and turn.error
    assert coach.app.coach.get_project(user, project).idea in (None, "", REAL[1])
    assert turn.pending is None


# --- 5. diffusion et mesures ------------------------------------------------------------------


def test_the_reply_is_streamed_progressively_and_measured(space, fake_llm):
    coach, user, project = space
    text = "Un deux trois quatre cinq six sept huit neuf dix onze douze treize « ok »."
    fake_llm.script("coach_reply", text)
    seen: list[str] = []
    turn = say(coach, user, project, REAL[1], stream=seen.append)
    # D-79 : seule la reponse est diffusee (jamais le JSON de la sortie structuree), par
    # fragments croissants, sans classification prealable qui la retarderait.
    assert len(seen) > 2 and seen[-1] == text == turn.reply
    assert all(text.startswith(part) for part in seen)
    assert not any("{" in part or '"intent"' in part for part in seen)
    assert [c["task"] for c in turn.timings["calls"]] == ["coach_turn"]
    timings = turn.timings
    assert 0 <= timings["first_visible"] <= timings["reply_complete"] <= timings["total"]
    assert timings["after_reply"] >= 0
    decision = timings["decision"]
    assert (decision["chosen"], decision["applied"], decision["notice"]) == (
        "conseiller", "conseiller", None,
    )  # fmt: skip


def test_a_status_question_on_an_active_project_needs_one_call(coach, make_planned, fake_llm):
    from factories import ALICE

    planned = make_planned(ALICE, "Bougies")
    fake_llm.calls.clear()
    turn = coach.agent.send_message(ALICE, planned.project.id, "Où en suis-je ?")
    assert [t for t, _ in fake_llm.calls] == ["classify_intent"]
    assert turn.reply.startswith("0 tâche terminée sur")


def test_the_classification_receives_a_compact_context(space, fake_llm):
    coach, user, project = space
    say(coach, user, project, REAL[0])
    fake_llm.calls.clear()
    say(coach, user, project, "J'ai terminé T1.")  # route deterministe : reclassement
    classify = payload([m for t, m in fake_llm.calls if t == "classify_intent"][-1])
    assert set(classify) == {
        "project", "tasks", "preferences", "dernier_message_du_coach", "recherche",
        "messages_precedents",  # D-85 : la raison d'une pause est souvent dite juste avant
    }  # fmt: skip
    assert "history" not in classify and "connu" not in classify
    previous = classify["messages_precedents"]
    assert len(previous) <= 2 and all(len(text) <= 300 for text in previous)
    assert "J'ai terminé T1." not in previous  # le message classe n'y est pas repete
