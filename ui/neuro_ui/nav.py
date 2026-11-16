"""Navigation (D-76) : pages, adresse de la page et barre laterale.

L'etat de navigation vit dans l'adresse (``?u=…&p=…&id=…``) : une actualisation garde la page
et l'espace ouverts. ``u`` est l'identifiant interne de l'espace local : ce n'est pas une
authentification, et l'adresse ne doit pas etre partagee.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import streamlit as st

from neuro_ui.components import brand_html, md_text
from neuro_ui.context import Ctx
from neurocoach.domain.profiles import compact_title

HOME, PROJECTS, TASKS, HISTORY, SETTINGS, PROFILE, PROJECT = (
    "accueil",
    "projets",
    "taches",
    "historique",
    "parametres",
    "profil",
    "projet",
)
MAIN_PAGES = (
    (HOME, "Accueil", ":material/home:"),
    (PROJECTS, "Mes projets", ":material/folder:"),
    (TASKS, "Mes tâches", ":material/checklist:"),
    (HISTORY, "Historique", ":material/history:"),
)
BOTTOM_PAGES = (
    (SETTINGS, "Paramètres", ":material/settings:"),
    (PROFILE, "Mon profil", ":material/person:"),
)
KNOWN = {name for name, _, _ in (*MAIN_PAGES, *BOTTOM_PAGES)} | {PROJECT}


@dataclass(frozen=True)
class Route:
    user_id: str | None
    page: str
    project_id: str | None


def current() -> Route:
    params = st.query_params
    page = params.get("p") or HOME
    if page not in KNOWN:
        page = HOME
    project_id = params.get("id") or None
    if page == PROJECT and not project_id:
        page = PROJECTS
    return Route(params.get("u") or None, page, project_id)


def go(page: str, project_id: str | None = None, *, rerun: bool = True) -> None:
    """Change de page en gardant l'espace ouvert ; l'adresse suit (actualisation sure)."""
    user = st.query_params.get("u")
    params = {"p": page}
    if user:
        params["u"] = user
    if project_id:
        params["id"] = project_id
    st.query_params.from_dict(params)
    if rerun:
        st.rerun()


def open_space(user_id: str) -> None:
    st.query_params.clear()
    st.query_params["u"] = user_id
    st.query_params["p"] = HOME
    st.rerun()


def close_space() -> None:
    st.query_params.clear()
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()


def _entry(page: str, label: str, icon: str, active: str) -> None:
    on = page == active or (page == PROJECTS and active == PROJECT)
    key = f"nav_on_{page}" if on else f"nav_{page}"
    st.button(
        label,
        key=key,
        icon=icon,
        type="tertiary",
        width="stretch",
        on_click=go,
        args=(page,),
        kwargs={"rerun": False},
    )


def sidebar(route: Route, ctx: Ctx) -> None:
    projects = ctx.app.coach.list_projects(ctx.user_id)
    activity = ctx.app.coach.last_activity(ctx.user_id)

    def last_seen(project):
        saved = ctx.agent.conversation_summary(ctx.user_id, project.id)["saved_at"]
        dates = [project.updated_at, activity.get(project.id)]
        if saved:
            dates.append(datetime.fromisoformat(saved))
        return max(date for date in dates if date is not None)

    with st.sidebar:
        st.html(brand_html("ne-side-brand"))
        with st.container(key="sidebar_main"):
            for page, label, icon in MAIN_PAGES:
                _entry(page, label, icon, route.page)
        st.html('<h2 class="ne-sidebar-heading">Conversations récentes</h2>')
        with st.container(key="sidebar_recent"):
            for project in sorted(projects, key=last_seen, reverse=True):
                selected = route.page == PROJECT and route.project_id == project.id
                prefix = "recent_on" if selected else "recent"
                st.button(
                    md_text(compact_title(project.title)),
                    key=f"{prefix}_{project.id}",
                    icon=":material/chat_bubble_outline:",
                    type="tertiary",
                    width="stretch",
                    on_click=go,
                    args=(PROJECT, project.id),
                    kwargs={"rerun": False},
                )
            if not projects:
                st.caption("Vos conversations apparaîtront ici.")
        with st.container(key="sidebar_bottom"):
            for page, label, icon in BOTTOM_PAGES:
                _entry(page, label, icon, route.page)
