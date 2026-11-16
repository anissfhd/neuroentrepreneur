"""Non-regression des trois corrections D-61 (apres la confirmation Terra du 10/11/2026).

1. Ne jamais inventer une tache : sans designation, le coach demande laquelle.
2. Surcharge : un allegement concret du plan existant, propose tout de suite, jamais applique
   sans clic, sans tache ni duree inventee.
3. Question repetee : un objectif provisoire a confirmer, jamais retenu sans accord.

Les sorties des modeles reels sont reproduites avec le faux LLM scripte : Terra (constats de
la confirmation) et gpt-5-mini (comptes rendus R0), pour verifier la compatibilite des deux.
"""

from __future__ import annotations

import re

import pytest

from factories import ALICE
from neurocoach.agent.guards import (
    REPLAN_QUESTION,
    REPLAN_REQUEST,
    WHICH_DELETE_QUESTION,
    WHICH_TASK_QUESTION,
    designated_refs,
    is_lightening,
    lighter_step,
    uses_tutoiement,
)
from neurocoach.agent.schemas import IntentResult
from neurocoach.domain.proposals import ChangeProposal

VAGUE = "Je veux vendre des bougies artisanales, mais je ne sais pas par où commencer."
DETAILS = (
    "Tester si des personnes seraient intéressées. J'ai 30 minutes par jour. "
    "Mon budget est de 100 €. Proposez-moi un plan."
)
DELAY = "Cette semaine je n'ai rien pu faire, je suis débordée."
GARAGE = (
    "bon ben voilà j'ai des bougies plein mon garage et je me demande si ça vaut le coup de "
    "les vendre"
)
UNSURE = "je sais pas trop, peut-être voir si des voisins en veulent, j'ai genre une demi-heure"


@pytest.fixture
def draft(coach):
    return coach.app.coach.create_project(ALICE, "Bougies du garage", "")


@pytest.fixture
def planned(coach):
    """Plan du faux LLM : T1 20 min, T2 20 min (apres T1), T3 30 min (apres T2)."""
    project = coach.app.coach.create_project(ALICE, "Bougies artisanales", "")
    coach.agent.send_message(ALICE, project.id, VAGUE)
    turn = coach.agent.send_message(ALICE, project.id, DETAILS)
    coach.agent.decide(ALICE, project.id, turn.pending["pending_action_id"], "confirm")
    return project


def _say(coach, project, text):
    return coach.agent.send_message(ALICE, project.id, text)


def _tasks(coach, project):
    return coach.app.coach.list_tasks(ALICE, project.id)


def _estimates(coach, project):
    return {task.ref: task.estimate_minutes for task in _tasks(coach, project)}


def _clear(reply: str) -> None:
    """Lisibilite (entrepreneurs neuroatypiques) : court, une question, vouvoiement, sans jargon."""
    assert reply.count("?") <= 1
    assert not uses_tutoiement(reply)
    assert len(re.split(r"(?<=[.!?])\s+", reply.strip())) <= 4
    assert not re.search(r"task_ref|estimate_minutes|VALIDATION|erreur|invalide", reply)


# --- 1. ne jamais inventer une tache --------------------------------------------------------


@pytest.mark.parametrize(
    "model_change",
    [
        {"op": "update", "task_ref": "T1", "fields": {}},  # sortie de Terra (confirmation)
        {"op": "update", "task_ref": "T1", "fields": {"title": "Décrire mieux"}},  # devinee
        {"op": "update", "fields": {"title": "Sans référence"}},
    ],
)
def test_a_change_without_a_designated_task_asks_which_one(coach, planned, model_change):
    before = _tasks(coach, planned)
    coach.llm.script("classify_intent", IntentResult(intent="modifier_tache", task_ref="T1"))
    coach.llm.script("draft_change", ChangeProposal(changes=[model_change]))
    turn = _say(coach, planned, "Je voudrais changer quelque chose dans le plan.")
    assert turn.reply == WHICH_TASK_QUESTION
    assert "pour T1" not in turn.reply
    assert turn.pending is None
    assert _tasks(coach, planned) == before
    _clear(turn.reply)


def test_a_guessed_deletion_is_never_proposed(coach, planned):
    coach.llm.script("classify_intent", IntentResult(intent="supprimer_tache", task_ref="T3"))
    coach.llm.script("draft_change", ChangeProposal(changes=[{"op": "delete", "task_ref": "T3"}]))
    turn = _say(coach, planned, "Je voudrais retirer une tâche.")
    assert turn.reply == WHICH_DELETE_QUESTION
    assert turn.pending is None
    assert len(_tasks(coach, planned)) == 3


@pytest.mark.parametrize(
    "text",
    ["Passe T2 à 15 minutes.", "Passe la deuxième tâche à 15 minutes.",
     "Passe « Préparer cinq questions » à 15 minutes."],
)  # fmt: skip
def test_a_designated_task_still_gets_a_proposal(coach, planned, text):
    coach.llm.script("classify_intent", IntentResult(intent="modifier_tache"))
    coach.llm.script(
        "draft_change",
        ChangeProposal(
            changes=[{"op": "update", "task_ref": "T2", "fields": {"estimate_minutes": 15}}]
        ),
    )
    turn = _say(coach, planned, text)
    assert turn.pending is not None
    assert _estimates(coach, planned)["T2"] == 20  # rien avant le clic


def test_the_task_named_by_the_coach_counts_for_the_next_answer(coach, planned):
    coach.llm.script("classify_intent", IntentResult(intent="modifier_tache", task_ref="T2"))
    coach.llm.script(
        "draft_change", ChangeProposal(changes=[{"op": "update", "task_ref": "T2", "fields": {}}])
    )
    question = _say(coach, planned, "Modifie T2.")
    assert question.reply.startswith("Que souhaitez-vous changer pour T2 :")
    coach.llm.script("classify_intent", IntentResult(intent="modifier_tache", task_ref="T2"))
    coach.llm.script(
        "draft_change",
        ChangeProposal(
            changes=[{"op": "update", "task_ref": "T2", "fields": {"estimate_minutes": 15}}]
        ),
    )
    turn = _say(coach, planned, "La durée : 15 minutes.")
    assert turn.pending is not None


def test_a_request_about_the_whole_plan_is_not_blocked(coach, planned):
    coach.llm.script("classify_intent", IntentResult(intent="modifier_tache"))
    coach.llm.script(
        "draft_change",
        ChangeProposal(
            changes=[
                {"op": "update", "task_ref": ref, "fields": {"estimate_minutes": 15}}
                for ref in ("T1", "T2", "T3")
            ]
        ),
    )
    turn = _say(coach, planned, "Mets toutes les tâches à 15 minutes.")
    assert turn.pending is not None


def test_gpt_5_mini_deadline_proposal_on_an_ordinal_is_kept(coach, planned):
    """Sortie de gpt-5-mini en R0 (« Décale la deuxième tâche à vendredi », echeances actives)."""
    coach.app.coach.update_preferences(ALICE, deadlines_enabled=True)
    coach.llm.script("classify_intent", IntentResult(intent="modifier_tache", task_ref="T2"))
    coach.llm.script(
        "draft_change",
        ChangeProposal(
            changes=[{"op": "update", "task_ref": "T2", "fields": {"due_date": "2026-11-13"}}]
        ),
    )
    turn = _say(coach, planned, "Décale la deuxième tâche à vendredi")
    assert turn.pending is not None
    assert "vendredi 13 novembre 2026" in turn.reply


def test_designated_refs_rules():
    catalog = [("a", 1, "Décrire le client visé"), ("b", 2, "Préparer cinq questions")]
    assert designated_refs("Je voudrais changer quelque chose", catalog, None) == set()
    assert designated_refs("Modifie T2", catalog, None) == {"T2"}
    assert designated_refs("la première tâche", catalog, None) == {"T1"}
    assert designated_refs("Préparer cinq questions plus vite", catalog, None) == {"T2"}
    named = "Que souhaitez-vous changer pour T2 : le titre, la durée estimée ou la description ?"
    assert designated_refs("La durée", catalog, named) == {"T2"}


# --- 2. surcharge : allegement concret, jamais applique sans clic ---------------------------


@pytest.mark.parametrize("model_intent", ["replanifier", "autre", "etat_projet"])
@pytest.mark.parametrize(
    "text",
    [DELAY, "Je suis fatiguée, mon plan est trop lourd.", "Je suis épuisé en ce moment."],
)
def test_overload_with_an_empty_model_change_gets_a_concrete_lighter_step(
    coach, planned, model_intent, text
):
    """Sortie de Terra (confirmation, 3 fois sur 4) : modification vide."""
    coach.llm.script("classify_intent", IntentResult(intent=model_intent))
    coach.llm.script(
        "draft_change", ChangeProposal(changes=[{"op": "update", "task_ref": "T1", "fields": {}}])
    )
    turn = _say(coach, planned, text)
    assert turn.pending is not None
    assert "Tâche T1 modifiée — durée estimée : 10 minutes (au lieu de 20 minutes)" in turn.reply
    assert "le plan s'adapte" in turn.reply
    assert "Nouvelle tâche" not in turn.reply and "échéance" not in turn.reply
    assert REPLAN_QUESTION not in turn.reply
    assert _estimates(coach, planned) == {"T1": 20, "T2": 20, "T3": 30}  # rien avant le clic


def test_the_lighter_step_is_saved_only_after_confirmation(coach, planned):
    coach.llm.script("classify_intent", IntentResult(intent="replanifier"))
    coach.llm.script(
        "draft_change", ChangeProposal(changes=[{"op": "update", "task_ref": "T1", "fields": {}}])
    )
    turn = _say(coach, planned, DELAY)
    notice = _say(coach, planned, "oui")  # un « oui » ecrit ne confirme jamais
    assert notice.reply is None and "Confirmer" in notice.notice
    assert _estimates(coach, planned)["T1"] == 20
    coach.agent.decide(ALICE, planned.id, turn.pending["pending_action_id"], "confirm")
    assert _estimates(coach, planned) == {"T1": 10, "T2": 20, "T3": 30}
    assert all(task.due_date is None for task in _tasks(coach, planned))


@pytest.mark.parametrize(
    "model_changes",
    [
        [{"op": "add", "fields": {"title": "Se reposer", "acceptance_criteria": "Fait"}}],
        [{"op": "update", "task_ref": "T1", "fields": {"estimate_minutes": 45}}],  # allongee
        [{"op": "delete", "task_ref": "T3"}],
    ],
)
def test_overload_never_adds_lengthens_or_deletes(coach, planned, model_changes):
    coach.llm.script("classify_intent", IntentResult(intent="replanifier"))
    coach.llm.script("draft_change", ChangeProposal(changes=model_changes))
    turn = _say(coach, planned, DELAY)
    assert turn.pending is not None
    assert "durée estimée : 10 minutes (au lieu de 20 minutes)" in turn.reply
    assert "Nouvelle tâche" not in turn.reply and "supprimée" not in turn.reply


def test_gpt_5_mini_lighter_proposal_is_kept_as_is(coach, planned):
    """Sortie de gpt-5-mini en R0 : T2 et T3 ramenees a 15 minutes."""
    coach.llm.script("classify_intent", IntentResult(intent="replanifier"))
    coach.llm.script(
        "draft_change",
        ChangeProposal(
            changes=[
                {"op": "update", "task_ref": "T2", "fields": {"estimate_minutes": 15}},
                {"op": "update", "task_ref": "T3", "fields": {"estimate_minutes": 15}},
            ],
            rationale="Des sessions courtes, compatibles avec vos 30 minutes.",
        ),
    )
    turn = _say(coach, planned, DELAY)
    assert "T2 modifiée — durée estimée : 15 minutes" in turn.reply
    assert "T3 modifiée — durée estimée : 15 minutes" in turn.reply
    assert "T1 modifiée" not in turn.reply


def test_overload_without_any_reducible_task_asks_a_simple_question(coach, planned):
    for ref in ("T1", "T2", "T3"):
        coach.llm.script("classify_intent", IntentResult(intent="changer_statut"))
        _say(coach, planned, f"J'ai terminé {ref}")
    coach.llm.script("classify_intent", IntentResult(intent="replanifier"))
    coach.llm.script(
        "draft_change", ChangeProposal(changes=[{"op": "update", "task_ref": "T1", "fields": {}}])
    )
    turn = _say(coach, planned, DELAY)
    assert turn.reply == REPLAN_QUESTION
    assert turn.pending is None


def test_lighter_step_rules():
    tasks = [
        {"ref": "T1", "status": "blocked", "estimate_minutes": 30},
        {"ref": "T2", "status": "todo", "estimate_minutes": 10},
        {"ref": "T3", "status": "todo", "estimate_minutes": None},
        {"ref": "T4", "status": "in_progress", "estimate_minutes": 25},
        {"ref": "T5", "status": "done", "estimate_minutes": 60},
    ]
    assert lighter_step(tasks, ["T1", "T2"]) == ("T4", 25)  # jamais de duree inventee
    assert lighter_step(tasks[:3], []) is None


def test_is_lightening_rules():
    tasks = [{"ref": "T1", "estimate_minutes": 20}, {"ref": "T2", "estimate_minutes": None}]
    shorter = ChangeProposal(
        changes=[{"op": "update", "task_ref": "T1", "fields": {"estimate_minutes": 10}}]
    )
    invented = ChangeProposal(
        changes=[{"op": "update", "task_ref": "T2", "fields": {"estimate_minutes": 10}}]
    )
    unknown = ChangeProposal(changes=[{"op": "update", "task_ref": "T9", "fields": {"title": "x"}}])
    assert is_lightening(shorter.changes, tasks)
    assert not is_lightening(invented.changes, tasks)
    assert not is_lightening(unknown.changes, tasks)


@pytest.mark.parametrize("text", ["Je suis fatiguée.", "Je suis à bout.", "Trop de tâches !"])
def test_fatigue_words_are_replan_requests(text):
    assert REPLAN_REQUEST.search(text.lower())


# --- 3. objectif provisoire : retire par D-78 (recette reelle du 11/11/2026 : le texte
#     code en dur reprenait le titre « Accompagnement création entreprise » et se
#     repetait). C'est desormais le modele qui conseille, voir test_agent_architecture.py.


def test_the_hard_coded_provisional_objective_no_longer_exists():
    from neurocoach.agent import guards

    assert not hasattr(guards, "provisional_outcome")
    assert not hasattr(guards, "PROVISIONAL_MESSAGE")
