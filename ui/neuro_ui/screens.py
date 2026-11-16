"""Pages de la plateforme (D-76) : bienvenue, accueil, projets, taches, historique,
parametres, profil. Elles lisent les services existants ; aucune n'ecrit en base sans un
clic explicite de l'utilisateur."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import streamlit as st

from neuro_ui.components import (
    badge,
    brand_html,
    empty_state,
    esc,
    flash,
    icon,
    local_time,
    md_text,
    page_title,
    progress_bar,
    run_safely,
    section_title,
    show_flash,
    topbar,
)
from neuro_ui.context import Ctx
from neuro_ui.nav import PROFILE, PROJECT, PROJECTS, TASKS, close_space, go, open_space
from neuro_ui.project_view import (
    progress_text,
    project_state,
    queue_message,
    render_deletion_confirmation,
)
from neurocoach.domain.clock import local_today
from neurocoach.domain.errors import DomainError
from neurocoach.domain.models import STATUS_LABELS, ActionType, Cadence, ResponseLength, TaskStatus
from neurocoach.domain.plans import Change
from neurocoach.domain.preview import describe_preview, format_date_fr
from neurocoach.domain.profiles import initials
from neurocoach.domain.progress import format_percent

RESPONSE_LABELS = {"court": "Courtes", "standard": "Standard", "detaille": "Détaillées"}
CADENCE_LABELS = {
    "flexible": "Flexible (aucun rythme imposé)",
    "quotidienne": "Un petit point chaque jour",
    "hebdomadaire": "Un point par semaine",
}
NOT_AUTH = (
    "Prototype local : le nom d'utilisateur ouvre votre espace sur cet ordinateur. Ce n'est "
    "ni un mot de passe ni une connexion sécurisée ; il ne suffit pas pour une mise en ligne."
)


def _error_text(error: DomainError) -> str:
    return error.detail or error.user_message


# --- premiere ouverture : creation du profil ---------------------------------------------
def render_welcome(app: Any) -> None:
    st.html(
        '<div class="ne-welcome">'
        f"{brand_html()}"
        "<h1>Bienvenue sur NeuroEntrepreneur</h1>"
        "<p>«\u00a0Votre coach IA pour transformer vos idées en projets concrets, à votre "
        "rythme.\u00a0»</p></div>"
    )
    _, middle, _ = st.columns([1, 2.4, 1])
    with middle:
        with st.container(key="card_profile"):
            st.subheader("Créer votre profil", anchor=False)
            with st.form("profile_form", border=False):
                first = st.text_input("Prénom", key="profile_first", max_chars=40,
                                      placeholder="Ex. : Marie")  # fmt: skip
                last = st.text_input("Nom", key="profile_last", max_chars=40,
                                     placeholder="Ex. : Dupont")  # fmt: skip
                username = st.text_input(
                    "Nom d'utilisateur unique",
                    key="profile_username",
                    max_chars=30,
                    placeholder="Ex. : marie.dupont",
                    help="3 à 30 caractères : lettres, chiffres, points, tirets ou traits bas.",
                )
                created = st.form_submit_button(
                    "Créer mon espace", type="primary", width="stretch", key="create_space"
                )
            if created:
                try:
                    user = app.coach.register_user(first, last, username)
                except DomainError as error:
                    st.error(_error_text(error))
                else:
                    open_space(user.id)
            st.caption(NOT_AUTH)
        with st.expander("Vous avez déjà un espace ? Le rouvrir"):
            with st.form("reopen_form", border=False):
                existing = st.text_input("Votre nom d'utilisateur", key="reopen_username")
                reopen = st.form_submit_button("Rouvrir mon espace", key="reopen_space")
            if reopen:
                user = app.coach.find_user(existing)
                if user is None:
                    st.error("Aucun espace ne porte ce nom d'utilisateur sur cet ordinateur.")
                else:
                    open_space(user.id)


# --- accueil ------------------------------------------------------------------------------
def start_new_project(ctx: Ctx) -> None:
    """« Créer votre projet » : ouvre directement la conversation, accueil du coach compris
    (sans appel au modele)."""
    project = ctx.agent.start_project(ctx.user_id)
    ctx.agent.greet(ctx.user_id, project.id)
    go(PROJECT, project.id)


def _project_rows(ctx: Ctx) -> list[dict[str, Any]]:
    """Projets de l'utilisateur avec progression reelle et derniere activite connue."""
    app, agent = ctx.app, ctx.agent
    events = app.coach.last_activity(ctx.user_id)
    rows = []
    for project in app.coach.list_projects(ctx.user_id):
        summary = app.coach.get_progress(ctx.user_id, project.id)
        conversation = agent.conversation_summary(ctx.user_id, project.id)
        moments = [project.updated_at, events.get(project.id)]
        if conversation["saved_at"]:
            moments.append(datetime.fromisoformat(conversation["saved_at"]))
        last = max(m for m in moments if m is not None)
        rows.append(
            {"project": project, "summary": summary, "last": last, "conversation": conversation}
        )
    return sorted(rows, key=lambda row: row["last"], reverse=True)


def render_dashboard(ctx: Ctx) -> None:
    with st.container(key="overview_home"):
        with st.container(
            key="overview_toolbar", horizontal=True, horizontal_alignment="distribute"
        ):
            if st.button("Créer votre projet", key="go_create", icon=":material/edit_square:",
                         type="tertiary"):  # fmt: skip
                start_new_project(ctx)
            with (
                st.container(key="overview_account", width="content"),
                st.popover(
                    initials(ctx.user.first_name, ctx.user.last_name, ctx.user.display_name),
                    help="Menu du profil",
                ),
            ):
                st.markdown(f"**{md_text(ctx.user.display_name)}**")
                if st.button("Mon profil", key="overview_profile", icon=":material/person:"):
                    go(PROFILE)
        show_flash()
        st.html(
            '<div class="ne-overview-hero"><span aria-hidden="true">✦</span>'
            f"<h1>Bonjour {esc(ctx.first_name)} !</h1>"
            "<p>Que souhaitez-vous avancer aujourd&#39;hui ?</p></div>"
        )
        with st.container(key="overview_composer"):
            draft = st.chat_input(
                "Discutez avec votre coach IA…",
                key="chat",
                accept_file=True,
                file_type=["png", "jpg", "jpeg", "webp"],
                max_upload_size=5,
            )
            if draft:
                project = ctx.agent.start_project(ctx.user_id)
                ctx.agent.greet(ctx.user_id, project.id)
                queue_message(project.id)
                go(PROJECT, project.id)
        _overview(ctx, _project_rows(ctx), projects_page=False)


def _overview(ctx: Ctx, rows: list[dict[str, Any]], *, projects_page: bool) -> None:
    with st.container(key="overview_summary"):
        active = [
            row
            for row in rows
            if project_state(row["project"], row["summary"])[0] not in ("En pause", "Terminé")
        ]
        total = sum(row["summary"].total for row in rows)
        done = sum(row["summary"].done for row in rows)
        for col, (symbol, value, label) in zip(
            st.columns(3),
            (
                ("folder-open", str(len(active)), "Projets actifs"),
                ("list-checks", str(total - done), "Tâches en attente"),
                ("trend", f"{round(100 * done / total) if total else 0} %", "Taux d'avancement"),
            ),
            strict=True,
        ):
            col.html(
                f'<div class="ne-overview-metric"><span>{icon(symbol)}</span>'
                f"<div><strong>{value}</strong><small>{label}</small></div></div>"
            )
        projects, tasks = st.columns(2, gap="medium")
        with projects, st.container(key="overview_projects", border=True):
            heading, link = st.columns([3, 1], vertical_alignment="center")
            heading.subheader("Mes projets", anchor=False)
            if not projects_page and link.button("Tout voir →", key="overview_all_projects"):
                go(PROJECTS)
            for row in rows[:2]:
                project = row["project"]
                state, tone = project_state(
                    project, row["summary"], row["conversation"]["user_count"] > 0
                )
                with st.container(key=f"overview_row_{project.id}", border=True):
                    title, status = st.columns([3, 2], vertical_alignment="center")
                    title.markdown(f":material/folder_open: **{md_text(project.title)}**")
                    status.html(badge(state, tone))
                    st.button(
                        f"Ouvrir {md_text(project.title)}",
                        key=f"resume_{project.id}",
                        type="tertiary",
                        on_click=go,
                        args=(PROJECT, project.id),
                        kwargs={"rerun": False},
                    )
            if not rows:
                st.caption("Vos projets apparaîtront ici.")
        with tasks, st.container(key="overview_tasks", border=True):
            heading, link = st.columns([3, 1], vertical_alignment="center")
            heading.subheader("Tâches prioritaires", anchor=False)
            if link.button("Tout voir →", key="overview_all_tasks"):
                go(TASKS)
            recommendations = []
            for row in active:
                if row["summary"].total:
                    project = row["project"]
                    actions = ctx.app.coach.get_next_actions(ctx.user_id, project.id)
                    recommendations.extend((item.score, project.id, item) for item in actions.items)
            for _, project_id, item in sorted(
                recommendations, key=lambda recommendation: -recommendation[0]
            )[:3]:
                if st.button(
                    md_text(item.title),
                    key=f"overview_task_{item.task_id}",
                    icon=":material/checklist:",
                    type="tertiary",
                ):
                    go(PROJECT, project_id)
            if not recommendations:
                st.html(
                    f'<div class="ne-overview-empty"><span>{icon("list-checks")}</span>'
                    "<strong>Aucune tâche prioritaire</strong>"
                    "<small>Les tâches prêtes à avancer apparaîtront ici.</small></div>"
                )


# --- mes projets ----------------------------------------------------------------------------
def render_projects(ctx: Ctx) -> None:
    topbar(ctx.user)
    show_flash()
    head, action = st.columns([3, 1], vertical_alignment="bottom")
    with head:
        page_title("Mes projets", "Retrouvez vos projets et leur progression.")
    with action:
        if st.button("Nouveau projet", key="new_project", type="primary",
                     icon=":material/add:", width="stretch"):  # fmt: skip
            start_new_project(ctx)
    rows = _project_rows(ctx)
    _overview(ctx, rows, projects_page=True)
    if not rows:
        with st.container(key="card_empty_projects"):
            empty_state(
                "folder-open",
                "Aucun projet pour le moment",
                "Commencez par parler de votre idée à votre coach : il vous aidera à la "
                "transformer en plan d'action.",
            )
            if st.button("Créer votre projet", key="empty_create", type="primary"):
                start_new_project(ctx)
        return
    columns = st.columns(2, gap="medium")
    for index, row in enumerate(rows):
        project, summary = row["project"], row["summary"]
        with columns[index % 2], st.container(key=f"card_project_{project.id}"):
            started = ctx.agent.conversation_summary(ctx.user_id, project.id)
            state, tone = project_state(project, summary, started["user_count"] > 0)
            st.html(
                f'<div style="display:flex;justify-content:space-between;gap:.5rem;'
                f'align-items:flex-start"><strong style="font-size:1.05rem">'
                f"{esc(project.title)}</strong>{badge(state, tone)}</div>"
            )
            description = project.target_outcome or project.idea
            if description:
                short = description if len(description) <= 140 else description[:137] + "…"
                st.caption(md_text(short))
            if summary.total:
                progress_bar(
                    summary.percent,
                    f"{progress_text(summary)} ({format_percent(summary.percent)})",
                )
            else:
                st.caption("Pas encore de plan : 0 tâche.")
            st.caption(f"Dernière activité : {local_time(row['last'], ctx.prefs.display_timezone)}")
            if st.button("Ouvrir le projet", key=f"open_{project.id}", width="stretch"):
                go(PROJECT, project.id)
            rename, delete = st.columns(2)
            with rename.popover("Renommer"), st.form(f"rename_{project.id}", border=False):
                title = st.text_input(
                    "Titre du projet",
                    value=project.title,
                    max_chars=120,
                    help="7 mots maximum.",
                )
                if st.form_submit_button("Enregistrer"):
                    if run_safely(ctx.app.coach.rename_project, ctx.user_id, project.id, title):
                        flash("success", "Titre enregistré.")
                    st.rerun()
            if delete.button("Supprimer…", key=f"delete_{project.id}"):
                run_safely(ctx.app.actions.request_project_deletion, ctx.user_id, project.id)
                st.rerun()
            pending = ctx.app.actions.get_pending(ctx.user_id, project.id)
            if pending and pending.action_type is ActionType.PROJECT_DELETE:
                render_deletion_confirmation(ctx, project, pending)


# --- mes taches ------------------------------------------------------------------------------
TASK_GROUPS = (
    (TaskStatus.TODO, "À faire"),
    (TaskStatus.IN_PROGRESS, "En cours"),
    (TaskStatus.BLOCKED, "Bloquées"),
    (TaskStatus.DONE, "Terminées"),
)


def render_tasks(ctx: Ctx) -> None:
    topbar(ctx.user)
    show_flash()
    page_title("Mes tâches", "Toutes les tâches de vos projets, selon leur statut.")
    st.caption(
        "Pour commencer, terminer ou bloquer une tâche, ouvrez son projet : chaque changement "
        "y est enregistré avec la possibilité de l'annuler."
    )
    items = []
    for project in ctx.app.coach.list_projects(ctx.user_id):
        snapshot = ctx.app.coach.get_snapshot(ctx.user_id, project.id)
        items += [(project, task) for task in snapshot.ordered_tasks()]
    if not items:
        with st.container(key="card_empty_tasks"):
            empty_state(
                "list-checks",
                "Aucune tâche pour le moment",
                "Les tâches apparaissent ici dès qu'un plan est confirmé dans un projet.",
            )
        return
    today = local_today(ctx.app.clock.now(), ctx.prefs.display_timezone)
    due_today = [
        (project, task)
        for project, task in items
        if ctx.prefs.deadlines_enabled
        and task.due_date == today
        and task.status is not TaskStatus.DONE
    ]
    if not due_today:
        for project, task in items:
            if project.paused_at or task.status is TaskStatus.DONE:
                continue
            actions = ctx.app.coach.get_next_actions(ctx.user_id, project.id)
            if actions.items:
                task_id = actions.items[0].task_id
                due_today = [(p, t) for p, t in items if p.id == project.id and t.id == task_id]
                break
    if due_today:
        scheduled = ctx.prefs.deadlines_enabled and all(t.due_date == today for _, t in due_today)
        heading = "À réaliser aujourd'hui" if scheduled else "Action conseillée aujourd'hui"
        st.subheader(heading, anchor=False)
        for project, task in due_today:
            st.caption(md_text(project.title))
            if task.description:
                st.write(md_text(task.description))
            if st.button(md_text(f"{task.ref} · {task.title}"), key=f"today_{task.id}"):
                go(PROJECT, project.id)
    tabs = st.tabs(
        [f"{label} ({sum(t.status is s for _, t in items)})" for s, label in TASK_GROUPS],
        key="tasks_tab",
    )
    for tab, (status, label) in zip(tabs, TASK_GROUPS, strict=True):
        with tab:
            group = [(p, t) for p, t in items if t.status is status]
            if not group:
                st.caption(f"Aucune tâche « {label.lower()} ».")
            for project, task in group:
                with st.container(key=f"card_task_{task.id}"):
                    text, action = st.columns([4, 1], vertical_alignment="center")
                    with text:
                        st.markdown(f"**{task.ref} · {md_text(task.title)}**")
                        details = [f"Projet : {md_text(project.title)}",
                                   f"Statut : {STATUS_LABELS[task.status]}"]  # fmt: skip
                        if task.estimate_minutes:
                            details.append(f"{task.estimate_minutes} min")
                        if ctx.prefs.deadlines_enabled and task.due_date:
                            details.append(f"échéance {format_date_fr(task.due_date)}")
                        st.caption(" · ".join(details))
                        if task.blocked_reason:
                            st.caption(f"Blocage : {md_text(task.blocked_reason)}")
                    with action:
                        if st.button("Ouvrir le projet", key=f"task_open_{task.id}",
                                     width="stretch"):  # fmt: skip
                            go(PROJECT, project.id)


# --- historique ------------------------------------------------------------------------------
EVENT_LABELS = {
    "project.created": "Projet créé",
    "project.renamed": "Titre du projet enregistré",
    "project.deleted": "Projet supprimé",
    "plan.applied": "Plan enregistré",
    "plan.replanned": "Plan modifié",
    "task.created": "Tâche ajoutée",
    "task.updated": "Tâche modifiée",
    "task.deleted": "Tâche retirée",
    "task.status_changed": "Statut d'une tâche changé",
    "task.status_reverted": "Changement de statut annulé",
    "preferences.updated": "Préférences modifiées",
    "profile.created": "Profil créé",
    "profile.updated": "Profil modifié",
    "pending_action.created": "Proposition présentée",
    "pending_action.applied": "Proposition confirmée",
    "pending_action.cancelled": "Proposition annulée",
    "pending_action.expired": "Proposition expirée",
    "pending_action.superseded": "Proposition remplacée",
    "pending_action.failed": "Proposition non appliquée",
    "user.data_exported": "Données exportées",
    "research.mission_proposed": "Recherche proposée",
    "research.mission_approved": "Recherche approuvée",
    "research.mission_cancelled": "Recherche annulée",
    "research.mission_expired": "Recherche expirée",
    "research.mission_superseded": "Recherche remplacée",
    "research.mission_closed": "Recherche close",
    "research.query_run": "Recherche web effectuée",
    "research.query_refused": "Recherche web refusée (budget ou quota)",
    "research.analysis_created": "Analyse produite",
    "research.solutions_created": "Solutions produites",
}
QUIET_EVENTS = {"pending_action.created", "research.query_run"}


def render_history(ctx: Ctx) -> None:
    topbar(ctx.user)
    show_flash()
    page_title("Historique", "Vos conversations et les actions enregistrées.")
    st.caption(
        "Limites : les messages ne sont pas horodatés un par un (la date indiquée est celle "
        "du dernier enregistrement de la conversation) ; le journal ne contient que les "
        "actions enregistrées par l'application (projets, plans, tâches, préférences, "
        "recherches). Rien n'est reconstitué."
    )
    rows = _project_rows(ctx)
    section_title("Conversations")
    conversations = [r for r in rows if r["conversation"]["count"]]
    if not conversations:
        st.caption("Aucune conversation enregistrée.")
    for row in conversations:
        project, conversation = row["project"], row["conversation"]
        with st.container(key=f"card_conv_{project.id}"):
            text, action = st.columns([4, 1], vertical_alignment="center")
            with text:
                st.markdown(f"**{md_text(project.title)}**")
                saved_at = conversation["saved_at"]
                saved = (
                    local_time(datetime.fromisoformat(saved_at), ctx.prefs.display_timezone)
                    if saved_at
                    else "date inconnue"
                )
                st.caption(
                    f"{conversation['count']} message(s), dont {conversation['user_count']} "
                    f"de vous · dernier enregistrement : {saved}"
                )
                who = "Vous" if conversation["last_role"] == "user" else "Coach"
                preview = " ".join(conversation["last_text"].split())
                if len(preview) > 160:
                    preview = preview[:157] + "…"
                st.caption(f"{who} : {md_text(preview)}")
            with action:
                if st.button("Reprendre", key=f"history_open_{project.id}", width="stretch"):
                    go(PROJECT, project.id)
    section_title("Journal des actions")
    titles = {row["project"].id: row["project"].title for row in rows}
    show_all = st.toggle("Afficher aussi les détails techniques (propositions, requêtes)",
                         key="history_all")  # fmt: skip
    events = [
        e for e in reversed(ctx.app.coach.list_events(ctx.user_id))
        if show_all or e.type.value not in QUIET_EVENTS
    ]  # fmt: skip
    if not events:
        st.caption("Aucune action enregistrée.")
        return
    limit = st.session_state.get("history_limit", 30)
    lines = []
    for event in events[:limit]:
        label = EVENT_LABELS.get(event.type.value, event.type.value)
        where = titles.get(event.project_id or "", "")
        suffix = f" · {md_text(where)}" if where else ""
        lines.append(
            f"- {local_time(event.created_at, ctx.prefs.display_timezone)} · {label}{suffix}"
        )
    with st.container(key="card_journal"):
        st.markdown("\n".join(lines))
    if len(events) > limit and st.button("Afficher plus", key="history_more"):
        st.session_state.history_limit = limit + 30
        st.rerun()


# --- parametres ------------------------------------------------------------------------------
def render_settings(ctx: Ctx, models_panel: Any) -> None:
    topbar(ctx.user)
    show_flash()
    page_title("Paramètres", "La façon dont votre coach vous répond, et vos données.")
    prefs = ctx.prefs
    with st.container(key="card_prefs"):
        st.subheader("Préférences", anchor=False)
        st.caption("Ces réglages sont choisis par vous ; l'assistant ne les modifie jamais.")
        with st.form(f"prefs_{ctx.user_id}", border=False):
            lengths = [item.value for item in ResponseLength]
            cadences = [item.value for item in Cadence]
            length = st.selectbox(
                "Longueur des réponses",
                lengths,
                index=lengths.index(prefs.response_length.value),
                format_func=RESPONSE_LABELS.__getitem__,
            )
            visible = st.select_slider(
                "Nombre de prochaines actions affichées",
                options=[1, 2, 3],
                value=prefs.max_visible_tasks,
            )
            one_question = st.checkbox(
                "Une seule question à la fois", value=prefs.one_question_at_a_time
            )
            deadlines = st.checkbox("Utiliser des échéances", value=prefs.deadlines_enabled)
            cadence = st.selectbox(
                "Rythme de suivi",
                cadences,
                index=cadences.index(prefs.cadence.value),
                format_func=CADENCE_LABELS.__getitem__,
            )
            timezone = st.text_input(
                "Fuseau horaire (ex. Europe/Paris)", value=prefs.display_timezone
            )
            if st.form_submit_button("Enregistrer les préférences", key="save_prefs",
                                     type="primary"):  # fmt: skip
                saved = run_safely(
                    ctx.app.coach.update_preferences,
                    ctx.user_id,
                    response_length=length,
                    max_visible_tasks=visible,
                    one_question_at_a_time=one_question,
                    deadlines_enabled=deadlines,
                    cadence=cadence,
                    display_timezone=timezone,
                )
                if saved:
                    flash("success", "Préférences enregistrées.")
                st.rerun()
    with st.container(key="card_data"):
        st.subheader("Mes données", anchor=False)
        export_key = f"export_{ctx.user_id}"
        if st.button("Préparer l'export de mes données", key="prepare_export"):
            st.session_state[export_key] = json.dumps(
                ctx.app.data.export_user_data(ctx.user_id), ensure_ascii=False, indent=2
            )
        if st.session_state.get(export_key):
            st.download_button(
                "Télécharger l'export (JSON)",
                st.session_state[export_key],
                file_name="neurocoach-export.json",
                mime="application/json",
                key="download_export",
            )
        st.caption(
            "L'effacement supprime vos projets, tâches, conversations, recherches et "
            "préférences, après confirmation. Votre profil (prénom, nom, nom d'utilisateur) "
            "est conservé."
        )
        if st.button("Effacer toutes mes données…", key="delete_data"):
            run_safely(ctx.app.actions.request_user_data_deletion, ctx.user_id)
            st.rerun()
        account_action = ctx.app.actions.get_pending(ctx.user_id, None)
        if account_action:
            for line in describe_preview([Change(**c) for c in account_action.preview]):
                st.warning(line)
            left, right = st.columns(2)
            if left.button("Confirmer l'effacement définitif",
                           key=f"confirm_{account_action.id}", type="primary"):  # fmt: skip
                if run_safely(ctx.app.actions.confirm, ctx.user_id, account_action.id):
                    flash("success", "Toutes vos données ont été effacées.")
                st.session_state.pop(export_key, None)
                st.rerun()
            if right.button("Annuler l'effacement", key=f"cancel_{account_action.id}"):
                run_safely(ctx.app.actions.cancel, ctx.user_id, account_action.id)
                st.rerun()
    with st.expander("Réglages avancés"):
        models_panel()
        status = ctx.app.research.availability()
        mode = (
            "désactivée (aucune clé)" if not status["enabled"]
            else ("réelle" if status["real"] else "simulée (démonstration)")
        )  # fmt: skip
        st.caption(f"Recherche web : {mode}. Quotas gratuits protégés par un plafond local.")
        for service in status["services"]:
            if service["simulated"]:
                continue
            state = "quota atteint ce mois-ci" if service["exhausted"] else "actif"
            st.caption(
                f"{service['label']} : {state} ; {service['used_usd']:.3f} $ utilisés sur "
                f"{(service['monthly_cap_usd'] or 0):.2f} $ autorisés ce mois"
            )


# --- profil ----------------------------------------------------------------------------------
def render_profile(ctx: Ctx) -> None:
    topbar(ctx.user)
    show_flash()
    page_title("Mon profil")
    user = ctx.user
    with st.container(key="card_profile_view"):
        avatar, info = st.columns([1, 5], vertical_alignment="center")
        with avatar:
            st.html(
                '<span class="ne-avatar ne-large" aria-hidden="true">'
                f"{esc(initials(user.first_name, user.last_name, user.display_name))}</span>"
            )
        with info:
            st.markdown(f"**{md_text(user.display_name)}**")
            st.caption(
                f"Nom d'utilisateur : {md_text(user.username or '—')} · espace créé le "
                f"{local_time(user.created_at, ctx.prefs.display_timezone)}"
            )
    with st.container(key="card_profile_edit"):
        st.subheader("Modifier mon nom", anchor=False)
        with st.form("profile_edit", border=False):
            first = st.text_input("Prénom", value=user.first_name or "", max_chars=40,
                                  key="edit_first")  # fmt: skip
            last = st.text_input("Nom", value=user.last_name or "", max_chars=40,
                                 key="edit_last")  # fmt: skip
            saved = st.form_submit_button("Enregistrer", type="primary", key="profile_save")
        if saved:
            try:
                ctx.app.coach.update_profile(user.id, first, last)
            except DomainError as error:
                st.error(_error_text(error))
            else:
                flash("success", "Profil enregistré.")
                st.rerun()
        st.caption("Le nom d'utilisateur ne peut pas être modifié.")
    with st.container(key="card_profile_space"):
        st.subheader("Changer d'espace", anchor=False)
        st.caption(NOT_AUTH)
        if st.button("Quitter cet espace", key="leave_space", icon=":material/logout:"):
            close_space()
