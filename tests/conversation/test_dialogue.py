"""Parcours conversationnels avec le faux LLM : T01, T02, T03, T04, T05, T06, T07, T08."""

from __future__ import annotations

import re
from datetime import timedelta

import pytest

from factories import ALICE
from neurocoach.application.formatting import format_resume_message
from neurocoach.bootstrap import build_coach_runtime
from neurocoach.domain.errors import DomainError
from neurocoach.domain.models import ActionStatus, EventType, TaskStatus

VAGUE = "Je veux vendre des bougies artisanales, mais je ne sais pas par où commencer."
DETAILS = (
    "Tester si des personnes seraient intéressées. J'ai 30 minutes par jour. "
    "Mon budget est de 100 €. Proposez-moi un plan."
)
GUILT_WORDS = re.compile(
    r"retard inacceptable|aurais dû|paresse|échec|faute|dommage|encore une fois"
)


@pytest.fixture
def draft(coach):
    project = coach.app.coach.create_project(ALICE, "Bougies artisanales", VAGUE)
    return project


def _say(coach, project, text):
    return coach.agent.send_message(ALICE, project.id, text)


def _tasks(coach, project):
    return coach.app.coach.list_tasks(ALICE, project.id)


def _planned(coach, project):
    _say(coach, project, VAGUE)
    turn = _say(coach, project, DETAILS)
    coach.agent.decide(ALICE, project.id, turn.pending["pending_action_id"], "confirm")
    return _tasks(coach, project)


def test_vague_idea_gets_a_model_reply_and_no_proposal(coach, draft, fake_llm):
    """T01, puis D-78 : la reponse vient du modele (coach_reply) ; la fiche est mise a jour
    par l'extraction (clarify) ; rien n'est propose ni ecrit."""
    fake_llm.calls.clear()
    turn = _say(coach, draft, VAGUE)
    # D-79 : un seul appel ; aucune preparation de plan pour une idee vague.
    assert [t for t, _ in fake_llm.calls] == ["coach_turn"]
    assert turn.reply.startswith("[Réponse simulée]")  # texte du (faux) modele, jamais du code
    assert turn.pending is None
    assert _tasks(coach, draft) == []


def test_idea_with_constraints_gets_a_plan_proposal_without_writing(coach, draft):
    """T02 : micro-taches avec criteres de fin ; rien n'est ecrit avant confirmation."""
    _say(coach, draft, VAGUE)
    turn = _say(coach, draft, DETAILS)
    assert turn.pending is not None
    assert turn.reply.startswith("Voici la proposition de plan")
    # D-82 : le plan est detaille etape par etape (taches, duree, critere de fin) ; les
    # creations restent dans l'apercu de la carte ; boutons Accepter / Demander un changement.
    assert "**Étape 1 : Valider l'intérêt**" in turn.reply
    assert "« Décrire le client visé »" in turn.reply
    assert any(
        "Nouvelle tâche T1 : « Décrire le client visé »" in line for line in turn.pending["preview"]
    )
    assert "« Accepter et ajouter ce plan à mes tâches »" in turn.reply
    assert _tasks(coach, draft) == []
    action = coach.app.actions.get_action(ALICE, turn.pending["pending_action_id"])
    assert action.status is ActionStatus.PENDING
    task_changes = [c for c in action.preview if c["entity"] == "task"]
    assert all(change["after"]["acceptance_criteria"] for change in task_changes)


def test_reference_dialogue_end_to_end(coach, draft):
    """T04 et dialogue de reference (docs/04)."""
    _say(coach, draft, VAGUE)
    turn = _say(coach, draft, DETAILS)
    done = coach.agent.decide(ALICE, draft.id, turn.pending["pending_action_id"], "confirm")
    assert done.reply.startswith(
        "Le plan est enregistré. Première action : T1 « Décrire le client visé »."
    )
    tasks = _tasks(coach, draft)
    assert [task.ref for task in tasks] == ["T1", "T2", "T3"]
    project = coach.app.coach.get_project(ALICE, draft.id)
    assert project.target_outcome == "Tester si des personnes seraient intéressées"
    assert project.available_minutes_per_day == 30
    assert coach.agent.pending_confirmation(ALICE, draft.id) is None


def test_refusing_the_plan_writes_nothing(coach, draft):
    """T03."""
    _say(coach, draft, VAGUE)
    turn = _say(coach, draft, DETAILS)
    result = coach.agent.decide(ALICE, draft.id, turn.pending["pending_action_id"], "cancel")
    assert result.reply == "D'accord, rien n'a été modifié."
    assert _tasks(coach, draft) == []


def test_double_confirmation_does_not_duplicate(coach, draft, fake_llm):
    """T05 de bout en bout : le second clic ne relance pas le graphe."""
    _say(coach, draft, VAGUE)
    turn = _say(coach, draft, DETAILS)
    action_id = turn.pending["pending_action_id"]
    coach.agent.decide(ALICE, draft.id, action_id, "confirm")
    calls = len(fake_llm.calls)
    second = coach.agent.decide(ALICE, draft.id, action_id, "confirm")
    assert second.reply is None
    assert second.notice == "Cette proposition a déjà été traitée."
    assert len(fake_llm.calls) == calls
    assert len(_tasks(coach, draft)) == 3


def test_expired_proposal(coach, draft, clock):
    _say(coach, draft, VAGUE)
    turn = _say(coach, draft, DETAILS)
    clock.advance(timedelta(minutes=16))
    result = coach.agent.decide(ALICE, draft.id, turn.pending["pending_action_id"], "confirm")
    assert result.notice.startswith("Cette proposition a expiré")
    assert result.reply.startswith("Cette proposition a expiré")
    assert _tasks(coach, draft) == []


def _proposal(coach, draft) -> str:
    _say(coach, draft, VAGUE)
    return _say(coach, draft, DETAILS).pending["pending_action_id"]


def test_new_message_while_pending_cancels_the_proposal(coach, draft):
    """S-02 / D-32 : la proposition est annulee, jamais confirmee, puis le message est traite."""
    action_id = _proposal(coach, draft)
    follow = _say(coach, draft, "En fait, je préfère d'abord trouver un fournisseur.")
    assert coach.app.actions.get_action(ALICE, action_id).status is ActionStatus.CANCELLED
    assert _tasks(coach, draft) == []
    assert follow.reply
    history = [m["content"] for m in coach.agent.history(ALICE, draft.id)]
    assert any("La proposition précédente n'a pas été enregistrée" in m for m in history)


@pytest.mark.parametrize("answer", ["Oui", "oui !", "Je confirme.", "OK", "d'accord"])
def test_written_yes_neither_confirms_nor_cancels(coach, draft, fake_llm, answer):
    """D-40 : « Oui » rappelle le bouton ; la proposition reste en attente (R-SEC-04)."""
    action_id = _proposal(coach, draft)
    calls = len(fake_llm.calls)
    turn = _say(coach, draft, answer)
    assert turn.notice.startswith("Pour enregistrer cette proposition")
    assert turn.pending["pending_action_id"] == action_id
    assert coach.app.actions.get_action(ALICE, action_id).status is ActionStatus.PENDING
    assert len(fake_llm.calls) == calls
    assert _tasks(coach, draft) == []


@pytest.mark.parametrize("answer", ["Non", "non merci", "Annule."])
def test_written_no_cancels(coach, draft, answer):
    action_id = _proposal(coach, draft)
    turn = _say(coach, draft, answer)
    assert turn.reply == "D'accord, rien n'a été modifié."
    assert coach.app.actions.get_action(ALICE, action_id).status is ActionStatus.CANCELLED


def test_yes_with_more_words_is_a_new_message(coach, draft):
    """Seule une reponse courte et non ambigue est reconnue ; le reste suit D-32."""
    action_id = _proposal(coach, draft)
    _say(coach, draft, "Oui mais ajoute une tâche sur le prix")
    assert coach.app.actions.get_action(ALICE, action_id).status is ActionStatus.CANCELLED


def test_plan_revision_through_the_agent(coach, draft):
    from neurocoach.domain.plans import PlanEdits

    action_id = _proposal(coach, draft)
    edits = PlanEdits(
        phase_titles={"phase1": "Premiers retours"},
        tasks={"client": {"title": "Décrire ma cliente idéale"}, "entretiens": {"remove": True}},
    )
    revised = coach.agent.revise_plan(ALICE, draft.id, action_id, edits)
    assert revised.reply.startswith("Proposition mise à jour :")
    assert "Nouvelle phase « Premiers retours »" in revised.reply
    assert coach.app.actions.get_action(ALICE, action_id).status is ActionStatus.SUPERSEDED
    assert _tasks(coach, draft) == []
    new_id = revised.pending["pending_action_id"]
    with pytest.raises(DomainError):
        coach.agent.revise_plan(ALICE, draft.id, action_id, edits)  # ancienne proposition
    done = coach.agent.decide(ALICE, draft.id, new_id, "confirm")
    assert done.reply.startswith(
        "Le plan est enregistré. Première action : T1 « Décrire ma cliente idéale »."
    )
    assert [task.title for task in _tasks(coach, draft)] == [
        "Décrire ma cliente idéale",
        "Préparer cinq questions",
    ]


def test_a_skipped_detail_does_not_block_the_plan(coach, draft):
    """« Je passe » : le modele n'insiste pas ; le plan reste possible (D-78)."""
    _say(coach, draft, VAGUE)
    _say(coach, draft, "Je passe")
    _say(coach, draft, "Je passe")
    # D-84 : le plan reste possible des qu'elle le demande, sans redemander ce qu'elle passe.
    final = _say(coach, draft, "Proposez-moi un plan quand même.")
    assert final.pending is not None


def test_status_change_through_chat_and_undo(coach, draft):
    _planned(coach, draft)
    turn = _say(coach, draft, "J'ai terminé T1")
    assert turn.reply == "T1 est maintenant terminée. Vous pouvez annuler ce changement."
    assert turn.undo_event_id is not None
    assert _tasks(coach, draft)[0].status is TaskStatus.DONE
    coach.app.coach.undo_status_change(ALICE, turn.undo_event_id)
    assert _tasks(coach, draft)[0].status is TaskStatus.TODO


def test_ambiguous_or_unknown_task_reference_asks_a_question(coach, draft):
    _planned(coach, draft)
    unknown = _say(coach, draft, "J'ai terminé T9")
    assert unknown.reply.startswith("Je ne trouve pas la tâche T9.")
    implicit = _say(coach, draft, "J'ai terminé")
    assert implicit.reply == "Quelle tâche avez-vous terminée ?"
    assert all(task.status is TaskStatus.TODO for task in _tasks(coach, draft))


def test_no_guess_even_when_a_single_task_is_in_progress(coach, draft):
    """D-57 (remplace la reference implicite a la seule tache en cours) : jamais deviner."""
    tasks = _planned(coach, draft)
    coach.app.coach.set_task_status(ALICE, tasks[0].id, TaskStatus.IN_PROGRESS)
    turn = _say(coach, draft, "J'ai terminé")
    assert turn.reply == "Quelle tâche avez-vous terminée ?"
    assert _tasks(coach, draft)[0].status is TaskStatus.IN_PROGRESS


def test_blocking_through_chat_records_the_reason(coach, draft):
    _planned(coach, draft)
    _say(coach, draft, "T2 est bloquée car j'attends un devis")
    task = _tasks(coach, draft)[1]
    assert task.status is TaskStatus.BLOCKED
    assert task.blocked_reason == "car j'attends un devis"


def test_progress_answer_comes_from_the_database(coach, draft):
    """T07 via la conversation : 33,3 % calcule hors LLM."""
    tasks = _planned(coach, draft)
    coach.app.coach.set_task_status(ALICE, tasks[0].id, TaskStatus.DONE)
    turn = _say(coach, draft, "Où en suis-je ?")
    assert turn.reply.startswith("1 tâche terminée sur 3 (33,3")
    assert "Prochaine action : T2 « Préparer cinq questions »." in turn.reply


def test_replanning_is_proposed_without_writing_and_without_guilt(coach, draft):
    """T08 : proposition plus petite, en attente ; aucune ecriture avant accord."""
    tasks = _planned(coach, draft)
    turn = _say(coach, draft, "Je n'ai pas avancé cette semaine")
    assert turn.pending is not None
    assert "Version courte : Décrire le client visé" in turn.reply
    assert not GUILT_WORDS.search(turn.reply.lower())
    assert _tasks(coach, draft) == tasks
    coach.agent.decide(ALICE, draft.id, turn.pending["pending_action_id"], "confirm")
    assert _tasks(coach, draft)[0].title == "Version courte : Décrire le client visé"


def test_task_deletion_and_rename_need_confirmation(coach, draft):
    _planned(coach, draft)
    rename = _say(coach, draft, "Renomme T2 en « Rédiger cinq questions ouvertes »")
    assert rename.pending is not None
    coach.agent.decide(ALICE, draft.id, rename.pending["pending_action_id"], "confirm")
    assert _tasks(coach, draft)[1].title == "Rédiger cinq questions ouvertes"
    delete = _say(coach, draft, "Supprime T3")
    assert "Tâche T3 « Interroger trois personnes » retirée du plan" in delete.reply
    assert len(_tasks(coach, draft)) == 3
    result = coach.agent.decide(ALICE, draft.id, delete.pending["pending_action_id"], "confirm")
    assert result.reply.startswith("C'est enregistré.")
    assert [task.ref for task in _tasks(coach, draft)] == ["T1", "T2"]


def test_routing_depends_on_project_status(coach, draft, fake_llm):
    """Sans plan, une demande de modification va au coach (le modele) ; avec un plan, une
    demande de nouveau plan recoit une reponse du modele, sans second plan."""
    fake_llm.calls.clear()
    reply = _say(coach, draft, "Supprime T1").reply
    assert [t for t, _ in fake_llm.calls] == ["coach_turn"] and reply
    _planned(coach, draft)
    fake_llm.calls.clear()
    turn = _say(coach, draft, "Fais-moi un plan")
    assert "coach_reply" in [t for t, _ in fake_llm.calls]
    assert turn.pending is None and len(_tasks(coach, draft)) == 3


def test_preferences_are_never_changed_by_the_conversation(coach, draft):
    """PF-01."""
    before = coach.app.coach.get_preferences(ALICE)
    turn = _say(coach, draft, "Passe en réponses courtes s'il te plaît")
    assert "rien n'a changé" in turn.reply and "panneau « Préférences »" in turn.reply
    assert coach.app.coach.get_preferences(ALICE) == before
    events = coach.app.coach.list_events(ALICE)
    assert not [event for event in events if event.type is EventType.PREFERENCES_UPDATED]


def test_out_of_scope_requests_are_redirected(coach, draft, fake_llm):
    turn = _say(coach, draft, "Mon médecin dit que je suis stressé, quel médicament prendre ?")
    assert "professionnel qualifié" in turn.reply
    # D-79 : l'intention en tete de la sortie du coach suffit ; generation interrompue.
    assert [task for task, _ in fake_llm.calls] == ["coach_turn"]


def test_short_responses_preference_limits_llm_text(coach, draft, fake_llm):
    _planned(coach, draft)
    coach.app.coach.update_preferences(ALICE, response_length="court")
    fake_llm.script("coach_reply", "Une. Deux. Trois. Quatre.")
    turn = _say(coach, draft, "Merci pour tout ce travail")
    assert turn.reply == "Une. Deux."


def test_resume_after_restart(coach, draft, settings, clock, fake_llm):
    """T06 : apres redemarrage, historique, proposition en attente et base sont identiques."""
    tasks = _planned(coach, draft)
    coach.app.coach.set_task_status(ALICE, tasks[0].id, TaskStatus.DONE)
    pending = _say(coach, draft, "Supprime T3")
    history = coach.agent.history(ALICE, draft.id)
    coach.checkpointer.conn.close()

    reopened = build_coach_runtime(settings, clock=clock, llm=fake_llm)
    try:
        assert reopened.agent.history(ALICE, draft.id) == history
        waiting = reopened.agent.pending_confirmation(ALICE, draft.id)
        assert waiting["pending_action_id"] == pending.pending["pending_action_id"]
        summary = reopened.app.coach.get_progress(ALICE, draft.id)
        next_actions = reopened.app.coach.get_next_actions(ALICE, draft.id)
        project = reopened.app.coach.get_project(ALICE, draft.id)
        assert format_resume_message(project, summary, next_actions) == (
            "Vous avez terminé 1 tâche sur 3. Prochaine action : T2 « Préparer cinq questions ». "
            "Voulez-vous la reprendre ou la simplifier ?"
        )
        result = reopened.agent.decide(ALICE, draft.id, waiting["pending_action_id"], "cancel")
        assert result.reply == "D'accord, rien n'a été modifié."
    finally:
        reopened.checkpointer.conn.close()


def test_export_and_deletion_include_the_conversation(coach, draft):
    _say(coach, draft, VAGUE)
    export = coach.app.data.export_user_data(ALICE)
    messages = export["conversations"][0]["messages"]
    assert messages[0] == {"role": "user", "content": VAGUE}
    assert messages[1]["role"] == "assistant"
    action = coach.app.actions.request_user_data_deletion(ALICE)
    coach.app.actions.confirm(ALICE, action.id)
    thread_id = export["conversations"][0]["thread_id"]
    state = coach.graph.get_state({"configurable": {"thread_id": thread_id}})
    assert state.values == {}
