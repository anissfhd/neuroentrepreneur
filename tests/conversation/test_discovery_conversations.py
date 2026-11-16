"""D-81 : le coach decouvre la personne avant de conseiller (consultant experimente).

Faux modele : ces tests verifient le contrat du tour (etape, une seule question a part,
aucune liste en decouverte), la memoire du diagnostic (deja connu, questions deja posees),
le contexte transmis au modele et les decisions de workflow. Ils ne prouvent PAS la
pertinence des questions ni la qualite des conseils de gpt-5-mini : c'est le role de
``scripts/evaluate_discovery.py --real-api`` (appels payants, sur autorisation).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from neurocoach.agent.schemas import CoachBrief, CoachTurn

ROOT = Path(__file__).resolve().parents[2]
FIRST = (
    "Bonjour, j'aimerais créer mon propre business, mais je ne sais pas par où commencer. "
    "Pouvez-vous m'aider ?"
)
# Reponse REELLE de gpt-5-mini lors de la recette du 12/11/2026 (echec : pistes, taches et
# duree avant de connaitre la personne). Donnee de test, jamais une reponse du coach.
FAILED_REPLY = (
    "Très bien — commençons simplement et concret. Trois pistes faciles à explorer pour "
    "démarrer sans plan lourd : 1) Prestation en freelance basée sur vos compétences (rapide à "
    "lancer, validation client immédiate). 2) Produit numérique (cours, guide, modèle) : "
    "scalable et testable avec peu de coûts fixes. 3) Service local ou atelier (activité en "
    "présentiel ou à la demande) : utile si vous aimez le contact et tester une offre en vrai. "
    "Ces options conviennent aux personnes qui veulent avancer vite et limiter les risques car "
    "elles permettent de tester la demande avant d'investir lourdement. En attendant votre "
    "réponse, si vous êtes prêt·e : 1) notez 3 compétences ou expériences que vous avez, 2) "
    "pensez à qui pourrait être intéressé par ce que vous faites, 3) bloquez 60 minutes cette "
    "semaine pour qu'on choisisse la piste et qu'on trace le premier petit test."
)
QUESTION = "Qu'est-ce qui vous passionne ou vous intéresse particulièrement ?"


@pytest.fixture
def space(coach):
    user = coach.app.coach.register_user("Camille", "Martin", "camille.m")
    project = coach.app.coach.start_project(user.id)
    coach.agent.greet(user.id, project.id)
    return coach, user.id, project.id


def say(coach, user, project, text, **kwargs):
    return coach.agent.send_message(user, project, text, **kwargs)


def facts_of(llm, index=-1) -> dict:
    content = [m for t, m in llm.calls if t == "coach_turn"][index][-1]["content"]
    return json.loads(content.split("<donnees_projet>\n", 1)[1].split("\n</donnees_projet>")[0])


def turn(stage="decouverte", reply="Merci, je vous écoute.", question=QUESTION, **values):
    """Sortie imposee du modele pour un tour de decouverte."""
    return CoachTurn(intent="information_projet", stage=stage, reply=reply, question=question,
                     fiche=CoachBrief(**values))  # fmt: skip


# --- le premier message exact de la recette ---------------------------------------------------


def test_the_first_vague_message_opens_a_discovery_conversation(space, fake_llm):
    coach, user, project = space
    seen: list[str] = []
    result = say(coach, user, project, FIRST, stream=seen.append)
    decision = result.timings["decision"]
    assert decision["stage"] == "decouverte"
    assert result.reply.count("?") == 1 and result.reply.endswith(decision["question"])
    assert [t for t, _ in fake_llm.calls] == ["coach_turn"]  # ni plan, ni recherche
    assert result.pending is None and coach.agent.research_pending(user, project) is None
    # Une envie generale n'est pas une idee : rien n'est enregistre comme sujet, aucun titre.
    assert coach.app.coach.get_project(user, project).idea in (None, "")
    assert coach.agent.title_suggestion(user, project) is None
    # Ce que le modele recevait : rien de connu sur la personne, tout a decouvrir.
    discovery = facts_of(fake_llm)["decouverte"]
    assert discovery["idee_retenue"] is False and discovery["deja_connu"] == {}
    assert discovery["assez_pour_des_pistes"] is False
    assert "ses centres d'intérêt" in discovery["a_decouvrir"]
    assert seen and seen[-1].endswith(decision["question"])  # diffuse : reponse puis question


def test_a_list_of_businesses_and_tasks_during_discovery_is_not_shown(space, fake_llm):
    """Le modele a declare l'etape « decouverte » mais ecrit des pistes et des taches : le
    code ne garde que sa question (aucun texte ajoute)."""
    coach, user, project = space
    fake_llm.script("coach_turn", turn(reply=FAILED_REPLY))
    result = say(coach, user, project, FIRST)
    assert result.reply == QUESTION
    assert result.timings["decision"]["contract"] == ["liste_en_decouverte"]


def test_a_question_hidden_in_the_reply_is_removed(space, fake_llm):
    coach, user, project = space
    fake_llm.script(
        "coach_turn",
        turn(reply="Je vous accompagne volontiers. Quel est votre métier ?", question=QUESTION),
    )
    result = say(coach, user, project, FIRST)
    assert result.reply == f"Je vous accompagne volontiers.\n\n{QUESTION}"
    assert "question_dans_la_reponse" in result.timings["decision"]["contract"]


# --- memoire du diagnostic ---------------------------------------------------------------------


def test_what_is_learned_is_given_back_and_never_asked_again(space, fake_llm):
    coach, user, project = space
    fake_llm.script("coach_turn", turn())
    say(coach, user, project, FIRST)
    fake_llm.script("coach_turn", turn(question="Qu'aimez-vous faire de votre temps libre ?",
                                       interests="la cuisine et recevoir"))  # fmt: skip
    say(coach, user, project, "J'aime cuisiner et recevoir des amis.")
    fake_llm.script("coach_turn", turn(question="Quel est votre parcours ?",
                                       skills="organisation, gestion administrative"))  # fmt: skip
    say(coach, user, project, "Je suis très organisée, je travaille dans l'administratif.")
    say(coach, user, project, "Je voudrais un complément de revenu.")
    discovery = facts_of(fake_llm)["decouverte"]
    assert discovery["deja_connu"]["ses centres d'intérêt"] == "la cuisine et recevoir"
    assert "ce qu'elle sait faire (compétences)" in discovery["deja_connu"]
    assert "ses centres d'intérêt" not in discovery["a_decouvrir"]
    assert discovery["questions_deja_posees"] == [
        QUESTION, "Qu'aimez-vous faire de votre temps libre ?", "Quel est votre parcours ?",
    ]  # fmt: skip
    system = [m for t, m in fake_llm.calls if t == "coach_turn"][-1][0]["content"]
    assert "jamais une question de decouverte.questions_deja_posees" in system


def test_the_diagnosis_survives_a_restart(settings, clock, fake_llm):
    from neurocoach.bootstrap import build_coach_runtime

    first = build_coach_runtime(settings, clock=clock, llm=fake_llm)
    user = first.app.coach.register_user("Camille", "Martin", "camille.m").id
    project = first.app.coach.start_project(user).id
    fake_llm.script("coach_turn", turn(interests="la photo de paysage"))
    first.agent.send_message(user, project, "J'adore la photo de paysage.")
    first.checkpointer.conn.close()
    again = build_coach_runtime(settings, clock=clock, llm=fake_llm)
    try:
        again.agent.send_message(user, project, "Je fais aussi beaucoup de randonnée.")
        discovery = facts_of(fake_llm)["decouverte"]
        assert discovery["deja_connu"]["ses centres d'intérêt"] == "la photo de paysage"
        assert discovery["questions_deja_posees"] == [QUESTION]
    finally:
        again.checkpointer.conn.close()


# --- progression : pistes au bon moment, idee precise, conseil immediat ------------------------


def test_ideas_are_offered_only_once_the_person_is_known(space, fake_llm):
    coach, user, project = space
    fake_llm.script("coach_turn", turn(interests="transmettre", skills="développement web"))
    say(coach, user, project, "J'aime transmettre et je suis développeur web.")
    assert facts_of(fake_llm)["decouverte"]["assez_pour_des_pistes"] is False
    fake_llm.script("coach_turn", turn(motivation="un revenu complémentaire",
                                       available_minutes_per_day=60))  # fmt: skip
    say(coach, user, project, "Je veux un revenu complémentaire, j'ai une heure par jour.")
    say(coach, user, project, "Plutôt en ligne.")
    # D-82 (recette du 12/11/2026 : pistes des que le temps etait connu) : un consultant
    # connait aussi les essais passes, le budget et la zone avant de recommander.
    discovery = facts_of(fake_llm)["decouverte"]
    assert discovery["assez_pour_des_pistes"] is False
    assert discovery["manque_avant_recommandation"] == [
        "ses essais passés de projet", "son budget", "son pays ou sa zone de vente",
    ]  # fmt: skip
    fake_llm.script("coach_turn", turn(past_attempts="une page Instagram arrêtée",
                                       budget="150 €", market="France, TPE"))  # fmt: skip
    say(
        coach,
        user,
        project,
        "J'ai déjà tenté une page Instagram, arrêtée ; 150 € ; la France, des TPE.",
    )
    say(coach, user, project, "Voilà.")
    assert facts_of(fake_llm)["decouverte"]["assez_pour_des_pistes"] is True


def test_no_plan_during_discovery_or_while_choosing_ideas(space, fake_llm):
    coach, user, project = space
    for stage in ("decouverte", "pistes"):
        fake_llm.script("coach_turn", CoachTurn(
            intent="information_projet", stage=stage, reply="D'accord.", question=QUESTION,
            fiche=CoachBrief(available_minutes_per_day=60, budget="300 €"),
            next_step="preparer_plan",
        ))  # fmt: skip
        result = say(coach, user, project, "J'ai une heure par jour et 300 €.")
        assert result.pending is None and "pas encore choisi votre idée" in result.notice
    assert "draft_plan" not in [t for t, _ in fake_llm.calls]
    # Demande explicite : permise (provisoire, hypotheses signalees).
    fake_llm.script("coach_turn", CoachTurn(
        intent="demande_plan", stage="pistes", reply="Voici.", next_step="preparer_plan",
        plan_requested=True, fiche=CoachBrief(idea_summary="Cours de cuisine à domicile"),
    ))  # fmt: skip
    assert say(coach, user, project, "Faites-moi un plan provisoire.").pending is not None


def test_a_precise_idea_skips_the_diagnosis(space, fake_llm):
    coach, user, project = space
    result = say(coach, user, project, "Je veux ouvrir un food truck de crêpes à Nantes.")
    assert result.timings["decision"]["stage"] == "idee_precise"
    say(coach, user, project, "Par quoi commencer ?")
    assert facts_of(fake_llm)["decouverte"]["idee_retenue"] is True
    assert coach.agent.title_suggestion(user, project)  # un titre, une fois l'idee retenue


def test_an_explicit_request_for_immediate_advice_is_answered(space, fake_llm):
    coach, user, project = space
    result = say(coach, user, project, "Donnez-moi directement un conseil pour démarrer.")
    assert result.timings["decision"]["stage"] == "conseil_immediat"
    assert result.pending is None


# --- six profils, joues tour par tour (logique du code) ----------------------------------------


def _harness():
    spec = importlib.util.spec_from_file_location(
        "evaluate_discovery", ROOT / "scripts" / "evaluate_discovery.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_six_profiles_respect_the_conversation_contract(coach):
    harness = _harness()
    results = harness.run(coach)
    failed = {
        (key, n, name)
        for key, turns in results.items()
        for n, t in enumerate(turns, 1)
        for name, ok in t.checks.items()
        if not ok
    }
    assert not failed
    assert {s.key for s in harness.SCENARIOS} == {
        "aucune_idee", "interets_progressifs", "echec_passe", "idee_precise",
        "infos_spontanees", "conseil_immediat",
    }  # fmt: skip
    # Le diagnostic progresse : ce qui est connu ne diminue jamais au fil des tours.
    for turns in results.values():
        sizes = [len(t.known) for t in turns]
        assert sizes == sorted(sizes)
