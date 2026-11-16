"""D-79 : une seule decision par message, verifiee par le code avant toute preparation.

Faux modele : ces tests verifient les appels, le contexte transmis, les preconditions et les
protections. Ils ne prouvent pas la qualite reelle du coaching, qui se juge en recette
reelle avec ``gpt-5-mini``. Quand un test porte sur le traitement d'une decision du modele,
sa sortie est imposee (``coach_turn``) ; sinon, les regles simples du faux modele jouent.
"""

from __future__ import annotations

import json

import pytest

from neurocoach.agent.schemas import CoachBrief, CoachTurn
from neurocoach.research.fake import FakeResearchProvider

CANDLES = "Fabriquer et vendre des bougies artisanales parfumées à Lyon."
DETAILED = (
    "Je veux vendre des bougies artisanales parfumées sur les marchés de Lyon. J'ai 45 "
    "minutes par jour et 150 € de budget, je suis débutant."
)
# D-84 (6/6 simulations validees) : le plan est prepare quand elle le demande.
ASKED = DETAILED + " Proposez-moi un plan."


@pytest.fixture
def space(coach):
    user = coach.app.coach.register_user("Camille", "Martin", "camille.m")
    project = coach.app.coach.start_project(user.id)
    coach.agent.greet(user.id, project.id)
    return coach, user.id, project.id


def say(coach, user, project, text, **kwargs):
    return coach.agent.send_message(user, project, text, **kwargs)


def model(next_step="conseiller", *, reply="Réponse écrite par le modèle.", **values):
    """Sortie imposee du modele pour un tour (reponse, fiche, decision)."""
    flags = {k: values.pop(k) for k in ("plan_requested", "real_change", "research_declined")
             if k in values}  # fmt: skip
    values.setdefault("idea_summary", CANDLES)
    return CoachTurn(
        intent=values.pop("intent", "information_projet"),
        reply=reply,
        fiche=CoachBrief(**values),
        next_step=next_step,
        **flags,
    )


def tasks_called(llm) -> list[str]:
    return [task for task, _ in llm.calls]


def facts_of(llm, task: str, index: int = -1) -> dict:
    messages = [m for t, m in llm.calls if t == task][index]
    content = messages[-1]["content"]
    return json.loads(content.split("<donnees_projet>\n", 1)[1].split("\n</donnees_projet>")[0])


def manquant(llm, index: int = -1) -> list[str]:
    return facts_of(llm, "coach_turn", index)["preparation_du_plan"]["informations_manquantes"]


# --- 1 et 11 : pas de plan premature, aucun appel de planification inutile -----------------


def test_a_vague_project_gets_advice_and_no_premature_plan(space, fake_llm):
    coach, user, project = space
    turn = say(coach, user, project, "Je veux vendre des bougies artisanales.")
    assert turn.reply and turn.pending is None
    assert tasks_called(fake_llm) == ["coach_turn"]  # aucune preparation de plan
    # Le modele sait ce qui manque avant de repondre. D-81 : l'idee n'est connue qu'une fois
    # comprise par le modele (fin de ce tour), jamais devinee par le code.
    assert manquant(fake_llm) == ["votre idée", "votre disponibilité", "votre budget"]
    assert turn.timings["decision"]["applied"] == "conseiller"


def test_explaining_an_idea_never_triggers_a_planning_call(space, fake_llm):
    coach, user, project = space
    for text in (
        "Je veux vendre des bougies artisanales.",
        "Plutôt des bougies parfumées, avec des cires végétales.",
        "Je pense aux marchés de Noël et aux boutiques de créateurs.",
        "Est-ce que c'est une bonne idée selon vous ?",
    ):
        assert say(coach, user, project, text).pending is None
    assert "draft_plan" not in tasks_called(fake_llm)
    # Meme avec tout le contexte, le modele qui choisit de conseiller ne declenche rien.
    fake_llm.script("coach_turn", model(available_minutes_per_day=60, budget="200 €"))
    assert say(coach, user, project, "J'ai 1 h par jour et 200 €.").pending is None
    assert "draft_plan" not in tasks_called(fake_llm)


# --- 2 : contexte suffisant -> proposition au bon moment --------------------------------------


def test_a_detailed_project_gets_a_plan_offer_then_the_plan_on_yes(space, fake_llm):
    coach, user, project = space
    offer = say(coach, user, project, DETAILED)
    # D-84 : le coach propose le plan par une question ; rien n'est prepare sans sa demande.
    assert offer.pending is None and "plan" in offer.reply.split("\n")[-1].lower()
    assert tasks_called(fake_llm) == ["coach_turn"]
    turn = say(coach, user, project, "Oui")
    assert turn.pending is not None and turn.pending["kind"] == "plan"
    assert tasks_called(fake_llm) == ["coach_turn", "coach_turn", "draft_plan"]
    brief = facts_of(fake_llm, "draft_plan")["brief"]
    assert brief["budget"] == "150 €" and brief["available_minutes_per_day"] == 45
    assert coach.app.coach.list_tasks(user, project) == []  # rien n'est ecrit sans clic


# --- 3 : refus de donner une information -------------------------------------------------------


def test_refusing_the_budget_lets_the_plan_go_ahead_with_flagged_assumptions(space, fake_llm):
    coach, user, project = space
    first = say(
        coach, user, project, "Je veux vendre des bougies parfumées. J'ai 30 minutes par jour."
    )
    # La disponibilite dite dans ce message est relevee par le code avant l'appel.
    assert first.pending is None and manquant(fake_llm) == ["votre idée", "votre budget"]
    second = say(coach, user, project, "Je préfère ne pas donner de budget pour l'instant.")
    assert manquant(fake_llm) == ["votre budget"]  # disponibilite connue : jamais redemandee
    assert second.pending is None  # D-84 : propose par une question
    third = say(coach, user, project, "Oui, proposez-moi un plan.")
    assert third.pending is not None and third.pending["kind"] == "plan"
    plan_facts = facts_of(fake_llm, "draft_plan")
    assert plan_facts["informations_non_fournies"] == ["le budget"]
    system = [m for t, m in fake_llm.calls if t == "draft_plan"][-1][0]["content"]
    assert "hypothèse prudente" in system and "assumptions" in system


# --- 4 : plan provisoire demande tout de suite --------------------------------------------------


def test_an_explicit_provisional_plan_is_proposed_without_a_questionnaire(space, fake_llm):
    coach, user, project = space
    turn = say(coach, user, project, "Faites-moi tout de suite un plan provisoire pour vendre "
               "des bougies artisanales.")  # fmt: skip
    assert turn.pending is not None and turn.pending["kind"] == "plan"
    assert tasks_called(fake_llm) == ["coach_turn", "draft_plan"]
    # Ce qui manque devient des hypotheses signalees dans le plan, sans questionnaire.
    assert facts_of(fake_llm, "draft_plan")["informations_manquantes"] == [
        "votre disponibilité", "votre budget",
    ]  # fmt: skip
    assert turn.timings["decision"]["missing"] == ["temps_disponible", "budget"]


# --- 5 : informations donnees sur plusieurs tours ----------------------------------------------


def test_information_given_progressively_is_kept_and_never_asked_again(space, fake_llm):
    coach, user, project = space
    fake_llm.script("coach_turn", model())
    say(coach, user, project, "Je veux vendre des bougies artisanales parfumées à Lyon.")
    assert manquant(fake_llm) == ["votre idée", "votre disponibilité", "votre budget"]
    fake_llm.script("coach_turn", model(available_minutes_per_day=60))
    assert say(coach, user, project, "Je peux y consacrer un peu de temps le soir.").pending is None
    fake_llm.script("coach_turn", model("preparer_plan", budget="200 €", plan_requested=True))
    third = say(coach, user, project, "Mon budget de départ est de 200 €, proposez un plan.")
    # La disponibilite (fiche du tour 2) n'est plus a demander ; le budget de ce message est
    # releve par le code avant l'appel.
    assert manquant(fake_llm) == []
    assert third.pending is not None
    brief = facts_of(fake_llm, "draft_plan")["brief"]
    assert brief["available_minutes_per_day"] == 60 and brief["budget"] == "200 €"


# --- 6 et 7 : modification reelle contre reformulation -------------------------------------------


def test_a_real_change_adapts_the_pending_proposal(space, fake_llm):
    coach, user, project = space
    known = {"available_minutes_per_day": 45, "budget": "150 €"}
    fake_llm.script("coach_turn", model("preparer_plan", plan_requested=True, **known))
    first = say(coach, user, project, ASKED)
    first_id = first.pending["pending_action_id"]
    online = "Vendre des bougies artisanales parfumées en ligne plutôt que sur les marchés."
    fake_llm.script(
        "coach_turn", model("preparer_plan", idea_summary=online, real_change=True, **known)
    )
    second = say(coach, user, project, "Finalement je préfère vendre en ligne.")
    assert coach.app.actions.get_action(user, first_id).status.value == "cancelled"
    assert second.pending is not None and second.pending["pending_action_id"] != first_id
    previous = facts_of(fake_llm, "draft_plan")["proposition_precedente"]
    assert previous["phases"] and previous["phases"][0]["tasks"]  # base de l'adaptation
    assert coach.app.coach.list_tasks(user, project) == []


def test_a_reformulation_does_not_trigger_a_new_plan(space, fake_llm):
    coach, user, project = space
    known = {"available_minutes_per_day": 45, "budget": "150 €"}
    fake_llm.script("coach_turn", model("preparer_plan", plan_requested=True, **known))
    first = say(coach, user, project, ASKED)
    coach.agent.decide(user, project, first.pending["pending_action_id"], "cancel")
    plans = tasks_called(fake_llm).count("draft_plan")
    reworded = "Créer et vendre des bougies parfumées faites main, à Lyon."
    fake_llm.script("coach_turn", model("preparer_plan", idea_summary=reworded, **known))
    turn = say(coach, user, project, "En résumé, ce sont des bougies faites main.")
    assert turn.pending is None and tasks_called(fake_llm).count("draft_plan") == plans
    assert turn.notice.startswith("Aucune proposition de plan n'a été préparée : je la")


# --- 8 et 9 : recherche refusee, recherche approuvee ---------------------------------------------


def test_a_refused_research_is_remembered_and_never_launched(space, fake_llm):
    coach, user, project = space
    fake_llm.script("coach_turn", model(reply="Voulez-vous que je vérifie les concurrents ?"))
    say(coach, user, project, "Je veux vendre des bougies artisanales parfumées à Lyon.")
    fake_llm.script("coach_turn", model(research_declined=True))
    say(coach, user, project, "Non, je préfère avancer sans ça.")
    assert coach.agent.research_pending(user, project) is None
    assert coach.app.research.list_missions(user, project) == []
    say(coach, user, project, "Et pour les prix, que me conseillez-vous ?")
    assert facts_of(fake_llm, "coach_turn")["brief"]["research_declined"] is True
    # Le modele qui choisirait malgre tout une recherche refusee n'obtient rien.
    fake_llm.script("coach_turn", model("preparer_recherche", research_declined=True))
    say(coach, user, project, "D'accord.")
    assert coach.app.research.list_missions(user, project) == []


def test_an_accepted_research_is_proposed_then_runs_only_after_approval(space, fake_llm):
    coach, user, project = space
    provider = FakeResearchProvider()
    from neurocoach.infra.search_providers import build_research_registry

    coach.app.research.registry = build_research_registry(simulation=True, extra={"fake": provider})
    fake_llm.script("coach_turn", model("preparer_recherche"))
    say(coach, user, project, "Oui, allez-y, vérifiez ça pour Lyon.")
    mission = coach.agent.research_pending(user, project)
    assert mission is not None and provider.calls == []  # aucun appel externe sans clic
    coach.agent.approve_research(user, project, mission.id, mission.scope_hash)
    assert provider.calls  # lancee apres l'approbation explicite
    assert coach.app.coach.list_tasks(user, project) == []
    assert coach.app.actions.get_pending(user, project) is None  # ni plan ni tache automatiques


# --- 10 : confirmation avant enregistrement ----------------------------------------------------


def test_the_plan_is_saved_only_after_the_confirm_button(space, fake_llm):
    coach, user, project = space
    turn = say(coach, user, project, ASKED)
    action_id = turn.pending["pending_action_id"]
    assert say(coach, user, project, "Oui").notice  # un « oui » ecrit ne confirme pas
    assert coach.app.coach.list_tasks(user, project) == []
    coach.agent.decide(user, project, action_id, "confirm")
    assert len(coach.app.coach.list_tasks(user, project)) == 3
    assert coach.app.coach.get_project(user, project).status.value == "active"


# --- 12 : aucune contradiction entre la reponse et les actions du code ---------------------------


def test_a_plan_decision_without_its_preconditions_is_refused_and_said(space, fake_llm):
    coach, user, project = space
    fake_llm.script(
        "coach_turn",
        model("preparer_plan", reply="Je vous prépare un plan.", available_minutes_per_day=30),
    )
    turn = say(coach, user, project, "Je veux vendre des bougies. J'ai 30 minutes par jour.")
    assert "draft_plan" not in tasks_called(fake_llm) and turn.pending is None
    # La decision refusee n'est pas cachee : l'utilisateur sait pourquoi rien ne s'affiche.
    # D-84 : un plan qu'elle n'a pas demande n'est jamais prepare.
    assert turn.notice == (
        "Aucune proposition de plan n'a été préparée : je la prépare dès que vous me la demandez."
    )
    decision = turn.timings["decision"]
    assert (decision["chosen"], decision["applied"], decision["missing"]) == (
        "preparer_plan", "conseiller", ["budget"],
    ) and decision["notice"] == turn.notice  # fmt: skip
    # La regle est donnee au modele avant sa decision (meme appel que sa reponse).
    system = [m for t, m in fake_llm.calls if t == "coach_turn"][-1][0]["content"]
    assert "preparation_du_plan.informations_manquantes" in system
    assert "termine reply par une phrase qui annonce" in system


def test_an_accepted_decision_matches_what_the_coach_said(space, fake_llm):
    coach, user, project = space
    reply = "Merci, c'est clair. La proposition de plan s'affiche juste après."
    fake_llm.script("coach_turn", model("preparer_plan", reply=reply, plan_requested=True,
                                        available_minutes_per_day=45, budget="150 €"))  # fmt: skip
    turn = say(coach, user, project, ASKED)
    history = coach.agent.history(user, project)
    assert reply in [m["content"] for m in history]
    assert turn.pending is not None and turn.notice is None


# --- 13 : diffusion sans classification bloquante -----------------------------------------------


def test_the_reply_is_fully_shown_before_any_long_preparation(space, fake_llm):
    coach, user, project = space
    seen: list[str] = []
    shown_at_plan: list[int] = []
    original = fake_llm.generate_structured

    def spy(task, messages, schema):
        if task == "draft_plan":
            shown_at_plan.append(len(seen))
        return original(task, messages, schema)

    fake_llm.generate_structured = spy
    turn = say(coach, user, project, ASKED, stream=seen.append)
    assert "classify_intent" not in tasks_called(fake_llm)
    assert seen and seen[-1] == [m for m in coach.agent.history(user, project)
                                 if m["role"] == "assistant"][-2]["content"]  # fmt: skip
    assert shown_at_plan == [len(seen)]  # la reponse etait complete avant le plan
    timings = turn.timings
    assert timings["first_visible"] <= timings["reply_complete"] <= timings["total"]
    assert [c["task"] for c in timings["calls"]] == ["coach_turn", "draft_plan"]


# --- 14 : memoire apres redemarrage ------------------------------------------------------------


def test_the_project_memory_survives_a_restart(settings, clock, fake_llm):
    from neurocoach.bootstrap import build_coach_runtime

    first = build_coach_runtime(settings, clock=clock, llm=fake_llm)
    user = first.app.coach.register_user("Camille", "Martin", "camille.m").id
    project = first.app.coach.start_project(user).id
    fake_llm.script("coach_turn", model(available_minutes_per_day=45, budget="150 €"))
    first.agent.send_message(user, project, DETAILED)
    first.checkpointer.conn.close()
    again = build_coach_runtime(settings, clock=clock, llm=fake_llm)
    try:
        # Le modele ne repete rien : la fiche enregistree suffit aux preconditions.
        fake_llm.script(
            "coach_turn", model("preparer_plan", idea_summary=None, plan_requested=True)
        )
        turn = again.agent.send_message(user, project, "On peut construire le plan ?")
        facts = facts_of(fake_llm, "coach_turn")
        assert facts["brief"]["budget"] == "150 €"
        assert facts["brief"]["available_minutes_per_day"] == 45
        assert facts["preparation_du_plan"]["informations_manquantes"] == []
        assert turn.pending is not None
    finally:
        again.checkpointer.conn.close()
