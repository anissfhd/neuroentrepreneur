"""Modeles, erreurs, regles de confirmation et apercu."""

from __future__ import annotations

import re
from datetime import datetime

import pytest
from pydantic import ValidationError

from factories import NOW, make_task
from neurocoach.domain.clock import local_today
from neurocoach.domain.confirmation import DirectOperation, requires_confirmation
from neurocoach.domain.errors import USER_MESSAGES, DomainError, ErrorCode
from neurocoach.domain.models import ActionType, Preferences, TaskStatus, new_id, updated
from neurocoach.domain.plans import Change
from neurocoach.domain.preview import describe_change, describe_preview, format_value

# --- modeles --------------------------------------------------------------------------


def test_new_id_format():
    assert re.fullmatch(r"tsk_[0-9a-f]{32}", new_id("tsk"))


def test_task_status_invariants_are_enforced():
    with pytest.raises(ValidationError):
        make_task(1, TaskStatus.DONE, completed_at=None)
    with pytest.raises(ValidationError):
        make_task(1, TaskStatus.TODO, completed_at=NOW)
    with pytest.raises(ValidationError):
        make_task(1, TaskStatus.BLOCKED, blocked_reason=None)
    with pytest.raises(ValidationError):
        make_task(1, TaskStatus.TODO, blocked_reason="Raison valable")


def test_naive_datetimes_are_refused():
    with pytest.raises(ValidationError):
        make_task(1, created_at=datetime(2026, 11, 9, 9, 0))


def test_preferences_validate_timezone_and_limits():
    with pytest.raises(ValidationError):
        Preferences(user_id="u", display_timezone="Mars/Olympus", updated_at=NOW)
    with pytest.raises(ValidationError):
        Preferences(user_id="u", max_visible_tasks=4, updated_at=NOW)
    assert Preferences(user_id="u", updated_at=NOW).max_visible_tasks == 3


def test_updated_converts_validation_errors():
    with pytest.raises(DomainError) as error:
        updated(make_task(1), title="x")
    assert error.value.code is ErrorCode.VALIDATION_ERROR
    assert "title" in error.value.user_message


def test_local_today_uses_display_timezone():
    late_evening_utc = datetime.fromisoformat("2026-11-09T23:30:00+00:00")
    assert str(local_today(late_evening_utc, "Europe/Paris")) == "2026-11-10"
    assert str(local_today(late_evening_utc, "America/Montreal")) == "2026-11-09"


def test_every_error_code_has_a_french_message():
    assert set(USER_MESSAGES) == set(ErrorCode)
    error = DomainError(ErrorCode.NOT_FOUND, "Projet introuvable.", hint=1)
    assert error.user_message.startswith("Élément introuvable.")
    assert error.data == {"hint": 1}
    assert DomainError(ErrorCode.NOT_FOUND).user_message == USER_MESSAGES[ErrorCode.NOT_FOUND]


# --- confirmation (R-CONF-01, R-CONF-02) ----------------------------------------------


@pytest.mark.parametrize("action_type", list(ActionType))
def test_every_action_type_requires_confirmation(action_type):
    assert requires_confirmation(action_type.value)


@pytest.mark.parametrize("operation", list(DirectOperation))
def test_direct_operations(operation):
    assert not requires_confirmation(operation.value)


def test_unknown_operation_requires_confirmation_by_default():
    assert requires_confirmation("task.rename_everything")


# --- apercu ---------------------------------------------------------------------------


def _change(**values):
    return Change(**values)


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (
            _change(
                op="add",
                entity="task",
                ref="T3",
                after={
                    "title": "Interroger",
                    "phase": "Valider",
                    "depends_on": ["T2"],
                    "due_date": "2026-11-14",
                },
            ),
            "Nouvelle tâche T3 : « Interroger », dans la phase « Valider », à faire après T2, "
            "pour le samedi 14 novembre 2026",
        ),
        (_change(op="add", entity="phase", ref="Vente"), "Nouvelle phase « Vente »"),
        (_change(op="delete", entity="phase", ref="Vide"), "Suppression de la phase vide « Vide »"),
        (
            _change(op="delete", entity="task", ref="T4", before={"title": "Ancienne"}),
            "Tâche T4 « Ancienne » retirée du plan",
        ),
        (
            _change(op="move", entity="task", ref="T2", after={"phase": "Vente", "position": 0}),
            "Tâche T2 déplacée dans la phase « Vente »",
        ),
        (
            _change(
                op="update",
                entity="task",
                ref="T2",
                before={"due_date": "2026-11-12"},
                after={"due_date": "2026-11-14"},
            ),
            "Tâche T2 modifiée — échéance : samedi 14 novembre 2026 "
            "(au lieu de jeudi 12 novembre 2026)",
        ),
        (
            _change(
                op="update",
                entity="project",
                ref="projet",
                before={"constraints": []},
                after={"constraints": ["30 min", "budget"]},
            ),
            "Projet mis à jour — contraintes notées : « 30 min » ; « budget »",
        ),
        (
            _change(op="delete", entity="project", ref="Bougies", before={"phases": 1, "tasks": 3}),
            "Suppression du projet « Bougies » (1 phase(s), 3 tâche(s) "
            "et la conversation associée)",
        ),
        (
            _change(
                op="delete", entity="user", ref="vos données", before={"projects": 2, "tasks": 5}
            ),
            "Suppression de toutes vos données : 2 projet(s), 5 tâche(s), "
            "historique et conversations",
        ),
    ],
)
def test_describe_change(change, expected):
    assert describe_change(change) == expected


def test_describe_preview_and_fallback():
    assert describe_preview([_change(op="update", entity="phase", ref="P")]) == [
        "Modification de « P »"
    ]
    assert format_value("priority", 4) == "4 sur 5"
    assert format_value("due_date", None) == "aucun"
    assert format_value("position", 0) == "1e position"


def test_preview_lines_are_plain_french_without_symbols():
    """Finition phase 5 : ni fleche, ni tiret de valeur vide, ni libelle technique."""
    project = _change(
        op="update",
        entity="project",
        ref="projet",
        before={"facts": [], "horizon_date": "2026-11-20", "description": "Ancienne"},
        after={
            "facts": ["J'ai 45 minutes par jour."],
            "horizon_date": "2026-11-30",
            "description": None,
        },
    )
    lines = describe_preview([project])
    assert lines == [
        "Ce que vous avez précisé : « J'ai 45 minutes par jour. »",
        "Date visée : lundi 30 novembre 2026 (au lieu de vendredi 20 novembre 2026)",
        "Description : à retirer (actuellement « Ancienne »)",
    ]
    for line in lines:
        assert "→" not in line and "—" not in line and "·" not in line
