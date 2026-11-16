"""Description en francais des elements d'apercu (DOMAIN_CONTRACTS section 5.2).

Finition de phase 5 : des phrases naturelles, sans fleche ni tiret de valeur vide
(« Projet · faits : — → … » etait incomprehensible pour un porteur de projet).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from neurocoach.domain.plans import Change

FIELD_LABELS: dict[str, str] = {
    "title": "titre",
    "acceptance_criteria": "critère de fin",
    "description": "description",
    "priority": "importance",
    "estimate_minutes": "durée estimée",
    "due_date": "échéance",
    "phase": "phase",
    "position": "place dans la phase",
    "exit_criterion": "critère de fin de phase",
    "target_outcome": "objectif visé",
    "constraints": "contraintes notées",
    "facts": "ce que vous avez précisé",
    "assumptions": "hypothèses à vérifier",
    "available_minutes_per_day": "temps disponible",
    "horizon_date": "date visée",
}

_DATE_FIELDS = {"due_date", "horizon_date"}
# Textes libres encadres de guillemets : « titre : « A » » reste lisible meme quand la
# valeur contient elle-meme deux-points.
_TEXT_FIELDS = {
    "title",
    "acceptance_criteria",
    "description",
    "exit_criterion",
    "target_outcome",
    "phase",
}
EMPTY = "aucun"
_DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_MONTHS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)  # fmt: skip


def format_date_fr(value: date) -> str:
    """« vendredi 13 novembre 2026 » : independant de la locale du systeme (D-58)."""
    day = "1er" if value.day == 1 else str(value.day)
    return f"{_DAYS[value.weekday()]} {day} {_MONTHS[value.month - 1]} {value.year}"


def format_value(name: str, value: Any) -> str:
    if value is None or value == []:
        return EMPTY
    if name in _DATE_FIELDS:
        return format_date_fr(date.fromisoformat(str(value)))
    if name == "available_minutes_per_day":
        return f"{value} minutes par séance de travail"
    if name == "estimate_minutes":
        return f"{value} minutes"
    if name == "priority":
        return f"{value} sur 5"
    if name == "position":
        return f"{int(value) + 1}e position"
    if isinstance(value, list):
        return " ; ".join(f"« {item} »" for item in value)
    if name in _TEXT_FIELDS:
        return f"« {value} »"
    return str(value)


def describe_field(name: str, before: Any, after: Any) -> str:
    """« libelle : nouvelle valeur », en rappelant l'ancienne valeur si elle existe."""
    label = FIELD_LABELS.get(name, name)
    new, old = format_value(name, after), format_value(name, before)
    if new == EMPTY:
        return f"{label} : à retirer (actuellement {old})"
    if old == EMPTY:
        return f"{label} : {new}"
    return f"{label} : {new} (au lieu de {old})"


def _field_diffs(change: Change) -> str:
    before = change.before or {}
    after = change.after or {}
    return " ; ".join(describe_field(name, before.get(name), after[name]) for name in after)


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]


def describe_change(change: Change) -> str:
    """Une ligne lisible par element d'apercu."""
    after = change.after or {}
    before = change.before or {}
    match (change.op, change.entity):
        case ("add", "task"):
            text = (
                f"Nouvelle tâche {change.ref} : « {after['title']} », "
                f"dans la phase « {after['phase']} »"
            )
            if after.get("depends_on"):
                text += f", à faire après {' et '.join(after['depends_on'])}"
            if after.get("due_date"):
                text += f", pour le {format_value('due_date', after['due_date'])}"
            return text
        case ("add", "phase"):
            return f"Nouvelle phase « {change.ref} »"
        case ("delete", "phase"):
            return f"Suppression de la phase vide « {change.ref} »"
        case ("delete", "task"):
            return f"Tâche {change.ref} « {before['title']} » retirée du plan"
        case ("move", "task"):
            return f"Tâche {change.ref} déplacée dans la phase « {after['phase']} »"
        case ("update", "project") if "pause" in after:
            # D-85 : pause ou reprise ; la raison est celle que la personne a donnee.
            if after["pause"] == "en pause":
                said = str(after.get("note") or "").strip().rstrip(".")
                note = f" — raison notée : « {said} »" if said else ""
                return f"Projet « {change.ref} » mis en pause{note}"
            return f"Projet « {change.ref} » repris"
        case ("update", "project"):
            return f"Projet mis à jour — {_field_diffs(change)}"
        case ("update", "task") if set(after) == {"status"} and after["status"] == "done":
            return f"Tâche {change.ref} « {before.get('title', '')} » : terminée"
        case ("update", "task"):
            return f"Tâche {change.ref} modifiée — {_field_diffs(change)}"
        case ("delete", "project"):
            return (
                f"Suppression du projet « {change.ref} » ({before['phases']} phase(s), "
                f"{before['tasks']} tâche(s) et la conversation associée)"
            )
        case ("delete", "user"):
            return (
                f"Suppression de toutes vos données : {before['projects']} projet(s), "
                f"{before['tasks']} tâche(s), historique et conversations"
            )
    return f"Modification de « {change.ref} »"


def describe_preview(changes: list[Change]) -> list[str]:
    """Une ligne par element ; la mise a jour du projet est detaillee champ par champ."""
    lines: list[str] = []
    for change in changes:
        pause = change.after is not None and "pause" in change.after  # D-85 : une seule ligne
        if (change.op, change.entity) == ("update", "project") and change.after and not pause:
            before = change.before or {}
            lines.extend(
                _capitalize(describe_field(name, before.get(name), value))
                for name, value in change.after.items()
            )
        else:
            lines.append(describe_change(change))
    return lines
