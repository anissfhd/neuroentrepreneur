"""D-84 : ecarts entre l'application et les six simulations validees (dossier V1).

Chaque test rejoue, avec le faux modele, une sortie reellement produite par gpt-5-mini le
12/11/2026 (transcriptions du dossier) ou une regle des simulations, et verifie ce que le
CODE garantit. La qualite des textes du vrai modele n'est pas jugee ici : elle demande une
campagne reelle autorisee.
"""

# Les traits d'union insecables (U+2011) sont ceux de gpt-5-mini : ils sont voulus.
# ruff: noqa: RUF001

from __future__ import annotations

import socket

import pytest

from factories import ALICE
from neurocoach.agent.guards import clean_brief, drop_example_lists, single_question
from neurocoach.agent.nodes import DISCOVERY_LABELS
from neurocoach.agent.prompts import _TASKS
from neurocoach.agent.schemas import CoachBrief, CoachTurn, IntentResult, ProjectBrief
from neurocoach.domain.models import TaskStatus
from neurocoach.domain.proposals import ChangeProposal

# Questions reellement posees par gpt-5-mini (transcriptions du 12/11/2026).
REAL_DOUBLE_QUESTIONS = [
    (
        "Dans quel pays ou zone comptez‑vous vendre vos photos et quelle clientèle visez‑vous ?",
        "Dans quel pays ou zone comptez‑vous vendre vos photos ?",
    ),
    (
        "Quelles compétences en photographie avez-vous et quel matériel utilisez-vous ?",
        "Quelles compétences en photographie avez-vous ?",
    ),
    (
        "Qu'est‑ce qui vous passionne le plus ou quelles compétences voulez‑vous mettre au "
        "service de ce projet ?",
        "Qu'est‑ce qui vous passionne le plus ?",
    ),
    (
        "Dans quel pays êtes‑vous et quelle clientèle ciblez‑vous ?",
        "Dans quel pays êtes‑vous ?",
    ),
    (
        "Quelle clientèle visez‑vous : débutants, développeurs juniors, freelances ou "
        "entreprises ?",
        "Quelle clientèle visez‑vous ?",
    ),
    (
        "Qu'est-ce qui vous attire le plus en ce moment — un domaine, un type d'activité ou un "
        "problème que vous aimeriez résoudre ?",
        "Qu'est-ce qui vous attire le plus en ce moment ?",
    ),
]
# Campagne reelle V1 du 13/11/2026 : seconde intention introduite par une preposition.
REAL_DOUBLE_QUESTIONS.append(
    (
        "Quelles compétences ou sujets précis aimeriez-vous transmettre et à quel public ?",
        "Quelles compétences ou sujets précis aimeriez-vous transmettre ?",
    )
)
# Questions simples, dont des choix binaires des simulations validees : intactes.
GOOD_QUESTIONS = [
    "Combien d'heures par semaine pouvez‑vous consacrer à ce projet ?",
    "D'après vous, qu'est-ce qui vous a principalement empêché de gagner de l'argent avec ce "
    "projet ?",
    "Préférez-vous commencer avec un seul parfum ou en tester deux ?",
    "Préférez-vous acheter un kit de découverte ou sélectionner les composants séparément ?",
    "Avez-vous déjà essayé de vendre quelque chose ou d'organiser un service en lien avec la "
    "cuisine ?",
    "Quelles activités, sujets ou tâches vous donnent de l'énergie quand vous les faites ?",
]


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("connexion reseau tentee")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def space(coach):
    user = coach.app.coach.register_user("Sam", "Test", "sam.test")
    project = coach.app.coach.start_project(user.id)
    coach.agent.greet(user.id, project.id)
    return coach, user.id, project.id


def turn(stage="decouverte", reply="Bien noté.", question="", next_step="conseiller", **values):
    names = ("plan_requested", "ideas_requested", "plan_change")
    flags = {k: values.pop(k) for k in names if k in values}
    return CoachTurn(intent="information_projet", stage=stage, reply=reply, question=question,
                     fiche=CoachBrief(**values), next_step=next_step, **flags)  # fmt: skip


# --- dialogue : une seule intention par question ----------------------------------------------


@pytest.mark.parametrize(("asked", "kept"), REAL_DOUBLE_QUESTIONS)
def test_a_real_double_question_keeps_a_single_intention(asked, kept):
    assert single_question(drop_example_lists(asked)) == kept


@pytest.mark.parametrize("question", GOOD_QUESTIONS)
def test_single_questions_and_binary_choices_stay_intact(question):
    assert single_question(drop_example_lists(question)) == question


def test_each_discovery_label_names_a_single_topic():
    """Cause racine : « son pays ou sa zone, et sa clientèle » faisait poser deux questions."""
    for label in DISCOVERY_LABELS.values():
        assert ", et " not in label and " et ce qu" not in label, label
    assert "clientèle" not in DISCOVERY_LABELS["zone"]


def test_the_person_receives_one_question_even_if_the_model_writes_two(space, fake_llm):
    coach, user, project = space
    fake_llm.script("coach_turn", turn(
        reply="Vous préférez travailler à distance : on cherchera des clients en ligne.",
        question="Dans quel pays êtes‑vous et quelle clientèle ciblez‑vous ?",
        interests="les outils d'IA",
    ))  # fmt: skip
    reply = coach.agent.send_message(user, project, "J'aime les outils d'IA, à distance.").reply
    assert reply.endswith("Dans quel pays êtes‑vous ?") and reply.count("?") == 1


# --- faits, choix et hypotheses ---------------------------------------------------------------


def test_what_she_said_is_a_fact_and_only_coach_guesses_are_hypotheses():
    """Recette reelle : objectif confirme et budget declare listes en « hypothèses »."""
    said = [
        "Je voudrais gagner environ 200 € par mois en complément de mon salaire.",
        "Je peux investir 150 € au maximum, en privilégiant les outils gratuits.",
    ]
    brief = ProjectBrief(
        target_outcome="Gagner environ 200 € par mois en complément du salaire",
        assumptions=[
            "Veut gagner environ 200 € par mois en complément du salaire",
            "Investir 150 € au maximum en privilégiant les outils gratuits",
            "Les indépendants accepteraient de payer un audit court",
        ],
    )
    cleaned = clean_brief(brief, said)
    assert cleaned.assumptions == ["Les indépendants accepteraient de payer un audit court"]
    assert "Investir 150 € au maximum en privilégiant les outils gratuits" in cleaned.facts
    assert not any("200 €" in fact for fact in cleaned.facts)  # l'objectif a sa ligne


def test_the_plan_states_time_in_her_words_never_a_derived_session(space, fake_llm):
    """Recette reelle : « 8 h/semaine » affiche « 240 minutes par séance de travail »."""
    coach, user, project = space
    fake_llm.script("coach_turn", turn(
        stage="idee_precise", next_step="preparer_plan", plan_requested=True,
        idea_summary="Pack de réponses clients pour petites boutiques en ligne",
        available_minutes_per_day=240, budget="150 €",
        target_outcome="Gagner environ 200 € par mois",
    ))  # fmt: skip
    reply = coach.agent.send_message(
        user, project, "J'ai environ 8 heures par semaine et 150 €. Proposez-moi un plan."
    ).reply
    assert "Temps disponible : environ 8 h par semaine" in reply
    assert "240 minutes par séance" not in reply


# --- recommandation, recherche et plan : consignes du modele ----------------------------------


def test_the_coach_is_told_to_recommend_one_precise_offer_and_propose_the_research():
    prompt = _TASKS["coach_turn"]
    assert "jamais un assemblage de plusieurs services" in prompt
    assert "comment elle évite ce qui a bloqué lors de ses essais passés" in prompt
    assert "propose de vérifier le marché par une recherche" in prompt
    assert "Ne lui demande jamais de choisir elle-même quoi vendre" in prompt
    assert "ne la déduis jamais de ses heures par semaine" in prompt
    assert "sans énumérer les noms de sites" in prompt
    assert "un mot d'accueil suffit" not in prompt  # cause des « Parfait — merci » isoles
    # D-86 (campagne reelle V1) : reformulations « Vous avez… — … » a chaque tour, annonce des
    # points a demander, question reposee mot pour mot, « vos 2 ou 3 … ».
    assert "Ne reformule jamais ce qu'elle vient de dire" in prompt
    assert "n'annonce jamais les points que tu vas lui demander" in prompt
    assert "passe à un autre élément : la question restée sans réponse" in prompt
    assert "Aucun nombre imposé dans une question" in prompt


def test_the_conclusion_and_plan_never_turn_a_guess_into_a_market_fact_or_a_choice():
    conclusion = _TASKS["research_conclusion"]
    assert "prix de test à vérifier, jamais comme un tarif de marché" in conclusion
    assert "la présence de concurrents ne prouve pas que des clients paieront" in conclusion
    assert "Aucun nom de site" in conclusion and "chiffre d'affaires (pas en revenu)" in conclusion
    plan = _TASKS["draft_plan"]
    assert "N'écris jamais qu'elle a choisi ce qu'elle n'a pas décidé" in plan
    assert "est un fait, jamais une hypothèse" in plan
    assert "tâche de vérification auprès de sources officielles avant toute vente" in plan


# --- plan enregistre : modification proposee, taches terminees protegees ----------------------

VAGUE = "Je veux vendre des bougies artisanales, mais je ne sais pas par où commencer."
DETAILS = (
    "Tester si des personnes seraient intéressées. J'ai 30 minutes par jour. "
    "Mon budget est de 100 €. Proposez-moi un plan."
)


@pytest.fixture
def planned(coach):
    project = coach.app.coach.create_project(ALICE, "Bougies artisanales", VAGUE)
    coach.agent.send_message(ALICE, project.id, VAGUE)
    proposal = coach.agent.send_message(ALICE, project.id, DETAILS)
    coach.agent.decide(ALICE, project.id, proposal.pending["pending_action_id"], "confirm")
    return project


def test_a_change_to_a_saved_plan_is_accepted_or_reworked_and_done_tasks_stay(coach, planned):
    tasks = coach.app.coach.list_tasks(ALICE, planned.id)
    coach.app.coach.set_task_status(ALICE, tasks[0].id, TaskStatus.DONE)
    coach.llm.script("classify_intent", IntentResult(intent="modifier_tache"))
    coach.llm.script("draft_change", ChangeProposal(
        changes=[{"op": "update", "task_ref": "T2", "fields": {"title": "Montrer à l'entourage"}}],
        rationale="Vous préférez votre entourage à une page en ligne.",
    ))  # fmt: skip
    proposal = coach.agent.send_message(
        ALICE, planned.id, "Remplace T2 : je montre à mon entourage."
    )
    assert proposal.pending is not None
    assert "« Accepter les modifications »" in proposal.reply
    assert "Les tâches déjà terminées ne sont jamais modifiées." in proposal.reply
    # « Demander un changement » : rien n'est ecrit.
    coach.agent.decide(
        ALICE, planned.id, proposal.pending["pending_action_id"], "cancel", reason="change"
    )
    after = coach.app.coach.list_tasks(ALICE, planned.id)
    assert [t.title for t in after] == [t.title for t in tasks]
    # Une modification d'une tache terminee est refusee par le domaine.
    coach.llm.script("classify_intent", IntentResult(intent="modifier_tache"))
    coach.llm.script("draft_change", ChangeProposal(
        changes=[{"op": "update", "task_ref": "T1", "fields": {"title": "Autre chose"}}],
    ))  # fmt: skip
    refused = coach.agent.send_message(ALICE, planned.id, "Change T1 en autre chose.")
    assert refused.pending is None
    done = coach.app.coach.list_tasks(ALICE, planned.id)[0]
    assert done.status is TaskStatus.DONE and done.title == tasks[0].title


# --- plan : propose par une question, prepare a la demande ------------------------------------


def test_a_complete_profile_gets_a_plan_offer_never_an_imposed_plan(space, fake_llm):
    """6/6 simulations : « Voulez-vous que je vous prépare un plan ? », puis le plan au oui.
    Recette dans l'interface (faux modele, 13/11/2026) : plan affiche sans demande."""
    coach, user, project = space
    fake_llm.script("coach_turn", turn(
        stage="idee_precise", next_step="preparer_plan", question="Voulez-vous un plan ?",
        idea_summary="Correction de CV pour étudiants", available_minutes_per_day=60,
        budget="50 €",
    ))  # fmt: skip
    offer = coach.agent.send_message(user, project, "J'ai 4 h par semaine et 50 €.")
    assert offer.pending is None and "draft_plan" not in [t for t, _ in fake_llm.calls]
    assert offer.notice.endswith("je la prépare dès que vous me la demandez.")
    accepted = coach.agent.send_message(user, project, "Oui, préparez-moi un plan.")
    assert accepted.pending is not None and accepted.pending["kind"] == "plan"


def test_a_requested_plan_without_any_idea_is_refused_with_the_reason(space, fake_llm):
    coach, user, project = space
    fake_llm.script("coach_turn", turn(stage="decouverte", next_step="preparer_plan",
                                       plan_requested=True))  # fmt: skip
    refused = coach.agent.send_message(user, project, "Faites-moi un plan.")
    assert refused.pending is None
    assert refused.notice == (
        "Aucune proposition de plan n'a été préparée : il manque encore votre idée. "
        "Vous pouvez aussi demander un plan provisoire."
    )


def test_a_research_asked_after_requesting_a_change_is_proposed_not_a_plan(space, fake_llm):
    """Recette dans l'interface (13/11/2026) : apres « Demander un changement »,
    « Vérifiez d'abord le marché belge : la concurrence et les prix » donnait un plan."""
    coach, user, project = space
    fake_llm.script("coach_turn", turn(
        stage="idee_precise", next_step="preparer_plan", plan_requested=True,
        idea_summary="Correction de CV pour étudiants en Belgique", market="Belgique",
    ))  # fmt: skip
    first = coach.agent.send_message(user, project, "Proposez-moi un plan.")
    coach.agent.decide(user, project, first.pending["pending_action_id"], "cancel", reason="change")
    fake_llm.script("coach_turn", turn(stage="idee_precise", next_step="conseiller",
                                       plan_change=True))  # fmt: skip
    asked = coach.agent.send_message(
        user, project, "Vérifiez d'abord le marché belge : la concurrence et les prix."
    )
    assert asked.pending is None and coach.agent.research_pending(user, project) is not None
    assert [t for t, _ in fake_llm.calls][-2:] == ["coach_turn", "research_spec"]


# --- D-86 : reformulations reelles de gpt-5-mini (campagne V1 du 13/11/2026) ----------------

ECHOES = [
    (
        "Vous avez déjà lancé une boutique de vêtements en ligne il y a deux ans, ça n'a pas "
        "marché et vous voulez retenter mais sans savoir quoi lancer cette fois.",
        "J'ai déjà essayé de créer une boutique de vêtements en ligne il y a deux ans, ça n'a "
        "pas marché. Je voudrais retenter quelque chose, mais je ne sais pas quoi.",
    ),
    (
        "Parfait — utile : vous avez de bonnes compétences techniques (freins, vitesses, pneus, "
        "chaînes) apprises en autonomie, et vous travaillez comme comptable en journée.",
        "Je règle les freins et les vitesses, je change les pneus et les chaînes. Je n'ai pas "
        "de formation, j'ai appris seul. Dans la vie je suis comptable dans une PME.",
    ),
]
# Phrases qui apportent quelque chose (campagne reelle et simulations validees) : gardees.
USEFUL = [
    (
        "Vous avez 5 ans d'expérience comme assistante administrative — c'est un atout pour "
        "l'organisation, la gestion et la relation client dans un futur projet.",
        "Je travaille comme assistante administrative depuis cinq ans.",
    ),
    (
        "Le stock acheté avant de vérifier la demande a été un vrai risque.",
        "J'avais acheté beaucoup de bijoux à l'avance, mais presque personne n'achetait.",
    ),
    (
        "Vous avez donc déjà une expérience concrète dans la résolution de problèmes.",
        "Je travaille dans le support informatique. J'utilise ChatGPT régulièrement.",
    ),
    ("Je vois.", "Je n'avais presque pas de clients."),
]


@pytest.mark.parametrize(("reply", "said"), ECHOES)
def test_a_sentence_that_repeats_her_message_is_recognised(reply, said):
    from neurocoach.agent.guards import echoes

    assert echoes(reply, said)


@pytest.mark.parametrize(("reply", "said"), USEFUL)
def test_a_sentence_that_adds_something_is_kept(reply, said):
    from neurocoach.agent.guards import echoes

    assert not echoes(reply, said)


def test_the_person_sees_only_the_question_after_a_reformulation(space, fake_llm):
    coach, user, project = space
    said, reply = ECHOES[1][1], ECHOES[1][0]
    fake_llm.script("coach_turn", turn(reply=reply, question="Combien d'heures par semaine ?"))
    shown = coach.agent.send_message(user, project, said)
    assert shown.reply == "Combien d'heures par semaine ?"
    assert "reformulation_retiree" in shown.timings["decision"]["contract"]


def test_when_everything_is_known_the_coach_is_told_to_recommend(space, fake_llm):
    """Campagne reelle V1 (13/11/2026) : diagnostic complet, etape « decouverte » gardee par le
    modele et « Quelle offre voulez-vous lancer précisément ? » au lieu d'une recommandation."""
    coach, user, project = space
    known = {
        "interests": "le vélo", "skills": "réglages et réparations de vélos",
        "past_attempts": "une chaîne YouTube sans revenus", "target_outcome": "150 € par mois",
        "budget": "200 €", "market": "Toulouse", "available_minutes_per_day": 60,
    }  # fmt: skip
    said = (
        "J'aime le vélo, je fais des réglages et des réparations de vélos ; ma chaîne YouTube "
        "n'a rien rapporté ; je vise 150 € par mois avec 200 € à Toulouse, 1 h par jour."
    )
    fake_llm.script("coach_turn", turn(stage="decouverte", question="Autre chose ?", **known))
    coach.agent.send_message(user, project, said)  # la fiche est connue apres ce tour
    fake_llm.script("coach_turn", turn(
        stage="decouverte", reply="Une piste se dessine pour vous.",
        question="Quelle offre voulez-vous lancer : atelier, domicile ou forfaits ?",
    ))  # fmt: skip
    second = coach.agent.send_message(user, project, "Je peux recevoir les clients le samedi.")
    facts = [m for t, m in fake_llm.calls if t == "coach_turn"][-1][-1]["content"]
    assert '"etape_conseillee": "pistes"' in facts
    assert "etape_corrigee_decouverte_terminee" in second.timings["decision"]["contract"]
    assert second.timings["decision"]["stage"] == "pistes"
    assert "ne lui demande pas de choisir son offre" in _TASKS["coach_turn"]


def test_a_research_offered_by_a_question_waits_for_her_answer(space, fake_llm):
    """Campagne reelle V1 : question « Souhaitez-vous que je lance une vérification rapide du
    marché local… ? » et carte de recherche affichee dans le meme tour, avant son accord."""
    coach, user, project = space
    fake_llm.script("coach_turn", turn(
        stage="pistes", next_step="preparer_recherche",
        reply="Je recommande un service d'atelier sur rendez-vous.",
        question="Souhaitez-vous que je lance une vérification rapide du marché local "
        "(concurrents, tarifs, demande) avant de valider cette piste ?",
        idea_summary="Atelier vélo sur rendez-vous", market="Toulouse",
    ))  # fmt: skip
    offer = coach.agent.send_message(user, project, "Je ne sais pas trop, les trois me tentent.")
    assert coach.agent.research_pending(user, project) is None
    assert offer.timings["decision"].get("offre_de_recherche") is True
    assert offer.reply.endswith("avant de valider cette piste ?")
    fake_llm.script("coach_turn", turn(stage="pistes", question="", next_step="preparer_recherche"))
    coach.agent.send_message(user, project, "Oui, vérifiez la concurrence et les prix à Toulouse.")
    assert coach.agent.research_pending(user, project) is not None  # apres son accord


# Conclusion reellement produite par gpt-5-mini le 13/11/2026 (extrait).
REAL_CONCLUSION = (
    "La recherche montre des éléments favorables : vous avez les compétences pratiques (avis), "
    "le format express existe localement et les clients cherchent des interventions rapides "
    "(faits/estimations, niveau de preuve partiel à factuel). En revanche ça ne prouve pas que "
    "des clients paieront chez vous, ni si l'assurance est compatible avec 200 € "
    "(niveau_de_preuve : inconnu ou partiel pour ces points). Format de départ : intervention "
    "courte (moins de 30 min)."
)


def test_the_conclusion_shows_no_internal_label_or_field_name():
    from neurocoach.agent.guards import drop_internal_labels

    clean = drop_internal_labels(REAL_CONCLUSION)
    for label in ("(avis)", "faits/estimations", "niveau_de_preuve", "niveau de preuve partiel"):
        assert label not in clean, label
    assert "vous avez les compétences pratiques, le format express" in clean
    assert "compatible avec 200 €." in clean
    assert "(moins de 30 min)" in clean  # une parenthese utile reste


def test_the_conclusion_prompt_no_longer_suggests_a_field_name():
    assert "(niveau_de_preuve)" not in _TASKS["research_conclusion"]
    assert (
        "sans nom de champ ni nature des éléments entre parenthèses"
        in _TASKS["research_conclusion"]
    )


def test_a_described_change_is_honoured_even_when_the_model_misses_it(space, fake_llm):
    """Campagne reelle V1 (13/11/2026) : apres « Demander un changement », « Je ne veux pas
    publier sur Facebook ni sur YouTube. Je préfère une affiche… » : plan_change false et une
    question du modele au lieu du plan modifie."""
    coach, user, project = space
    fake_llm.script("coach_turn", turn(
        stage="idee_precise", question="", next_step="preparer_plan", plan_requested=True,
        idea_summary="Forfait d'entretien vélo express", budget="200 €",
    ))  # fmt: skip
    first = coach.agent.send_message(user, project, "Préparez-moi un plan détaillé.")
    coach.agent.decide(user, project, first.pending["pending_action_id"], "cancel", reason="change")
    fake_llm.script("coach_turn", turn(
        stage="idee_precise", next_step="conseiller", plan_change=False,
        question="Voulez-vous que je prépare un texte d'affiche ?",
    ))  # fmt: skip
    second = coach.agent.send_message(
        user, project, "Je ne veux pas publier sur Facebook. Je préfère une affiche dans "
        "mon immeuble et le bouche-à-oreille."
    )  # fmt: skip
    assert second.pending is not None and second.pending["kind"] == "plan"
    plan_facts = [m for t, m in fake_llm.calls if t == "draft_plan"][-1][-1]["content"]
    assert "proposition_precedente" in plan_facts


def test_her_budget_and_goal_paraphrased_by_the_model_are_facts_not_hypotheses():
    """Campagne reelle V1 : « budget limité à 200 € » et « objectif : atteindre ~150 €/mois »
    en « Hypothèses à vérifier » ; une vraie hypothese chiffree reste une hypothese."""
    said = [
        "Environ 5 heures par semaine, surtout le samedi. Et je peux investir 200 € au maximum.",
        "Je voudrais gagner environ 150 € par mois pour commencer.",
        "L'an dernier j'ai lancé une chaîne YouTube sur le vélo : 15 vidéos, aucun revenu.",
    ]
    brief = ProjectBrief(
        assumptions=[
            "budget limité à 200 €",
            "objectif : atteindre ~150 €/mois avec interventions le samedi",
            "Les clients paieront 15 € par intervention",
        ]
    )
    cleaned = clean_brief(brief, said)
    assert cleaned.assumptions == ["Les clients paieront 15 € par intervention"]
    assert "budget limité à 200 €" in cleaned.facts


def test_no_field_name_reaches_the_plan_text():
    from neurocoach.agent.guards import humanize_field_names

    shown = humanize_field_names("Ressources : synthèse prix locaux (prix_local).")
    assert shown == "Ressources : synthèse prix locaux (prix local)."


def test_plan_changes_get_the_long_delay_and_a_low_effort():
    """Campagne reelle V1 : draft_change au delai de 30 s et a l'effort par defaut : 60,6 s puis
    « Le service de langage ne répond pas » pour une adaptation de plan."""
    from neurocoach.agent.llm import SLOW_TASK_EFFORT

    assert SLOW_TASK_EFFORT["draft_change"] == "low"
    assert SLOW_TASK_EFFORT["draft_plan"] == "low"
