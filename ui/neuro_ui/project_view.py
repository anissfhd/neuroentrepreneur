"""Interieur d'un projet (D-76) : en-tete de progression, puis Conversation | Plan et taches |
Recherche. Fonctionnement inchange : propositions confirmees par clic, statuts annulables,
recherche approuvee une fois par mission (R1 a R6)."""

from __future__ import annotations

from io import BytesIO
from typing import Any

import streamlit as st
import streamlit.components.v1 as components
from PIL import Image
from pydantic import ValidationError

from neuro_ui.components import (
    ASSETS,
    COACH_AVATAR,
    USER_AVATAR,
    badge,
    brand_mark,
    esc,
    flash,
    local_time,
    md_link,
    md_text,
    progress_bar,
    run_safely,
    show_flash,
    speaker,
)
from neuro_ui.context import Ctx
from neuro_ui.nav import PROJECTS, go
from neurocoach.application.formatting import (
    describe_dependencies,
    format_next_actions,
    format_phase_header,
    format_resume_message,
    format_status_change,
)
from neurocoach.application.research_format import (
    format_analysis,
    format_solutions,
    split_details,
)
from neurocoach.application.research_service import MissionRequest
from neurocoach.domain.errors import DomainError
from neurocoach.domain.models import (
    STATUS_LABELS,
    ActionType,
    Preferences,
    ResponseLength,
    Task,
    TaskStatus,
    validation_detail,
)
from neurocoach.domain.plans import Change, PlanEdits, ProjectSnapshot, TaskEdit
from neurocoach.domain.preview import describe_preview, format_date_fr
from neurocoach.domain.profiles import compact_title
from neurocoach.domain.progress import format_percent
from neurocoach.domain.research import (
    CATEGORY_LABELS,
    NATURE_LABELS,
    MissionStatus,
    ResearchCategory,
)
from neurocoach.domain.transitions import ALLOWED_TRANSITIONS

STATUS_ACTIONS = {
    TaskStatus.IN_PROGRESS: "Commencer",
    TaskStatus.DONE: "Marquer terminée",
    TaskStatus.TODO: "Remettre à faire",
}
MISSION_STATUS_LABELS = {
    MissionStatus.PROPOSED: "proposée, en attente de votre approbation",
    MissionStatus.APPROVED: "approuvée",
    MissionStatus.COMPLETED: "terminée",
    MissionStatus.PARTIAL: "terminée partiellement",
    MissionStatus.CANCELLED: "annulée",
    MissionStatus.EXPIRED: "expirée sans approbation",
    MissionStatus.SUPERSEDED: "remplacée par une extension",
}
NEW_PROJECT_PLACEHOLDER = "Décrivez votre idée ou votre objectif…"
CHAT_PLACEHOLDER = "Écrivez votre message…"


def project_state(project: Any, summary: Any, started: bool = False) -> tuple[str, str]:
    """Etat lisible du projet et sa tonalite (le texte porte l'information, pas la couleur).
    D-82 : « a commencer » selon les messages reellement echanges (l'idee n'est enregistree
    qu'une fois comprise par le coach, elle ne dit plus si la conversation a commence)."""
    if getattr(project, "paused_at", None) is not None:
        return "En pause", ""  # D-85
    if project.status.value == "draft":
        if project.title_pending and not project.idea and not started:
            return "Conversation à commencer", ""
        return "En préparation", ""
    if summary.total and summary.done == summary.total:
        return "Terminé", "ok"
    return "En cours", "ok"


def progress_text(summary: Any) -> str:
    word = "tâche terminée" if summary.done <= 1 else "tâches terminées"
    return f"{summary.done} {word} sur {summary.total}"


def progress_to(box: Any) -> Any:
    """Rappel de progression : met a jour l'encart d'etat et garde la liste des etapes."""

    def show(message: str) -> None:
        box.update(label=message)
        box.write(message)

    return show


# --- page du projet ---------------------------------------------------------------------
def render_project(ctx: Ctx, project_id: str) -> None:
    app, agent, user_id, prefs = ctx.app, ctx.agent, ctx.user_id, ctx.prefs
    try:
        project = app.coach.get_project(user_id, project_id)
    except DomainError:
        st.info("Ce projet n'existe plus ou n'appartient pas à cet espace.")
        if st.button("Voir mes projets", key="missing_back", type="primary"):
            go(PROJECTS)
        return
    welcomed = f"welcome_back_{project_id}"
    if welcomed not in st.session_state:
        # D-85 : une fois par ouverture (session) : resume de retour apres une pause ou une
        # longue absence, ecrit a partir de la base, jamais pendant une proposition.
        st.session_state[welcomed] = True
        agent.welcome_back(user_id, project_id)
    snapshot = app.coach.get_snapshot(user_id, project_id)
    summary = app.coach.get_progress(user_id, project_id)
    next_actions = app.coach.get_next_actions(user_id, project_id)
    pending = agent.pending_confirmation(user_id, project_id)
    db_pending = app.actions.get_pending(user_id, project_id)
    plan_pending = bool(pending and pending.get("kind") == "plan")
    missions = app.research.list_missions(user_id, project_id)
    new_chat = (
        project.title_pending
        and project.status.value == "draft"
        and not missions
        and not summary.total
    )

    started = agent.conversation_summary(user_id, project_id)["user_count"] > 0
    with st.container(key="chat_browser_controls"):
        components.html((ASSETS / "dictation.js.html").read_text(encoding="utf-8"), height=0)
    if (
        new_chat
        and not started
        and not pending
        and not db_pending
        and not st.session_state.get(f"send_{project_id}")
        and not st.session_state.get(f"retry_{project_id}")
    ):
        show_flash()
        with st.container(key="chat_landing"):
            st.html('<h1 class="ne-chat-landing-title">Quel est votre prochain projet ?</h1>')
            _chat_input(project_id, NEW_PROJECT_PLACEHOLDER)
            _image_preview(project_id)
        return
    state, tone = project_state(project, summary, started)
    _chat_input(project_id, NEW_PROJECT_PLACEHOLDER if project.title_pending else CHAT_PLACEHOLDER)
    show_flash()
    _chat_header(project.title, state, tone)
    if not new_chat:
        with st.expander("Aperçu et état du projet", expanded=project.paused_at is not None):
            _project_header(ctx, project, summary, next_actions, plan_pending, bool(pending))
    _status_feedback(ctx)
    if db_pending and db_pending.action_type is ActionType.PROJECT_DELETE and not pending:
        # Proposition creee hors conversation (suppression du projet) ; une proposition de la
        # conversation est, elle, affichee avec ses boutons dans l'onglet Conversation.
        render_deletion_confirmation(ctx, project, db_pending)

    if new_chat:
        render_conversation(ctx, project, pending)
    else:
        chat_tab, plan_tab, research_tab = st.tabs(
            ["Conversation", "Plan et tâches", "Recherche"], key="main_tab"
        )
        with chat_tab:
            render_conversation(ctx, project, pending)
        with plan_tab:
            render_plan(ctx, project, snapshot, summary, next_actions)
        with research_tab:
            render_research(ctx, project_id, prefs)


def _chat_header(title: str, state: str, tone: str) -> None:
    st.html(
        '<header class="ne-chat-head">'
        f'{brand_mark(44)}<div class="ne-chat-heading">'
        '<h1 class="ne-chat-title">Votre coach entrepreneurial</h1>'
        f'<p class="ne-chat-sub">{esc(compact_title(title))}</p></div>{badge(state, tone)}</header>'
    )


def _project_header(
    ctx: Ctx,
    project: Any,
    summary: Any,
    next_actions: Any,
    plan_pending: bool,
    pending: bool = False,
) -> None:
    with st.container(key="card_header"):
        st.markdown(
            format_resume_message(project, summary, next_actions, ctx.prefs.cadence, plan_pending)
        )
        if summary.total:
            progress_bar(
                summary.percent,
                f"Progression : {format_percent(summary.percent)} ({progress_text(summary)})",
            )
        if project.paused_at is not None:
            # D-85 : pause reelle, enregistree ; la reprise est un clic explicite et journalise.
            day = format_date_fr(project.paused_at.astimezone().date())
            said = (project.pause_note or "").strip().rstrip(".")
            note = f" Raison notée : « {said} »." if said else ""
            st.info(
                f"Projet en pause depuis le {day}.{note} Vos tâches et votre plan sont conservés."
            )
            if not pending and st.button("Reprendre le projet", key="resume_project"):
                run_safely(ctx.agent.resume_project, ctx.user_id, project.id)
                st.rerun()
        alert = ctx.app.coach.get_workload_alert(ctx.user_id, project.id)
        if alert:
            st.warning(alert.message)
        if ctx.prefs.deadlines_enabled and summary.overdue:
            st.warning("En retard : " + ", ".join(f"T{number}" for number in summary.overdue))


def _status_feedback(ctx: Ctx) -> None:
    chat_change = st.session_state.get("last_change")
    if chat_change and chat_change["task_id"] is None:
        # Changement de statut demande dans la conversation : retour en haut de page.
        st.success(chat_change["text"])
        if chat_change.get("event_id"):
            render_undo(ctx, chat_change)


def render_deletion_confirmation(ctx: Ctx, project: Any, db_pending: Any) -> None:
    """Proposition creee hors conversation (suppression du projet) : confirmation requise."""
    with st.container(key="card_delete"):
        st.subheader("Confirmation requise", anchor=False)
        lines = describe_preview([Change(**c) for c in db_pending.preview])
        st.markdown("\n".join(f"- {line}" for line in lines))
        left, right = st.columns(2)
        if left.button(
            "Confirmer la suppression", key=f"confirm_{db_pending.id}", type="primary"
        ) and run_safely(ctx.app.actions.confirm, ctx.user_id, db_pending.id):
            flash("success", f"Le projet « {project.title} » a été supprimé.")
            st.session_state.pop(f"export_{ctx.user_id}", None)  # export devenu obsolete
            go(PROJECTS)
        if right.button("Annuler", key=f"cancel_{db_pending.id}"):
            run_safely(ctx.app.actions.cancel, ctx.user_id, db_pending.id)
            st.rerun()


# --- conversation -----------------------------------------------------------------------
def render_conversation(ctx: Ctx, project: Any, pending: dict[str, Any] | None) -> None:
    with st.container(key="conversation"):
        _conversation_body(ctx, project, pending)
        _image_preview(project.id)
        text = st.session_state.pop(f"send_{project.id}", None)
        if text:
            message_id = st.session_state.pop(f"replace_{project.id}", None)
            send_message(ctx, project.id, text, message_id=message_id)


def _image_preview(project_id: str) -> None:
    key = f"image_{project_id}"
    if image := st.session_state.get(key):
        with st.container(key="card_image"):
            st.image(image[1], width=180)
            st.caption(f"{image[0]} · Aperçu de session. Le coach reçoit le texte seul.")
            st.button("Retirer l'image", on_click=st.session_state.pop, args=(key, None))


def _conversation_body(ctx: Ctx, project: Any, pending: dict[str, Any] | None) -> None:
    agent, user_id = ctx.agent, ctx.user_id
    history = agent.history(user_id, project.id, include_ids=True)
    replacing = st.session_state.get(f"replace_{project.id}")
    if replacing:
        index = next((i for i, item in enumerate(history) if item["id"] == replacing), len(history))
        history = history[:index]
    if not history:
        st.caption(
            "Décrivez votre idée en une ou deux phrases. Exemples : « Je veux vendre des bougies, "
            "par où commencer ? », « J'ai terminé T1 », « Où en suis-je ? »."
        )
    for message in history:
        avatar = USER_AVATAR if message["role"] == "user" else COACH_AVATAR
        with st.chat_message(message["role"], avatar=avatar):
            # D-82 : qui parle AVANT le message (recette : les libelles suivaient le texte, ce
            # qui inversait la lecture pour les lecteurs d'ecran et les copies de la page).
            speaker(message["role"])
            # La conversation reste lisible ; le detail (sources, analyse complete,
            # parametres d'une recherche) est replie, consultable en un clic.
            main, details = split_details(message["content"])
            st.markdown(main)
            if details:
                with st.expander("Détail"):
                    st.markdown(details)
            if message["role"] == "user" and not st.session_state.get(f"send_{project.id}"):
                _edit_message(project.id, message["id"], message["content"])
    if replacing:
        return
    _deadline_messages(ctx, project.id)
    _conversation_actions(ctx, project, pending)


@st.fragment(run_every=30)
def _deadline_messages(ctx: Ctx, project_id: str) -> None:
    for notice in reversed(ctx.app.coach.deadline_notices(ctx.user_id, project_id)):
        with st.chat_message("assistant", avatar=COACH_AVATAR):
            st.caption("Notification d'échéance")
            st.text(notice.payload["text"])


def _conversation_actions(ctx: Ctx, project: Any, pending: dict[str, Any] | None) -> None:
    agent, user_id = ctx.agent, ctx.user_id
    # R3 (D-70) : mission proposee dans la conversation. Rien n'est envoye sans ce clic.
    research_mission = agent.research_pending(user_id, project.id)
    if research_mission is not None:
        with st.container(key="card_research_go"):
            mode = "simulée" if research_mission.simulated else "web réelle"
            st.markdown(f"**Recherche {mode} proposée** : en attente de votre approbation.")
            # D-82 : ce que l'approbation autorise, visible au moment du consentement.
            queries = [line for line in research_mission.preview if line.startswith("Requête")]
            consent = [line for line in research_mission.preview if line not in queries]
            st.markdown("\n".join(f"- {line}" for line in consent))
            if queries:
                with st.expander(f"Requêtes envoyées ({len(queries)})"):
                    st.markdown("\n".join(f"- {line}" for line in queries))
            left, right = st.columns(2)
            if left.button(
                "Approuver et lancer", key=f"research_go_{research_mission.id}", type="primary"
            ):
                with st.status("Recherches en cours…", expanded=True) as running:
                    turn = run_safely(
                        agent.approve_research,
                        user_id,
                        project.id,
                        research_mission.id,
                        research_mission.scope_hash,
                        progress=progress_to(running),
                    )
                    running.update(label="Recherche terminée", state="complete")
                if turn and turn.notice:
                    flash("info", turn.notice)
                st.rerun()
            if right.button("Annuler la recherche", key=f"research_no_{research_mission.id}"):
                run_safely(agent.cancel_research, user_id, project.id, research_mission.id)
                st.rerun()
    if pending:
        render_pending(ctx, pending, project.id)
    _retry_card(ctx, project)


def _retry_card(ctx: Ctx, project: Any) -> None:
    """Apres une erreur du service de langage : renvoyer le meme message, sur demande."""
    text = st.session_state.get(f"retry_{project.id}")
    if not text:
        return
    with st.container(key="card_retry"):
        st.warning(
            "Le coach n'a pas pu répondre (service de langage indisponible ou réponse "
            "invalide). Aucune réponse n'a été inventée et vos données sont intactes."
        )
        st.button(
            "Réessayer",
            key="retry_send",
            type="primary",
            icon=":material/refresh:",
            on_click=queue_message,
            args=(project.id, text),
        )


def _edit_message(project_id: str, message_id: str, original: str) -> None:
    key = f"edit_message_{project_id}_{message_id}"
    with st.container(key=key), st.popover(":material/edit:", help="Modifier le message"):
        with st.form(f"form_{key}", border=False):
            revised = st.text_area("Modifier le message", value=original, max_chars=2000)
            submitted = st.form_submit_button("Enregistrer et relancer")
        if submitted:
            revised = revised.strip()
            if not revised or revised == original.strip():
                st.warning("Modifiez le message avant d'envoyer la correction.")
                return
            st.session_state[f"send_{project_id}"] = revised
            st.session_state[f"replace_{project_id}"] = message_id
            st.rerun()


def queue_message(project_id: str, text: str | None = None) -> None:
    if text is not None:
        st.session_state[f"send_{project_id}"] = text
        return
    draft = st.session_state.get("chat")
    if isinstance(draft, str):
        st.session_state[f"send_{project_id}"] = draft
    elif draft:
        if draft.files:
            image = draft.files[0]
            data = image.getvalue()
            try:
                with Image.open(BytesIO(data), formats=["PNG", "JPEG", "WEBP"]) as opened:
                    if opened.width * opened.height > 20_000_000:
                        raise ValueError("image trop grande")
                    opened.verify()
            except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
                flash("error", "Cette image est illisible ou dépasse les dimensions acceptées.")
            else:
                st.session_state[f"image_{project_id}"] = (image.name, data)
        if draft.text and draft.text.strip():
            st.session_state[f"send_{project_id}"] = draft.text


def _chat_input(project_id: str, placeholder: str) -> None:
    st.chat_input(
        placeholder,
        key="chat",
        disabled=bool(st.session_state.get(f"send_{project_id}")),
        accept_file=True,
        file_type=["png", "jpg", "jpeg", "webp"],
        max_upload_size=5,
        on_submit=queue_message,
        args=(project_id,),
    )


def send_message(ctx: Ctx, project_id: str, text: str, *, message_id: str | None = None) -> None:
    """Affiche le message, puis remplace l'attente par la réponse dans la même bulle."""
    st.session_state.pop(f"retry_{project_id}", None)
    with st.chat_message("user", avatar=USER_AVATAR):
        speaker("user")
        st.markdown(text)
    with st.chat_message("assistant", avatar=COACH_AVATAR):
        speaker("assistant")
        bubble = st.empty()
        bubble.html(
            '<div class="ne-thinking" role="status">'
            '<span class="ne-thinking-dots" aria-hidden="true"><i></i><i></i><i></i></span>'
            "Le coach réfléchit…</div>"
        )

        def on_delta(partial: str) -> None:
            if partial.strip():
                bubble.markdown(partial)

        turn = None
        try:
            if message_id:
                turn = run_safely(
                    ctx.agent.edit_message,
                    ctx.user_id,
                    project_id,
                    message_id,
                    text,
                    stream=on_delta,
                )
            else:
                turn = run_safely(
                    ctx.agent.send_message, ctx.user_id, project_id, text, stream=on_delta
                )
        finally:
            if not turn or not turn.reply:
                bubble.empty()
        if turn and turn.reply:
            main, _ = split_details(turn.reply)
            bubble.markdown(main)
    if (turn is None and message_id is None) or (turn and turn.error):
        # Erreur explicite (service indisponible, reponse invalide) : rien n'est invente ;
        # le message peut etre renvoye tel quel.
        st.session_state[f"retry_{project_id}"] = text
    if turn and not turn.error:
        project = ctx.app.coach.get_project(ctx.user_id, project_id)
        if project.title_pending:
            suggestion = ctx.agent.title_suggestion(ctx.user_id, project_id)
            if suggestion:
                run_safely(
                    ctx.app.coach.rename_project, ctx.user_id, project_id, compact_title(suggestion)
                )
    if turn and turn.notice:
        flash("info", turn.notice)
    if turn and turn.undo_event_id:
        st.session_state.last_change = {
            "task_id": None,
            "ref": "conversation",
            "event_id": turn.undo_event_id,
            "text": turn.reply or "",
        }
    st.rerun()


CARD_BUTTONS = {
    "plan": ("Accepter et ajouter ce plan à mes tâches", "Demander un changement"),
    "change": ("Accepter les modifications", "Demander un changement"),
    "tasks_done": ("Confirmer les tâches terminées", "Ce n'est pas ça"),
    "pause": ("Mettre en pause", "Continuer sans pause"),
    "resume": ("Reprendre le projet", "Rester en pause"),
}


def render_pending(ctx: Ctx, pending: dict[str, Any], project_id: str) -> None:
    """Proposition issue de la conversation : rien n'est ecrit avant le clic sur Confirmer."""
    action_id = pending["pending_action_id"]
    with st.container(key="card_pending"):
        st.subheader("Proposition en attente de votre accord", anchor=False)
        # D-84/D-85 : deux boutons par type de proposition (simulations 1 a 6).
        button, other = CARD_BUTTONS.get(pending.get("kind") or "change", CARD_BUTTONS["change"])
        st.caption(f"Rien n'est enregistré tant que vous n'avez pas cliqué sur « {button} ».")
        st.markdown("\n".join(f"- {line}" for line in pending.get("preview", [])))
        left, right = st.columns(2)
        if left.button(
            button,
            key=f"confirm_{action_id}",
            type="primary",
            help="Enregistre la proposition telle qu'elle est affichée.",
        ):
            turn = run_safely(ctx.agent.decide, ctx.user_id, project_id, action_id, "confirm")
            if turn and turn.notice:
                flash("info", turn.notice)
            st.rerun()
        # D-82 : « Demander un changement » met la proposition de cote (rien n'est
        # enregistre) et la conversation reprend pour la modifier ; les autres refus annulent.
        change = other == "Demander un changement"
        if right.button(
            other,
            key=f"cancel_{action_id}",
            help="N'enregistre rien"
            + (" ; dites ensuite au coach ce que vous voulez changer." if change else "."),
        ):
            reason = {"reason": "change"} if change else {}
            run_safely(ctx.agent.decide, ctx.user_id, project_id, action_id, "cancel", **reason)
            st.rerun()
        if pending.get("kind") == "plan":
            with st.expander("Modifier la proposition avant de confirmer"):
                render_plan_editor(ctx, action_id, project_id)


def render_plan_editor(ctx: Ctx, action_id: str, project_id: str) -> None:
    view = run_safely(ctx.app.actions.plan_draft_view, ctx.user_id, action_id) or []
    with st.form(f"edit_{action_id}"):
        phase_titles: dict[str, str] = {}
        task_edits: dict[str, dict[str, Any]] = {}
        number = 0
        for index, phase in enumerate(view, start=1):
            # Libelles uniques : un lecteur d'ecran distingue chaque champ (verification visuelle).
            value = st.text_input(
                f"Titre de la phase {index}", value=phase["title"], key=f"edit_phase_{phase['key']}"
            )
            if value != phase["title"]:
                phase_titles[phase["key"]] = value
            for task in phase["tasks"]:
                number += 1
                key = task["key"]
                st.markdown(f"**Tâche {number} : {task['title']}**")
                title = st.text_input(
                    f"Titre de la tâche {number}", value=task["title"], key=f"edit_title_{key}"
                )
                criteria = st.text_input(
                    f"Critère de fin de la tâche {number}",
                    value=task["acceptance_criteria"],
                    key=f"edit_criteria_{key}",
                )
                remove = st.checkbox(
                    f"Retirer la tâche {number} « {task['title']} »", key=f"edit_remove_{key}"
                )
                edit: dict[str, Any] = {}
                if title != task["title"]:
                    edit["title"] = title
                if criteria != task["acceptance_criteria"]:
                    edit["acceptance_criteria"] = criteria
                if remove:
                    edit["remove"] = True
                if edit:
                    task_edits[key] = edit
        if st.form_submit_button("Mettre à jour la proposition", key="revise_submit"):
            try:
                edits = PlanEdits(
                    phase_titles=phase_titles,
                    tasks={key: TaskEdit(**edit) for key, edit in task_edits.items()},
                )
            except ValidationError as error:
                flash("error", f"Modification impossible : {validation_detail(error)}")
                st.rerun()
            if edits.phase_titles or edits.tasks:
                run_safely(ctx.agent.revise_plan, ctx.user_id, project_id, action_id, edits)
            else:
                flash("info", "Aucune modification à appliquer.")
            st.rerun()


# --- plan et taches ---------------------------------------------------------------------
def render_plan(
    ctx: Ctx, project: Any, snapshot: ProjectSnapshot, summary: Any, next_actions: Any
) -> None:
    prefs = ctx.prefs
    st.subheader("Prochaines actions", anchor=False)
    st.caption(f"Affichage limité à {prefs.max_visible_tasks} action(s), selon vos préférences.")
    st.markdown(format_next_actions(next_actions))
    if summary.total:
        st.subheader("Plan par phase", anchor=False)
        expanded = prefs.response_length is not ResponseLength.COURT and prefs.max_visible_tasks > 1
        for phase in summary.phases:
            with st.expander(format_phase_header(phase), expanded=expanded):
                for task in snapshot.phase_tasks(phase.phase_id):
                    render_task(ctx, task, snapshot, prefs)
    with st.expander("Options du projet"):
        st.caption(
            "La suppression efface le plan, les tâches, la conversation et les recherches de ce "
            "projet, après une confirmation."
        )
        if st.button("Supprimer ce projet…", key="delete_project"):
            run_safely(ctx.app.actions.request_project_deletion, ctx.user_id, project.id)
            st.rerun()


def render_task(ctx: Ctx, task: Task, snapshot: ProjectSnapshot, prefs: Preferences) -> None:
    with st.container(border=True):
        st.markdown(f"**{task.ref} · {task.title}**  \nStatut : **{STATUS_LABELS[task.status]}**")
        if prefs.response_length is not ResponseLength.COURT:
            st.caption(f"Critère de fin : {task.acceptance_criteria}")
        dependencies = describe_dependencies(task, snapshot)
        if dependencies:
            st.caption(f"Dépendances : {dependencies}")
        if prefs.deadlines_enabled and task.due_date:
            st.caption(f"Échéance : {format_date_fr(task.due_date)}")
        if task.blocked_reason:
            st.warning(f"Blocage : {task.blocked_reason}")
        targets = [s for s in STATUS_ACTIONS if (task.status, s) in ALLOWED_TRANSITIONS]
        if task.status is TaskStatus.DONE:
            targets = [TaskStatus.TODO]  # une seule action claire : « Rouvrir »
        for column, status in zip(st.columns(len(targets) or 1), targets, strict=False):
            label = (
                "Rouvrir"
                if task.status is TaskStatus.DONE and status is TaskStatus.TODO
                else (STATUS_ACTIONS[status])
            )
            if column.button(
                f"{label} {task.ref}", key=f"status_{status.value}_{task.id}", width="stretch"
            ):
                change_status(ctx, task, status)
        can_block = (task.status, TaskStatus.BLOCKED) in ALLOWED_TRANSITIONS
        if st.session_state.get("reset_block") == task.id:
            # Referme le champ de blocage apres enregistrement. Retirer la cle ne suffit pas
            # (constate dans le navigateur) : la valeur est forcee avant creation du widget.
            st.session_state[f"block_toggle_{task.id}"] = False
            st.session_state[f"block_reason_{task.id}"] = ""
            st.session_state.pop("reset_block")
        if (can_block or task.status is TaskStatus.BLOCKED) and st.checkbox(
            f"Modifier la raison du blocage de {task.ref}"
            if task.status is TaskStatus.BLOCKED
            else f"Signaler un blocage sur {task.ref}",
            key=f"block_toggle_{task.id}",
        ):
            reason = st.text_input(
                "Raison du blocage (obligatoire)",
                key=f"block_reason_{task.id}",
                placeholder="Ex. : en attente d'un devis",
            )
            if st.button(f"Enregistrer le blocage de {task.ref}", key=f"block_submit_{task.id}"):
                if len(reason.strip()) < 3:
                    st.session_state.task_error = (
                        task.id,
                        "Indiquez une raison d'au moins 3 caractères.",
                    )
                    st.rerun()
                st.session_state.reset_block = task.id
                change_status(ctx, task, TaskStatus.BLOCKED, reason)
        # Retour affiche dans la carte de la tache, la ou l'action a eu lieu (accessibilite).
        error = st.session_state.get("task_error")
        if error and error[0] == task.id:
            st.error(error[1])
            st.session_state.pop("task_error")
        last = st.session_state.get("last_change")
        if last and last["task_id"] == task.id:
            st.success(last["text"])
            if last.get("event_id"):
                render_undo(ctx, last)


def render_undo(ctx: Ctx, last: dict[str, Any]) -> None:
    if st.button(f"Annuler ce changement ({last['ref']})", key="undo"):
        if run_safely(ctx.app.coach.undo_status_change, ctx.user_id, last["event_id"]):
            last = {**last, "event_id": None, "text": f"Changement annulé pour {last['ref']}."}
            st.session_state.last_change = last
        else:
            st.session_state.last_change = None
        st.rerun()


def change_status(ctx: Ctx, task: Task, status: TaskStatus, reason: str | None = None) -> None:
    try:
        change = ctx.app.coach.set_task_status(ctx.user_id, task.id, status, reason)
    except DomainError as error:
        st.session_state.task_error = (task.id, error.user_message)
    else:
        st.session_state.last_change = {
            "task_id": task.id,
            "ref": task.ref,
            "event_id": change.event_id,
            "text": format_status_change(change),
        }
    st.rerun()


# --- recherche (R1 a R6) ------------------------------------------------------------------
def render_research_status(status: dict[str, Any]) -> bool:
    if not status["enabled"]:
        st.info(
            "La recherche web n'est pas encore activée. Ajoutez une clé gratuite Tavily "
            "(`TAVILY_API_KEY`) et/ou Exa (`EXA_API_KEY`) dans votre fichier `.env` local, "
            "puis redémarrez l'application. Aucune clé n'est jamais affichée."
        )
        return False
    if not status["real"]:
        st.info(
            "Recherche **simulée** (mode démonstration) : les sources et les chiffres sont "
            "fictifs (domaines « .example »). Aucun service externe n'est appelé."
        )
        return True
    lines = []
    for service in status["services"]:
        if service["simulated"]:
            continue
        state = "suspendu ce mois-ci (quota atteint)" if service["exhausted"] else "actif"
        cap = service["monthly_cap_usd"] or 0
        lines.append(
            f"{service['label']} : {state} ; {service['used_usd']:.3f} $ utilisés sur "
            f"{cap:.2f} $ autorisés ce mois ({service['free_tier']})"
        )
    st.info(
        "Recherche web **réelle**. Rien n'est envoyé avant votre approbation de la mission ; "
        "les quotas gratuits sont protégés par un plafond local.\n\n"
        + "\n".join(f"- {line}" for line in lines)
    )
    return True


def render_research(ctx: Ctx, project_id: str, prefs: Preferences) -> None:
    """Business Researcher (D-68, D-69) : mission approuvee, puis recherches dans son
    perimetre. Aucune ecriture dans le plan ni les taches."""
    app, user_id = ctx.app, ctx.user_id
    status = app.research.availability()
    if not render_research_status(status):
        return
    simulated = not status["real"]
    unit = " (fictif)" if simulated else ""
    with (
        st.expander("Préparer une nouvelle mission de recherche", expanded=False),
        st.form(f"research_form_{project_id}", border=False),
    ):
        categories = st.multiselect(
            "Recherches à prévoir",
            options=list(ResearchCategory),
            default=list(ResearchCategory),
            format_func=lambda c: CATEGORY_LABELS[c],
        )
        markets = st.text_input(
            "Marché (pays), si le projet ne le précise pas",
            placeholder="Par exemple : France",
        )
        budget = st.number_input(
                f"Budget maximal de la mission ($){unit}",
                min_value=0.01, max_value=2.0, value=0.40, step=0.05,
            )  # fmt: skip
        submitted = st.form_submit_button("Préparer la mission")
    if submitted:
        try:
            request = MissionRequest(
                project_ids=[project_id],
                categories=categories,
                markets=[m.strip() for m in markets.split(",") if m.strip()],
                max_budget_usd=float(budget),
            )
        except ValidationError as exc:
            flash("error", validation_detail(exc))
            st.rerun()
        draft = run_safely(app.research.prepare_mission, user_id, request)
        if draft and draft.question:
            flash("info", draft.question)
        elif draft:
            run_safely(app.research.propose_mission, user_id, request)
        st.rerun()

    missions = app.research.list_missions(user_id, project_id)
    if not missions:
        st.caption(
            "Aucune mission de recherche pour ce projet. Demandez-la au coach dans la "
            "conversation (« Qui sont mes concurrents ? ») ou préparez-la ci-dessus."
        )
    for mission in reversed(missions[-3:]):
        _render_mission(ctx, project_id, prefs, mission)


def _render_mission(ctx: Ctx, project_id: str, prefs: Preferences, mission: Any) -> None:
    app, user_id = ctx.app, ctx.user_id
    status_label = MISSION_STATUS_LABELS[mission.status]
    mode = "simulée" if mission.simulated else "réelle"
    unit = " (fictif)" if mission.simulated else ""
    purpose = "solutions" if mission.scope.purpose == "solutions" else "marché"
    with st.container(key=f"card_mission_{mission.id}"):
        st.markdown(f"**Mission de recherche {mode}** ({purpose}) : {status_label}")
        if mission.status is MissionStatus.PROPOSED:
            st.markdown("Ce que vous approuvez :")
            st.markdown("\n".join(f"- {md_text(line)}" for line in mission.preview))
            st.caption(
                "Après approbation, les recherches de ce périmètre s'enchaînent sans "
                "nouvelle question. Tout élargissement demandera une nouvelle approbation. "
                "Proposition valable jusqu'au "
                + local_time(mission.expires_at, prefs.display_timezone)
                + "."
            )
            if st.button("Approuver la mission", key=f"approve_{mission.id}", type="primary"):
                if run_safely(
                    app.research.approve_mission, user_id, mission.id, mission.scope_hash
                ):
                    flash("success", "Mission approuvée.")
                st.rerun()
            if st.button("Annuler la mission", key=f"cancel_research_{mission.id}"):
                run_safely(app.research.cancel_mission, user_id, mission.id)
                st.rerun()
            return
        if mission.status is MissionStatus.APPROVED:
            st.caption(
                "Autorisation valable jusqu'au "
                f"{local_time(mission.valid_until, prefs.display_timezone)} ; "
                f"{mission.queries_used}/{mission.scope.max_queries} recherches, "
                f"{mission.spent_usd:.3f} $ sur {mission.scope.max_budget_usd:.2f} ${unit}."
            )
            if st.button("Lancer les recherches prévues", key=f"run_{mission.id}", type="primary"):
                with st.status("Recherches en cours…", expanded=True) as searching:
                    run_safely(
                        app.research.run_mission,
                        user_id,
                        mission.id,
                        progress=progress_to(searching),
                    )
                st.rerun()
            if st.button("Clore la mission", key=f"close_{mission.id}"):
                run_safely(app.research.close_mission, user_id, mission.id)
                st.rerun()
            if st.button("Retirer l'autorisation", key=f"revoke_{mission.id}"):
                run_safely(app.research.cancel_mission, user_id, mission.id)
                st.rerun()
        report = run_safely(app.research.mission_report, user_id, mission.id)
        if report is None or not report.queries:
            return
        _render_report(ctx, project_id, prefs, mission, report)


def _render_report(
    ctx: Ctx, project_id: str, prefs: Preferences, mission: Any, report: Any
) -> None:
    app, agent, user_id = ctx.app, ctx.agent, ctx.user_id
    failed = [q for q in report.queries if q.status == "failed"]
    if failed:
        st.warning(
            f"{len(failed)} recherche(s) n'ont pas abouti : "
            + " ; ".join(md_text(q.error or "erreur") for q in failed[:3])
        )
    sources = {s.id: s for s in report.sources}
    with st.expander("Résultats et avis clients", expanded=False):
        for category in report.categories:
            if not category.findings and not category.no_data:
                continue
            st.markdown(f"**{category.label.capitalize()}**")
            if category.no_data:
                st.markdown("- Aucune donnée fiable trouvée.")
            for finding in category.findings:
                flags = f" ; {', '.join(finding.flags)}" if finding.flags else ""
                cited = ", ".join(
                    md_link(sources[s].domain, sources[s].url)
                    for s in finding.source_ids
                    if s in sources
                )
                # Un constat tire d'une source simulee n'est jamais presente comme reel.
                nature = NATURE_LABELS[finding.nature]
                if "simulé" in finding.flags:
                    nature += " (SIMULÉ)"
                st.markdown(
                    f"- {nature} (confiance {finding.confidence}{md_text(flags)}) : "
                    f"{md_text(finding.statement)} Source : {cited or 'aucune'}"
                )
        if report.hypotheses:
            st.markdown("**Hypothèses à vérifier** : " + md_text(" ; ".join(report.hypotheses)))
    # R6 (D-73) : mission de solutions ; les solutions validees, ou leur calcul.
    if mission.scope.purpose == "solutions" and any(q.status == "done" for q in report.queries):
        plan = app.research.latest_solutions(user_id, mission.id)
        if plan is not None:
            with st.expander("Solutions trouvées", expanded=False):
                st.markdown(format_solutions(plan, report.sources))
        elif st.button("Proposer les solutions", key=f"solve_{mission.id}"):
            with st.status("Recherche des solutions…", expanded=True) as solving:
                run_safely(
                    agent.solve_research, user_id, project_id, mission.id,
                    progress=progress_to(solving),
                )  # fmt: skip
            st.rerun()
    # R4 (D-71) : analyse par le modele de strategie, validee contre les sources.
    elif any(q.status == "done" for q in report.queries):
        analysis = app.research.latest_analysis(user_id, mission.id)
        if analysis is not None:
            with st.expander("Analyse du coach", expanded=False):
                st.markdown(format_analysis(analysis, report.sources))
                removed = [r for idea in analysis.ideas for r in idea.removed]
                if removed:
                    st.caption(
                        "Retiré ou requalifié par le contrôle des sources : "
                        + " ; ".join(md_text(r) for r in removed[:12])
                    )
        label = "Mettre à jour l'analyse" if analysis else "Analyser ces résultats"
        if st.button(label, key=f"analyze_{mission.id}"):
            with st.status("Analyse en cours…", expanded=True) as analysing:
                run_safely(
                    agent.analyze_research,
                    user_id,
                    project_id,
                    mission.id,
                    force=analysis is not None,
                    progress=progress_to(analysing),
                )
            st.rerun()
    with st.expander(f"Sources ({len(report.sources)})"):
        for source in report.sources:
            published = (
                source.published_date.strftime("%d/%m/%Y")
                if source.published_date
                else "date inconnue"
            )
            prefix = "[SIMULÉ] " if source.simulated else ""
            text = source.excerpt or source.title
            st.markdown(
                f"- {prefix}{md_link(source.title or source.domain, source.url)} "
                f"({md_text(source.domain)}, {published}, collecté le "
                f"{local_time(source.retrieved_at, prefs.display_timezone)}) : "
                f"{md_text(text)}"
            )
