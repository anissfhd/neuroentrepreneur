"""Gabarits deterministes en francais (D-15) : chiffres issus du domaine uniquement."""

from __future__ import annotations

from factories import TODAY, make_phase, make_project, make_task
from neurocoach.application.formatting import (
    OUT_OF_SCOPE_MESSAGE,
    format_error,
    format_next_actions,
    format_progress,
    format_resume_message,
    format_status_change,
)
from neurocoach.application.services import StatusChange
from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.models import TaskStatus
from neurocoach.domain.priority import select_next_actions
from neurocoach.domain.progress import NBSP, summarize_progress

S = TaskStatus


def _state(tasks, edges=(), **kwargs):
    phases = [make_phase()]
    by_id = {task.id: task for task in tasks}
    summary = summarize_progress(phases, tasks, today=TODAY)
    next_actions = select_next_actions(
        phases,
        by_id,
        set(edges),
        today=TODAY,
        max_visible=kwargs.get("max_visible", 3),
        deadlines_enabled=False,
        available_minutes_per_day=kwargs.get("minutes"),
    )
    return summary, next_actions


def test_reference_resume_message():
    """Dialogue de reference (docs/04) : 1 tache sur 3, reprise de la deuxieme."""
    t1, t2, t3 = make_task(1, S.DONE), make_task(2, title="Préparer cinq questions"), make_task(3)
    summary, next_actions = _state([t1, t2, t3], edges={(t3.id, t2.id), (t2.id, t1.id)})
    message = format_resume_message(make_project(title="Bougies"), summary, next_actions)
    assert message == (
        "Vous avez terminé 1 tâche sur 3. Prochaine action : T2 « Préparer cinq questions ». "
        "Voulez-vous la reprendre ou la simplifier ?"
    )


def test_resume_without_plan():
    summary, next_actions = _state([])
    message = format_resume_message(make_project(title="Bougies"), summary, next_actions)
    assert "n'a pas encore de plan" in message


def test_resume_while_a_plan_awaits_confirmation():
    """Finition phase 5 : le resume ne dit plus « pas encore de plan » sous un plan propose."""
    summary, next_actions = _state([])
    message = format_resume_message(
        make_project(title="Bougies"), summary, next_actions, plan_pending=True
    )
    assert message == (
        "« Bougies » n'a pas encore de plan enregistré. Une proposition vous attend : "
        "rien ne sera enregistré avant votre confirmation."
    )


def test_resume_with_fallback_and_finished_plan():
    summary, next_actions = _state([make_task(1, S.BLOCKED)])
    assert "lever ce blocage" in format_resume_message(make_project(), summary, next_actions)
    summary, next_actions = _state([make_task(1, S.DONE), make_task(2, S.DONE)])
    message = format_resume_message(make_project(), summary, next_actions)
    assert message.startswith("Vous avez terminé 2 tâches sur 2.")
    assert "Toutes les tâches" in message


def test_progress_sentence():
    summary, _ = _state([make_task(1, S.DONE), make_task(2, S.BLOCKED), make_task(3)])
    assert format_progress(summary) == "1 tâche terminée sur 3 (33,3" + NBSP + "%). 1 bloquée."
    summary, _ = _state([])
    assert format_progress(summary) == "Pas encore de plan."


def test_next_actions_sentences():
    _, single = _state([make_task(1)])
    assert format_next_actions(single) == "Prochaine action : T1 « Tâche 1 »."
    _, several = _state([make_task(1), make_task(2)])
    assert format_next_actions(several).startswith("Prochaines actions possibles :\n- T1")
    _, split = _state([make_task(1, estimate_minutes=240)], minutes=30)
    assert "découper" in format_next_actions(split)
    _, empty = _state([])
    assert "Pas encore de plan" in format_next_actions(empty)
    _, nothing = _state([make_task(1)], edges={(make_task(1).id, "tsk_absente")})
    assert format_next_actions(nothing) == (
        "Aucune tâche n'est réalisable pour l'instant : les tâches restantes attendent que "
        "d'autres soient terminées."
    )


def test_status_change_sentences():
    task = make_task(2, S.DONE)
    assert format_status_change(StatusChange(task, None)) == "T2 est déjà terminée."
    one = StatusChange(task, "evt_x", ["UNMET_DEPENDENCIES"], ["T1"])
    assert format_status_change(one) == (
        "T2 est maintenant terminée. À noter : T1 n'est pas encore terminée. "
        "Vous pouvez annuler ce changement."
    )
    two = StatusChange(task, "evt_x", ["UNMET_DEPENDENCIES"], ["T1", "T3"])
    assert "T1, T3 ne sont pas encore terminées" in format_status_change(two)


def test_error_and_out_of_scope_messages():
    assert format_error(DomainError(ErrorCode.ACTION_EXPIRED)).startswith(
        "Cette proposition a expiré"
    )
    assert "professionnel" in OUT_OF_SCOPE_MESSAGE
