"""Gabarits deterministes en francais pour les faits metier (DOMAIN_CONTRACTS 11.5, D-15).

Les chiffres et statuts proviennent toujours de la base ; le LLM ne les formule jamais.
"""

from __future__ import annotations

from neurocoach.application.services import StatusChange
from neurocoach.domain.errors import DomainError
from neurocoach.domain.models import STATUS_LABELS, Cadence, Project, Task, TaskStatus
from neurocoach.domain.plans import ProjectSnapshot
from neurocoach.domain.priority import NextActions, Recommendation
from neurocoach.domain.progress import PhaseProgress, ProgressSummary, format_percent

OUT_OF_SCOPE_MESSAGE = (
    "Je suis un assistant d'organisation de projet : je ne peux pas donner d'avis médical, "
    "juridique ou financier personnalisé. Pour ces questions, un professionnel qualifié "
    "saura vous aider. Je peux en revanche vous aider à structurer les prochaines étapes."
)


def _plural(count: int, singular: str, plural: str) -> str:
    return singular if count <= 1 else plural


def format_progress(summary: ProgressSummary) -> str:
    if summary.total == 0:
        return "Pas encore de plan."
    done_word = _plural(summary.done, "tâche terminée", "tâches terminées")
    text = f"{summary.done} {done_word} sur {summary.total} ({format_percent(summary.percent)})."
    if summary.blocked:
        text += f" {summary.blocked} {_plural(summary.blocked, 'bloquée', 'bloquées')}."
    return text


def format_recommendation(item: Recommendation) -> str:
    text = f"{item.ref} « {item.title} »"
    if item.kind == "lever_blocage":
        return f"{text} est bloquée : la prochaine étape serait de lever ce blocage."
    if item.kind == "decouper":
        return f"{text} semble longue pour le temps disponible : on peut la découper."
    return text


NO_READY_TASK = (
    "Aucune tâche n'est réalisable pour l'instant : les tâches restantes attendent que "
    "d'autres soient terminées."
)


def format_next_step(next_actions: NextActions) -> str:
    """« Et maintenant ? » : UNE prochaine tache realisable, choisie par le moteur de priorite
    (score, puis phase, position et numero : regle deterministe), ou la raison de l'absence."""
    match next_actions.state:
        case "ok":
            return f"Prochaine tâche réalisable : {format_recommendation(next_actions.items[0])}."
        case "repli":
            assert next_actions.fallback is not None
            return (
                "Aucune tâche n'est réalisable pour l'instant. "
                f"{format_recommendation(next_actions.fallback)}"
            )
    return format_next_actions(next_actions)


def format_next_actions(next_actions: NextActions) -> str:
    match next_actions.state:
        case "pas_de_plan":
            return "Pas encore de plan : nous pouvons en construire un ensemble."
        case "plan_termine":
            return "Toutes les tâches du plan sont terminées."
        case "aucune_action":
            return NO_READY_TASK
        case "repli":
            assert next_actions.fallback is not None
            return format_recommendation(next_actions.fallback)
    items = next_actions.items
    if len(items) == 1:
        return f"Prochaine action : {format_recommendation(items[0])}."
    lines = "\n".join(f"- {format_recommendation(item)}" for item in items)
    return f"Prochaines actions possibles :\n{lines}"


CADENCE_HINTS = {
    Cadence.QUOTIDIENNE: "Rythme choisi : un petit point chaque jour, même bref.",
    Cadence.HEBDOMADAIRE: "Rythme choisi : un point par semaine, sans pression entre-temps.",
}


def cadence_hint(cadence: Cadence | str | None) -> str | None:
    """D-12 : la cadence ne declenche aucune notification, elle oriente seulement la formulation."""
    return CADENCE_HINTS.get(Cadence(cadence)) if cadence else None


def format_resume_message(
    project: Project,
    summary: ProgressSummary,
    next_actions: NextActions,
    cadence: Cadence | str | None = None,
    plan_pending: bool = False,
) -> str:
    """US-06 : message de reprise construit uniquement a partir de la base."""
    if summary.total == 0 and plan_pending:
        # Finition phase 5 : ne pas annoncer « pas encore de plan » sous un plan propose.
        return (
            f"« {project.title} » n'a pas encore de plan enregistré. Une proposition vous "
            "attend : rien ne sera enregistré avant votre confirmation."
        )
    if summary.total == 0:
        # D-80 : un rappel factuel ; le moment du plan est decide dans la conversation.
        name = "votre projet" if project.title_pending else f"« {project.title} »"
        return f"Bon retour sur {name}. Ce projet n'a pas encore de plan."
    done_word = _plural(summary.done, "tâche", "tâches")
    opening = f"Vous avez terminé {summary.done} {done_word} sur {summary.total}."
    if next_actions.state == "ok":
        first = next_actions.items[0]
        verb = "reprendre" if summary.done or summary.in_progress else "commencer"
        text = (
            f"{opening} Prochaine action : {first.ref} « {first.title} ». "
            f"Voulez-vous la {verb} ou la simplifier ?"
        )
    else:
        text = f"{opening} {format_next_actions(next_actions)}"
    hint = cadence_hint(cadence)
    return f"{text} {hint}" if hint else text


def format_phase_header(phase: PhaseProgress) -> str:
    """Titre de phase avec progression calculee (jamais estimee par le LLM)."""
    labels = {
        "vide": "vide",
        "a_faire": "à faire",
        "en_cours": "en cours",
        "terminee": "terminée",
    }
    if phase.total == 0:
        return f"{phase.title} — aucune tâche"
    return (
        f"{phase.title} — {phase.done}/{phase.total} ({format_percent(phase.percent)}), "
        f"{labels[phase.status]}"
    )


def describe_dependencies(task: Task, snapshot: ProjectSnapshot) -> str | None:
    """Dependances d'une tache, avec leur statut, en clair."""
    deps = sorted(
        (snapshot.tasks[dep] for (owner, dep) in snapshot.dependencies if owner == task.id),
        key=lambda item: item.number,
    )
    if not deps:
        return None
    waiting = [dep.ref for dep in deps if dep.status is not TaskStatus.DONE]
    listed = ", ".join(f"{dep.ref} ({STATUS_LABELS[dep.status]})" for dep in deps)
    if waiting and task.status is not TaskStatus.DONE:
        return f"Après {listed}. En attente de {', '.join(waiting)}."
    return f"Après {listed}."


def format_status_change(change: StatusChange) -> str:
    task = change.task
    if not change.changed:
        return f"{task.ref} est déjà {STATUS_LABELS[task.status]}."
    text = f"{task.ref} est maintenant {STATUS_LABELS[task.status]}."
    if change.unmet_dependencies:
        refs = ", ".join(change.unmet_dependencies)
        verb = _plural(
            len(change.unmet_dependencies),
            "n'est pas encore terminée",
            "ne sont pas encore terminées",
        )
        text += f" À noter : {refs} {verb}."
    return text + " Vous pouvez annuler ce changement."


def format_error(error: DomainError) -> str:
    return error.user_message
