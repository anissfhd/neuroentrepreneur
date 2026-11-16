"""Affichage des propositions et regles de presentation (D-77, revu par D-78).

D-78 (recette manuelle reelle du 11/11/2026) : les textes de coaching codes en dur (piste
provisoire de secours, questions imposees, offre de recherche, objectif provisoire) sont
retires. Le coach, c'est le modele : il ecrit ses reponses et ses recommandations. Ce module
ne garde que l'affichage des DONNEES d'une proposition (taches, durees, priorites, criteres) et
les instructions de validation (boutons), qui relevent des permissions, pas du coaching.
"""

from __future__ import annotations

import re
from typing import Any

from neurocoach.domain.models import TaskStatus
from neurocoach.domain.plans import PlanDraft, ProjectSnapshot

# Choix de presentation de l'etat du projet (les donnees viennent de la base).
DONE_QUERY = re.compile(
    r"qu'ai-je (?:d[ée]j[àa] )?(?:termin|fait|accompli|fini)|qu'est-ce que j'ai (?:d[ée]j[àa] )?"
    r"(?:termin|fait|fini)|t[âa]ches? (?:d[ée]j[àa] )?termin[ée]es|ce que j'ai (?:d[ée]j[àa] )?"
    r"(?:fait|termin)|j'ai (?:d[ée]j[àa] )?fait quoi",
    re.IGNORECASE,
)

NO_PLAN_STATUS = "Ce projet n'a pas encore de plan enregistré."
PLAN_LABEL = "Voici la proposition de plan."
PROVISIONAL_LABEL = (
    "Voici la proposition de plan. Elle est provisoire : aucune recherche de marché n'a encore "
    "été faite pour ce projet."
)
PLAN_BUTTONS = (
    "Rien n'est enregistré avant votre clic : « Accepter et ajouter ce plan à mes tâches » "
    "pour l'enregistrer et commencer le suivi, ou « Demander un changement » pour me dire ce "
    "que vous voulez modifier."
)
PRIORITY_LABELS = {5: "très haute", 4: "haute", 3: "normale", 2: "basse", 1: "très basse"}


def plan_capacity_errors(draft: PlanDraft, *, session: int | None, weekly: int | None) -> list[str]:
    errors = []
    for phase in draft.phases:
        for task in phase.tasks:
            if task.estimate_minutes is None:
                errors.append(f"Estimer la durée de {task.title}.")
            elif session is not None and task.estimate_minutes > session:
                errors.append(f"Découper {task.title} en séances de {session} min maximum.")
        if weekly is not None:
            total = sum(task.estimate_minutes or 0 for task in phase.tasks)
            if total > weekly:
                errors.append(
                    f"{phase.title} représente {total} min pour {weekly} min disponibles par "
                    "semaine. Réduire le périmètre ou répartir le travail sur plusieurs phases."
                )
    return errors


def revision_capacity_errors(
    before: ProjectSnapshot, after: ProjectSnapshot, weekly: int | None
) -> list[str]:
    errors = []
    for task in after.ordered_tasks():
        old = before.tasks.get(task.id)
        if (
            old is not None
            and old.estimate_minutes
            and task.estimate_minutes
            and task.estimate_minutes < old.estimate_minutes
            and task.description == old.description
            and task.acceptance_criteria == old.acceptance_criteria
        ):
            errors.append(f"{task.ref} : réduire le travail, pas seulement sa durée.")
    if weekly is not None:
        for phase in after.ordered_phases():
            remaining = sum(
                task.estimate_minutes or 0
                for task in after.phase_tasks(phase.id)
                if task.status is not TaskStatus.DONE
            )
            if remaining > weekly:
                errors.append(f"{phase.title} : {remaining} min restantes pour {weekly} min.")
    return errors


def lower_first(text: str) -> str:
    text = (text or "").strip().rstrip(".")
    return text[:1].lower() + text[1:] if text else text


def task_details(tasks: list[dict[str, Any]]) -> list[str]:
    """Une ligne par tache proposee : duree, priorite, critere de fin (ordre du plan)."""
    lines = []
    for task in tasks:
        bits = []
        if task.get("estimate_minutes"):
            bits.append(f"environ {task['estimate_minutes']} min")
        if task.get("priority"):
            bits.append(f"priorité {PRIORITY_LABELS.get(int(task['priority']), 'normale')}")
        meta = f" ({', '.join(bits)})" if bits else ""
        lines.append(
            f"« {task['title']} »{meta} : terminée quand {lower_first(task['acceptance_criteria'])}"
        )
    return lines


def how_to(title: str, description: str | None, criteria: str | None) -> str:
    """Ce que la proposition dit d'une tache (texte du modele), sans rien ajouter."""
    parts = []
    if description:
        parts.append(f"Comment faire : {description.strip().rstrip('.')}.")
    if criteria:
        parts.append(f"C'est terminé quand {lower_first(criteria)}.")
    return " ".join(parts)


def without_deadlines(draft: Any) -> Any:
    """L'utilisateur a refuse les dates limites : aucune echeance dans la proposition."""
    phases = [
        phase.model_copy(
            update={"tasks": [t.model_copy(update={"due_in_days": None}) for t in phase.tasks]}
        )
        for phase in draft.phases
    ]
    return draft.model_copy(update={"phases": phases})


def plan_details(draft: Any) -> str:
    """Donnees de la proposition (redigees par le modele), etape par etape : taches, duree,
    critere de fin, comment faire et ressources, dependances ; points d'attention et premiere
    action (D-82 : le plan est le moment ou la reponse peut etre detaillee)."""
    tasks = [t for phase in draft.phases for t in phase.tasks]
    titles = {t.key: t.title for t in tasks}
    lines: list[str] = []
    for number, phase in enumerate(draft.phases, 1):
        exit_text = getattr(phase, "exit_criterion", None)
        done = f" (étape franchie quand {lower_first(exit_text)})" if exit_text else ""
        lines += [f"**Étape {number} : {phase.title}**{done}", ""]
        for task, line in zip(
            phase.tasks, task_details([t.model_dump() for t in phase.tasks]), strict=True
        ):
            after = [titles[d] for d in task.depends_on if d in titles]
            extra = f" Après : « {' », « '.join(after)} »." if after else ""
            how = (
                f" Comment faire : {task.description.strip().rstrip('.')}."
                if task.description
                else ""
            )
            lines.append(f"- {line}.{how}{extra}")
        lines.append("")
    risks = list(getattr(draft, "risks", []) or [])
    if risks:
        lines += ["", "Points d'attention : " + " ; ".join(r.rstrip(".") for r in risks[:4]) + "."]
    first = next((t for t in tasks if not t.depends_on), tasks[0] if tasks else None)
    step = getattr(draft, "first_step", None) or (first.description if first else None)
    if first is not None:
        how = f" Comment faire : {step.strip().rstrip('.')}." if step else ""
        lines += ["", f"Première action proposée : « {first.title} ».{how}"]
    return "\n".join(lines)
