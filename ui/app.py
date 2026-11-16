"""Interface Streamlit de NeuroEntrepreneur (refonte D-76).

Parcours : profil local -> accueil -> projet par la conversation -> plan, taches, recherche.
L'interface n'accede jamais a SQL : elle passe par le lanceur du graphe et par les services
applicatifs. Le coach reste le vrai modele configure (aucune reponse simulee ajoutee) ; le
message d'accueil d'un nouveau projet est un texte fixe, sans appel au modele.

Prototype local : un nom d'utilisateur ouvre un espace, ce n'est pas une authentification
(R-SEC-01). Accessibilite : composants natifs (navigables au clavier), libelles explicites,
statuts ecrits en toutes lettres, aucune information portee par la seule couleur.
Lancement : python scripts/dev.py demo
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from neuro_ui import nav
from neuro_ui.components import COACH_AVATAR, inject_theme
from neuro_ui.context import Ctx
from neuro_ui.project_view import render_project
from neuro_ui.screens import (
    render_dashboard,
    render_history,
    render_profile,
    render_projects,
    render_settings,
    render_tasks,
    render_welcome,
)

from neurocoach.bootstrap import CoachRuntime, build_coach_runtime
from neurocoach.config import Settings
from neurocoach.llm_catalog import RESTART_MESSAGE, loaded_lines, pending_changes

st.set_page_config(
    page_title="NeuroEntrepreneur",
    page_icon=COACH_AVATAR,
    layout="wide",
    initial_sidebar_state="auto",
)


def close_runtime(runtime: CoachRuntime) -> None:
    runtime.checkpointer.conn.close()


@st.cache_resource(show_spinner=False, on_release=close_runtime)
def get_runtime(data_dir: str) -> CoachRuntime:
    """Une instance par dossier de donnees, construite au demarrage.

    M3 : le fournisseur et le modele ne font plus partie de la cle. Avant, changer de
    fournisseur reconstruisait l'execution en silence, et changer de modele n'avait aucun
    effet visible. Desormais, un changement de configuration n'est jamais applique en cours
    de session : il est signale, et prend effet au redemarrage.

    D-76 : aucune donnee de demonstration n'est creee a l'ouverture (``dev.py seed`` reste
    disponible) ; un nouvel utilisateur ne voit jamais un projet fictif."""
    return build_coach_runtime(Settings.from_env())


settings = Settings.from_env()
runtime = get_runtime(str(settings.data_dir.resolve()))
app = runtime.app
# M3 : configuration demandee (.env, environnement) comparee a celle reellement chargee.
changes = pending_changes(runtime.llm_config, settings) if runtime.llm_config else []


def models_panel() -> None:
    """Reglages avances : modeles reellement charges (M3), sans aucune cle."""
    if runtime.llm_config:
        with st.expander("Modèles IA chargés"):
            for line in loaded_lines(runtime.llm_config):
                st.caption(line)
            if not changes:
                st.caption("Configuration demandée : identique à la configuration chargée.")


inject_theme()
if changes:
    st.warning(RESTART_MESSAGE + "\n\n" + "\n".join(f"- {line}" for line in changes))

route = nav.current()
user = app.coach.get_user(route.user_id) if route.user_id else None
if user is None:
    # Premiere ouverture (ou espace inconnu) : creation du profil, sans projet fictif.
    render_welcome(app)
    st.stop()

ctx = Ctx(runtime, settings, changes, user, app.coach.get_preferences(user.id))
if ctx.prefs.deadlines_enabled:
    app.coach.check_deadlines(user.id)
nav.sidebar(route, ctx)


@st.fragment(run_every=30)
def notifications() -> None:
    if ctx.prefs.deadlines_enabled:
        app.coach.check_deadlines(user.id)
    notices = app.coach.deadline_notices(user.id)
    with st.popover("Notifications", icon=":material/notifications:"):
        if not notices:
            st.caption("Aucune notification pour le moment.")
        for notice in notices[:20]:
            st.write(notice.payload["text"])
            if notice.project_id and st.button("Ouvrir le projet", key=f"notice_{notice.id}"):
                nav.go(nav.PROJECT, notice.project_id)


notifications()
if route.page == nav.PROJECT and route.project_id:
    render_project(ctx, route.project_id)
elif route.page == nav.PROJECTS:
    render_projects(ctx)
elif route.page == nav.TASKS:
    render_tasks(ctx)
elif route.page == nav.HISTORY:
    render_history(ctx)
elif route.page == nav.SETTINGS:
    render_settings(ctx, models_panel)
elif route.page == nav.PROFILE:
    render_profile(ctx)
else:
    render_dashboard(ctx)
