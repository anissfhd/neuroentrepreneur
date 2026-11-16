"""Elements d'interface reutilises par les pages (D-76) : barre du haut, cartes, badges.

Tout texte venu de l'utilisateur ou du Web est echappe avant d'etre place dans du HTML.
"""

from __future__ import annotations

import base64
import html
import re
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import streamlit as st

from neuro_ui.theme import CSS, GREEN, ICONS
from neurocoach.domain.profiles import initials

ASSETS = Path(__file__).resolve().parents[1] / "assets"
COACH_AVATAR = str(ASSETS / "coach.png")
USER_AVATAR = str(ASSETS / "user.svg")
BRAND_IMAGE = base64.b64encode((ASSETS / "neuroentrepreneur.png").read_bytes()).decode("ascii")
COACH_IMAGE = base64.b64encode((ASSETS / "coach.png").read_bytes()).decode("ascii")

# Caracteres actifs en Markdown Streamlit : liens et images ([ ] !), emphase, code, HTML,
# tableaux, titres et formules ($ ... $ est rendu en LaTeX).
_MD_SPECIAL = re.compile(r"([\\`*_\[\]!<>|#~$])")


def inject_theme() -> None:
    st.html(CSS)


def speaker(role: str) -> None:
    """Qui parle, pour les lecteurs d'ecran (les avatars sont decoratifs)."""
    label = "Vous" if role == "user" else "Votre coach"
    st.html(f'<span class="ne-sr ne-speaker-{role}">{label} :</span>')


def svg_img(svg: str, size: int, css_class: str = "") -> str:
    """Icone SVG en image (le HTML insere est filtre : le SVG en ligne serait retire).
    Decorative : texte alternatif vide, le libelle voisin porte le sens."""
    markup = svg.replace("currentColor", GREEN)
    if "xmlns=" not in markup:
        markup = markup.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1)
    data = base64.b64encode(markup.encode("utf-8")).decode("ascii")
    return (
        f'<img class="{css_class}" src="data:image/svg+xml;base64,{data}" width="{size}" '
        f'height="{size}" alt="" />'
    )


def icon(name: str, size: int = 26) -> str:
    return svg_img(ICONS[name], size)


def esc(text: Any) -> str:
    return html.escape(str(text or ""), quote=True)


def md_text(text: str) -> str:
    """Texte venu du Web affiche tel quel : aucun lien, image ni mise en forme interpretes
    (une image Markdown chargerait une adresse externe a l'affichage)."""
    return _MD_SPECIAL.sub(r"\\\1", " ".join((text or "").split()))


def md_link(label: str, url: str) -> str:
    if not re.match(r"^https?://[^\s()<>]+$", url or ""):
        return md_text(label)
    return f"[{md_text(label)}]({url})"


def local_time(value: Any, timezone: str) -> str:
    return value.astimezone(ZoneInfo(timezone)).strftime("%d/%m/%Y %H:%M")


def brand_html(css_class: str = "ne-brand") -> str:
    return (
        f'<div class="{css_class}"><img src="data:image/png;base64,{BRAND_IMAGE}" '
        'alt="NeuroEntrepreneur AI Coach" /></div>'
    )


def brand_mark(size: int) -> str:
    return (
        f'<img src="data:image/png;base64,{COACH_IMAGE}" width="{size}" height="{size}" alt="" />'
    )


def topbar(user: Any) -> None:
    """Marque a gauche ; prenom et avatar discret a droite."""
    first = user.first_name or user.display_name
    st.html(
        '<div class="ne-topbar">'
        f"{brand_html()}"
        '<div class="ne-user">'
        f'<span class="ne-user-name">{esc(first)}</span>'
        f'<span class="ne-avatar" aria-hidden="true">'
        f"{esc(initials(user.first_name, user.last_name, user.display_name))}</span>"
        "</div></div>"
    )


def page_title(title: str, subtitle: str | None = None) -> None:
    st.html(
        f'<h1 class="ne-hello">{esc(title)}</h1>'
        + (f'<p class="ne-sub">{esc(subtitle)}</p>' if subtitle else "")
    )


def section_title(text: str) -> None:
    st.html(f'<h2 class="ne-section">{esc(text)}</h2>')


def badge(text: str, tone: str = "") -> str:
    tone_class = {"ok": " ne-ok", "warn": " ne-warn"}.get(tone, "")
    return f'<span class="ne-badge{tone_class}">{esc(text)}</span>'


def progress_bar(percent: float | None, label: str) -> None:
    """Barre verte native (lue par les lecteurs d'ecran avec son texte)."""
    st.progress(max(0.0, min(1.0, float(percent or 0) / 100)), text=label)


def empty_state(icon_name: str, title: str, text: str) -> None:
    icon_html = icon(icon_name)
    st.html(
        '<div class="ne-empty">'
        f'<span class="ne-tile-icon">{icon_html}</span>'
        f'<div class="ne-empty-title">{esc(title)}</div>'
        f'<p class="ne-muted">{esc(text)}</p></div>'
    )


def action_tile(key: str, icon_name: str, title: str, text: str) -> bool:
    """Grande carte cliquable : tout le cadre est un vrai bouton (clavier compris)."""
    icon_html = icon(icon_name)
    with st.container(key=f"tile_{key}"):
        st.html(
            f'<span class="ne-tile-icon">{icon_html}</span>'
            f'<p class="ne-tile-title">{esc(title)}</p>'
            f'<p class="ne-tile-text">{esc(text)}</p>'
        )
        return st.button(title, key=f"go_{key}")


def flash(level: str, text: str) -> None:
    st.session_state.flash = (level, text)


def show_flash() -> None:
    message = st.session_state.pop("flash", None)
    if message:
        level, text = message
        getattr(st, level)(text)


def run_safely(action: Any, *args: Any, **kwargs: Any) -> Any:
    """Toute erreur metier devient un message comprehensible, jamais une trace technique."""
    from neurocoach.domain.errors import DomainError

    try:
        return action(*args, **kwargs)
    except DomainError as error:
        flash("error", error.user_message)
        return None
