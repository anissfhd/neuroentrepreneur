"""D-87 : ecarts restants de la campagne reelle V1 (13/11/2026), corriges hors ligne.

1. Une seule demande traitee par message : « Oui, je reprends. Mais maintenant je n'ai plus que
   2 heures par semaine. » reprenait le projet sans adapter le plan.
2. Aucune aide quand la personne est bloquee (« le syndic l'a retirée… personne ne m'a
   contacté ») ; la simulation 3 cherche la cause puis propose une amelioration.
3. Adaptation de plan appauvrie : consignes concretes remplacees par « par étapes », durees de
   120 a 150 min gardees pour 2 h par semaine.

Faux modele : ces tests verifient l'enchainement, les donnees transmises et les garanties du
code ; la qualite des textes du vrai modele n'est pas jugee ici.
"""

from __future__ import annotations

import socket
from types import SimpleNamespace

import pytest

from factories import ALICE
from neurocoach.agent.guards import keep_concrete_instructions, tasks_over
from neurocoach.agent.schemas import IntentResult
from neurocoach.domain.models import TaskStatus
from neurocoach.domain.proposals import ChangeProposal

VAGUE = "Je veux vendre des bougies artisanales, mais je ne sais pas par où commencer."
DETAILS = (
    "Tester si des personnes seraient intéressées. J'ai 30 minutes par jour. "
    "Mon budget est de 100 €. Proposez-moi un plan."
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("connexion reseau tentee")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def say(coach, project, text):
    return coach.agent.send_message(ALICE, project.id, text)


def decide(coach, project, turn, choice="confirm"):
    return coach.agent.decide(ALICE, project.id, turn.pending["pending_action_id"], choice)


def tasks_called(coach):
    return [t for t, _ in coach.llm.calls]


@pytest.fixture
def planned(coach):
    project = coach.app.coach.create_project(ALICE, "Bougies artisanales", VAGUE)
    say(coach, project, VAGUE)
    decide(coach, project, say(coach, project, DETAILS))
    return project


@pytest.fixture
def paused(coach, planned):
    decide(coach, planned, say(coach, planned, "Je suis fatiguée, j'aimerais faire une pause."))
    assert coach.app.coach.get_project(ALICE, planned.id).paused_at is not None
    return planned


# --- 1. seconde demande du meme message ----------------------------------------------------


def test_resuming_with_less_time_then_proposes_the_adapted_plan(coach, paused):
    coach.llm.script("classify_intent", IntentResult(
        intent="reprendre_projet", then_intent="replanifier",
    ))  # fmt: skip
    coach.llm.script("draft_change", ChangeProposal(
        changes=[{"op": "update", "task_ref": "T3", "fields": {"estimate_minutes": 20}}],
        rationale="Deux heures par semaine : une étape plus courte.",
    ))  # fmt: skip
    turn = say(coach, paused, "Oui, je reprends. Mais maintenant je n'ai plus que 2 heures par "
                              "semaine.")  # fmt: skip
    assert turn.pending["kind"] == "resume"
    assert "draft_change" not in tasks_called(coach)  # rien avant son clic
    after = decide(coach, paused, turn)
    assert coach.app.coach.get_project(ALICE, paused.id).paused_at is None
    # La seconde demande suit : une adaptation a valider, jamais appliquee d'office.
    assert after.pending is not None and after.pending["kind"] == "change"
    history = [m["content"] for m in coach.agent.history(ALICE, paused.id)]
    assert any(text.startswith("Le projet a repris.") for text in history[-3:])
    facts = [m for t, m in coach.llm.calls if t == "draft_change"][-1][-1]["content"]
    assert '"duree_max_par_tache": 25' in facts  # 2 h par semaine (dites en dernier), 5 jours
    assert '"instructions_actuelles"' in facts
    assert [t.estimate_minutes for t in coach.app.coach.list_tasks(ALICE, paused.id)][2] != 20


def test_refusing_to_resume_prepares_no_adaptation(coach, paused):
    coach.llm.script("classify_intent", IntentResult(
        intent="reprendre_projet", then_intent="replanifier",
    ))  # fmt: skip
    turn = say(coach, paused, "Je reprends, mais avec 2 heures par semaine.")
    after = decide(coach, paused, turn, "cancel")
    assert after.pending is None and "draft_change" not in tasks_called(coach)
    assert coach.app.coach.get_project(ALICE, paused.id).paused_at is not None


def test_a_done_task_and_a_difficulty_get_the_status_then_real_help(coach, planned):
    coach.llm.script("classify_intent", IntentResult(
        intent="changer_statut", target_status="done", task_ref="T1", then_intent="aide",
    ))  # fmt: skip
    turn = say(coach, planned, "J'ai terminé T1, mais personne ne m'a répondu, je bloque.")
    assert coach.app.coach.list_tasks(ALICE, planned.id)[0].status is TaskStatus.DONE
    history = [m["content"] for m in coach.agent.history(ALICE, planned.id)]
    assert history[-2] == "T1 est maintenant terminée. Vous pouvez annuler ce changement."
    assert turn.reply == history[-1] and turn.reply != history[-2]  # puis l'aide du coach
    system = [m for t, m in coach.llm.calls if t == "coach_reply"][-1][0]["content"]
    assert "cherche la cause avec UNE question précise" in system
    assert "pas de liste de pistes" in system


def test_a_grouped_card_then_help_after_the_click(coach, planned):
    coach.llm.script("classify_intent", IntentResult(
        intent="changer_statut", target_status="done", then_intent="aide",
    ))  # fmt: skip
    turn = say(coach, planned, "J'ai terminé T1 et T2, mais personne ne m'a contacté.")
    assert turn.pending["kind"] == "tasks_done" and "coach_reply" not in tasks_called(coach)
    decide(coach, planned, turn)
    history = [m["content"] for m in coach.agent.history(ALICE, planned.id)]
    assert history[-2].startswith("C'est enregistré : T1 et T2 terminées.")
    assert "coach_reply" in tasks_called(coach)  # aide apres la confirmation


def test_without_a_second_request_nothing_follows(coach, planned):
    coach.llm.script("classify_intent", IntentResult(intent="changer_statut", task_ref="T1",
                                                     target_status="done"))  # fmt: skip
    say(coach, planned, "J'ai terminé T1")
    assert "coach_reply" not in tasks_called(coach)


def test_a_new_message_drops_a_pending_second_request(coach, paused):
    coach.llm.script("classify_intent", IntentResult(
        intent="reprendre_projet", then_intent="replanifier",
    ))  # fmt: skip
    say(coach, paused, "Je reprends, mais avec 2 heures par semaine.")
    say(coach, paused, "Où en suis-je ?")  # la carte est abandonnee
    config, _ = coach.agent._session(ALICE, paused.id)
    assert coach.agent.graph.get_state(config).values.get("followup") is None


# --- 3. adaptation de plan concrete --------------------------------------------------------


def _snapshot(*tasks):
    return SimpleNamespace(tasks={t.ref: t for t in tasks}, ordered_tasks=lambda: list(tasks))


def _task(ref, description="", minutes=60, status="todo"):
    return SimpleNamespace(
        ref=ref, description=description, estimate_minutes=minutes,
        status=SimpleNamespace(value=status),
    )  # fmt: skip


TOOLS = (
    "Élaborez une liste courte (démonte-pneu, démonte-cassette, clé allen, clé à pédale, "
    "pompe, pied d'atelier simple, lubrifiants, rustines, chambres à air). Notez un coût estimé."
)


def test_concrete_instructions_are_never_replaced_by_a_generic_line():
    """Campagne reelle V1 : la liste d'outils de T5 remplacee par « par étapes »."""
    snapshot = _snapshot(_task("T5", TOOLS, 120))
    proposal = ChangeProposal(
        changes=[
            {
                "op": "update",
                "task_ref": "T5",
                "fields": {"description": "Lister l'outillage par étapes.", "estimate_minutes": 60},
            }
        ]
    )
    kept = keep_concrete_instructions(proposal, snapshot)
    assert kept.changes[0].fields.description is None  # consigne concrete gardee
    assert kept.changes[0].fields.estimate_minutes == 60  # duree adaptee gardee
    only_text = ChangeProposal(changes=[{"op": "update", "task_ref": "T5",
                                         "fields": {"description": "Par étapes."}}])  # fmt: skip
    assert keep_concrete_instructions(only_text, snapshot).changes == []


def test_a_richer_description_is_kept():
    snapshot = _snapshot(_task("T5", TOOLS, 120))
    richer = TOOLS + " Commencez par ce que vous possédez déjà."
    proposal = ChangeProposal(changes=[{"op": "update", "task_ref": "T5",
                                        "fields": {"description": richer}}])  # fmt: skip
    assert keep_concrete_instructions(proposal, snapshot).changes[0].fields.description == richer


def test_tasks_still_longer_than_a_session_are_named():
    snapshot = _snapshot(_task("T3", minutes=120), _task("T4", minutes=30),
                         _task("T1", minutes=150, status="done"))  # fmt: skip
    proposal = ChangeProposal(changes=[{"op": "update", "task_ref": "T3",
                                        "fields": {"estimate_minutes": 90}}])  # fmt: skip
    assert tasks_over(proposal, snapshot, 60) == ["T3 (90 min)"]
    assert tasks_over(proposal, snapshot, None) == []


def test_the_adaptation_instructions_ask_to_keep_details_and_fit_the_session():
    from neurocoach.agent.prompts import _TASKS

    prompt = _TASKS["draft_change"]
    assert "ne dépasse duree_max_par_tache" in prompt
    assert "ne les remplace jamais par une consigne générique" in prompt
    assert "then_intent" in _TASKS["classify_intent"]
