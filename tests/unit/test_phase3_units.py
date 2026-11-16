"""Phase 3 : correction d'un plan propose, gabarits de reprise, de phase et de dependances."""

from __future__ import annotations

from decimal import Decimal

import pytest

from factories import TODAY, make_phase, make_project, make_snapshot, make_task, sample_plan
from neurocoach.agent.routing import after_await
from neurocoach.application.formatting import (
    cadence_hint,
    describe_dependencies,
    format_phase_header,
    format_resume_message,
)
from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.models import TaskStatus
from neurocoach.domain.plans import (
    AddPhase,
    AddTask,
    Change,
    PlanEdits,
    TaskEdit,
    plan_create_command,
    revise_plan_command,
)
from neurocoach.domain.preview import describe_preview
from neurocoach.domain.priority import select_next_actions
from neurocoach.domain.progress import NBSP, PhaseProgress, summarize_progress


def _command():
    return plan_create_command(sample_plan(), today=TODAY, deadlines_enabled=False)


def _tasks(command):
    return [op for op in command.operations if isinstance(op, AddTask)]


def test_revision_changes_titles_and_criteria():
    edits = PlanEdits(
        phase_titles={"phase1": "Premiers retours"},
        tasks={"client": TaskEdit(title="Décrire ma cliente", acceptance_criteria="Une phrase")},
    )
    revised = revise_plan_command(_command(), edits)
    phase = next(op for op in revised.operations if isinstance(op, AddPhase))
    assert phase.title == "Premiers retours"
    first = _tasks(revised)[0]
    assert (first.title, first.acceptance_criteria) == ("Décrire ma cliente", "Une phrase")
    assert revised.brief == _command().brief


def test_removing_a_task_removes_its_dependencies():
    revised = revise_plan_command(_command(), PlanEdits(tasks={"questions": TaskEdit(remove=True)}))
    assert [task.key for task in _tasks(revised)] == ["client", "entretiens"]
    assert _tasks(revised)[1].depends_on == []


def test_emptied_phase_is_dropped_and_empty_plan_refused():
    command = plan_create_command(
        sample_plan(
            phases=[
                {
                    "title": "Phase A",
                    "tasks": [{"key": "a", "title": "Tâche A", "acceptance_criteria": "Fait"}],
                },
                {
                    "title": "Phase B",
                    "tasks": [{"key": "b", "title": "Tâche B", "acceptance_criteria": "Fait"}],
                },
            ]
        ),
        today=TODAY,
        deadlines_enabled=False,
    )
    revised = revise_plan_command(command, PlanEdits(tasks={"b": TaskEdit(remove=True)}))
    assert [op.title for op in revised.operations if isinstance(op, AddPhase)] == ["Phase A"]
    with pytest.raises(DomainError) as error:
        revise_plan_command(
            command, PlanEdits(tasks={"a": TaskEdit(remove=True), "b": TaskEdit(remove=True)})
        )
    assert error.value.code is ErrorCode.VALIDATION_ERROR


def test_unknown_keys_are_refused():
    with pytest.raises(DomainError) as error:
        revise_plan_command(_command(), PlanEdits(tasks={"inconnue": TaskEdit(title="Titre ok")}))
    assert error.value.code is ErrorCode.VALIDATION_ERROR


def test_after_await_loops_only_on_revision():
    assert after_await({"last_result": {"kind": "revised"}}) == "await_decision"
    assert after_await({"last_result": {"kind": "decision"}}) == "respond"


def test_project_preview_is_detailed_field_by_field():
    change = Change(
        op="update",
        entity="project",
        ref="projet",
        before={"target_outcome": None},
        after={"target_outcome": "Tester l'intérêt", "available_minutes_per_day": 30},
    )
    assert describe_preview([change]) == [
        "Objectif visé : « Tester l'intérêt »",
        "Temps disponible : 30 minutes par séance de travail",
    ]


def test_text_values_are_quoted_to_stay_unambiguous():
    """Verification visuelle : « titre : A → Version courte : A » etait ambigu (phase 3) ;
    phrases naturelles sans fleche (finition de phase 5)."""
    change = Change(
        op="update",
        entity="task",
        ref="T1",
        before={"title": "Décrire le client", "estimate_minutes": 20},
        after={"title": "Version courte : Décrire le client", "estimate_minutes": 15},
    )
    assert describe_preview([change]) == [
        "Tâche T1 modifiée — titre : « Version courte : Décrire le client » "
        "(au lieu de « Décrire le client ») ; durée estimée : 15 minutes (au lieu de 20 minutes)"
    ]


def test_resume_says_start_when_nothing_was_done():
    tasks = [make_task(1), make_task(2)]
    summary = summarize_progress([make_phase()], tasks, today=TODAY)
    next_actions = select_next_actions(
        [make_phase()],
        {task.id: task for task in tasks},
        set(),
        today=TODAY,
        max_visible=1,
        deadlines_enabled=False,
        available_minutes_per_day=None,
    )
    message = format_resume_message(make_project(), summary, next_actions)
    assert message.endswith("Voulez-vous la commencer ou la simplifier ?")


@pytest.mark.parametrize(
    ("cadence", "expected"),
    [
        ("flexible", None),
        (None, None),
        ("quotidienne", "Rythme choisi : un petit point chaque jour, même bref."),
        ("hebdomadaire", "Rythme choisi : un point par semaine, sans pression entre-temps."),
    ],
)
def test_cadence_hint(cadence, expected):
    assert cadence_hint(cadence) == expected


def test_resume_message_adds_the_chosen_rhythm():
    tasks = [make_task(1, TaskStatus.DONE), make_task(2)]
    summary = summarize_progress([make_phase()], tasks, today=TODAY)
    next_actions = select_next_actions(
        [make_phase()],
        {task.id: task for task in tasks},
        set(),
        today=TODAY,
        max_visible=1,
        deadlines_enabled=False,
        available_minutes_per_day=None,
    )
    message = format_resume_message(make_project(), summary, next_actions, "hebdomadaire")
    assert message.endswith("Rythme choisi : un point par semaine, sans pression entre-temps.")


def test_phase_header():
    phase = PhaseProgress(
        phase_id="p",
        title="Valider",
        position=0,
        total=3,
        done=1,
        percent=Decimal("33.3"),
        status="en_cours",
    )
    assert format_phase_header(phase) == "Valider — 1/3 (33,3" + NBSP + "%), en cours"
    empty = phase.model_copy(update={"total": 0, "done": 0, "percent": None, "status": "vide"})
    assert format_phase_header(empty) == "Valider — aucune tâche"


def test_describe_dependencies():
    t1, t2 = make_task(1, TaskStatus.DONE), make_task(2)
    t3 = make_task(3)
    snapshot = make_snapshot([t1, t2, t3], dependencies={(t3.id, t1.id), (t3.id, t2.id)})
    assert describe_dependencies(t1, snapshot) is None
    assert describe_dependencies(t3, snapshot) == (
        "Après T1 (terminée), T2 (à faire). En attente de T2."
    )
    done = make_task(3, TaskStatus.DONE)
    snapshot.tasks[done.id] = done
    assert describe_dependencies(done, snapshot) == "Après T1 (terminée), T2 (à faire)."
