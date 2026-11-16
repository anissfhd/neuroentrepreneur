"""Charte graphique de la refonte (D-76) : feuille de style et constantes.

Les couleurs de base sont dans ``.streamlit/config.toml`` (theme) ; cette feuille ajoute ce
que le theme ne couvre pas : cartes cliquables, navigation laterale, bulles de conversation,
largeur de lecture, marges. Aucune ressource externe n'est chargee.
"""

from __future__ import annotations

GREEN = "#238C6E"
GREEN_DARK = "#176B53"
TEXT = "#1F2937"
MUTED = "#6B7280"
BORDER = "#E5E7EB"
SOFT = "#F8F9FA"
ACTIVE = "#F1F3F5"

CSS = f"""
<style>
:root {{
  --ne-green: {GREEN}; --ne-green-dark: {GREEN_DARK}; --ne-green-soft: #E8F3EF;
  --ne-text: {TEXT}; --ne-muted: {MUTED}; --ne-border: {BORDER}; --ne-soft: {SOFT};
  --ne-active: {ACTIVE}; --ne-radius: 14px;
  --ne-shadow: 0 1px 2px rgba(16, 24, 40, .04), 0 1px 3px rgba(16, 24, 40, .06);
  --ne-shadow-hover: 0 4px 12px rgba(16, 24, 40, .08);
}}

/* Largeur confortable, peu d'espace perdu en haut de page */
[data-testid="stMainBlockContainer"] {{
  max-width: 1080px; padding-top: 1.25rem; padding-bottom: 7rem;
}}
header[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {{
  color: var(--ne-muted);
}}
h1, h2, h3 {{ color: var(--ne-text); letter-spacing: -0.01em; }}

/* Boutons : accent vert, survol vert fonce */
button[data-testid="stBaseButton-primary"] {{
  background: var(--ne-green); border-color: var(--ne-green); font-weight: 600;
}}
button[data-testid="stBaseButton-primary"]:hover {{
  background: var(--ne-green-dark); border-color: var(--ne-green-dark); color: #FFFFFF;
}}
button[data-testid="stBaseButton-secondary"]:hover {{
  border-color: var(--ne-green); color: var(--ne-green-dark);
}}
button[data-testid="stBaseButton-tertiary"] {{ color: var(--ne-green-dark); }}

/* Cartes : conteneurs bordes, coins arrondis, ombre tres discrete */
[data-testid="stVerticalBlock"][class*="st-key-card"],
[data-testid="stVerticalBlock"][class*="st-key-tile"] {{
  background: #FFFFFF; border: 1px solid var(--ne-border); border-radius: var(--ne-radius);
  box-shadow: var(--ne-shadow); padding: 1.1rem 1.25rem; gap: .5rem;
}}
[data-testid="stVerticalBlock"][class*="st-key-soft"] {{
  background: var(--ne-soft); border: 1px solid var(--ne-border);
  border-radius: var(--ne-radius); padding: 1rem 1.25rem; gap: .4rem;
}}

/* Grandes cartes cliquables du tableau de bord : tout le cadre est un bouton */
[data-testid="stVerticalBlock"][class*="st-key-tile"] {{
  position: relative; min-height: 168px; padding: 1.5rem; justify-content: flex-start;
  transition: border-color .15s ease, box-shadow .15s ease;
}}
[data-testid="stVerticalBlock"][class*="st-key-tile"]:hover {{
  border-color: var(--ne-green); box-shadow: var(--ne-shadow-hover);
}}
[data-testid="stVerticalBlock"][class*="st-key-tile"] [class*="st-key-go_"] {{
  position: absolute; inset: 0; margin: 0; z-index: 3; width: 100% !important;
  height: 100%;
}}
[data-testid="stVerticalBlock"][class*="st-key-tile"] [class*="st-key-go_"] div,
[data-testid="stVerticalBlock"][class*="st-key-tile"] [class*="st-key-go_"] button {{
  width: 100%; height: 100%; min-height: 100%;
}}
[data-testid="stVerticalBlock"][class*="st-key-tile"] [class*="st-key-go_"] button {{
  opacity: 0; cursor: pointer;
}}
[data-testid="stVerticalBlock"][class*="st-key-tile"] [data-testid="stHtml"] {{
  pointer-events: none;
}}
[data-testid="stVerticalBlock"][class*="st-key-tile"]:has(button:focus-visible) {{
  outline: 3px solid var(--ne-green); outline-offset: 2px;
}}
.ne-tile-icon {{
  display: inline-flex; align-items: center; justify-content: center; width: 48px;
  height: 48px; border-radius: 12px; background: var(--ne-green-soft); color: var(--ne-green);
  margin-bottom: .35rem;
}}
.ne-tile-icon img {{ width: 26px; height: 26px; }}
.ne-tile-title {{ font-size: 1.15rem; font-weight: 650; color: var(--ne-text); margin: 0; }}
.ne-tile-text {{ color: var(--ne-muted); margin: 0; }}

/* Barre du haut : marque a gauche, prenom et avatar a droite */
.ne-topbar {{
  display: flex; align-items: center; justify-content: space-between; gap: 1rem;
  padding: .25rem 0 .75rem; border-bottom: 1px solid var(--ne-border); margin-bottom: 1.25rem;
}}
.ne-brand {{
  display: flex; align-items: center; gap: .55rem; font-weight: 700; font-size: 1.05rem;
  color: var(--ne-text);
}}
.ne-brand img {{ width: min(235px, 100%); height: auto; display: block; }}
.ne-topbar .ne-brand {{ min-width: 0; }}
.ne-user {{ display: flex; align-items: center; gap: .6rem; color: var(--ne-text); }}
.ne-avatar {{
  display: inline-flex; align-items: center; justify-content: center; width: 34px;
  height: 34px; border-radius: 50%; background: var(--ne-green-soft); color: var(--ne-green-dark);
  font-weight: 650; font-size: .85rem; flex: none;
}}
.ne-avatar.ne-large {{ width: 64px; height: 64px; font-size: 1.35rem; }}

/* Titres de page */
.ne-hello {{ font-size: 1.9rem; font-weight: 700; color: var(--ne-text); margin: .25rem 0 0; }}
.ne-sub {{ color: var(--ne-muted); margin: .15rem 0 1.25rem; font-size: 1.02rem; }}
.ne-section {{
  font-size: 1.1rem; font-weight: 650; color: var(--ne-text); margin: 1.75rem 0 .6rem;
}}
.ne-muted {{ color: var(--ne-muted); }}
.ne-small {{ font-size: .88rem; }}

/* Badges d'etat (texte toujours ecrit en clair, jamais la couleur seule) */
.ne-badge {{
  display: inline-block; padding: .1rem .55rem; border-radius: 999px; font-size: .78rem;
  font-weight: 600; border: 1px solid var(--ne-border); background: var(--ne-soft);
  color: var(--ne-muted); white-space: nowrap;
}}
.ne-badge.ne-ok {{ background: var(--ne-green-soft); color: var(--ne-green-dark);
  border-color: #CFE6DE; }}
.ne-badge.ne-warn {{ background: #FFF7ED; color: #9A3412; border-color: #FED7AA; }}

/* Barre de progression verte et fine */
[data-testid="stProgress"] > div > div > div > div {{ background-color: var(--ne-green); }}
.ne-bar {{ height: 8px; border-radius: 999px; background: #EEF0F2; overflow: hidden; }}
.ne-bar > span {{ display: block; height: 100%; background: var(--ne-green); }}

/* Etats vides */
.ne-empty {{ text-align: center; padding: 2.25rem 1rem; color: var(--ne-muted); }}
.ne-empty .ne-tile-icon {{ margin: 0 auto .75rem; }}
.ne-empty-title {{ color: var(--ne-text); font-weight: 650; font-size: 1.05rem; }}

/* Bienvenue */
.ne-welcome {{ text-align: center; margin: 2.5rem auto 1.5rem; max-width: 680px; }}
.ne-welcome .ne-brand {{ justify-content: center; font-size: 1.2rem; margin-bottom: 1.25rem; }}
.ne-welcome h1 {{ font-size: 2rem; margin: 0 0 .5rem; }}
.ne-welcome p {{ color: var(--ne-muted); font-size: 1.05rem; margin: 0; }}

/* Conversation and composer share a single reading width. */
[data-testid="stMainBlockContainer"]:has(.ne-chat-head) {{
  max-width: 920px; padding-top: .9rem; padding-bottom: 1.5rem;
}}
[data-testid="stMainBlockContainer"]:has(.st-key-chat_landing) {{
  max-width: 870px; padding-top: clamp(5rem, 31dvh, 23rem); padding-bottom: 2rem;
}}
.st-key-chat_landing {{ gap: 1.4rem; }}
.ne-chat-landing-title {{
  text-align: center; margin: 0; padding: 0;
  font-size: clamp(1.45rem, 3.2vw, 2.2rem); font-weight: 650;
}}
.ne-title-word {{ display: inline-block; }}
[data-testid="stLayoutWrapper"]:has(> .st-key-chat_browser_controls) {{ display: none; }}
.st-key-conversation {{ gap: 1.55rem; padding: .55rem 0 1rem; }}
[data-testid="stChatMessage"] {{
  background: transparent; padding: 0; gap: .7rem; align-items: flex-start; min-width: 0;
}}
[data-testid="stChatMessageContent"] {{ min-width: 0; flex: 1; padding: .3rem .1rem 0; }}
[data-testid="stChatMessage"]:has(.ne-sr) > [data-testid*="Avatar"] {{ display: none; }}
[data-testid="stChatMessage"]:has(.ne-speaker-user) {{
  justify-content: flex-start; flex-direction: row-reverse;
}}
[data-testid="stChatMessage"]:has(.ne-speaker-user) [data-testid="stChatMessageContent"] {{
  flex: 0 1 auto; width: fit-content; max-width: 82%; margin: 0; background: #e8f2fb;
  color: #19364f; padding: .62rem 1rem; border: 0; border-radius: 23px;
}}
[data-testid="stChatMessageContent"] [data-testid="stMarkdownContainer"] {{
  overflow-wrap: anywhere;
}}
[data-testid="stChatMessageContent"] [data-testid="stMarkdownContainer"] p {{
  line-height: 1.62;
}}
[class*="st-key-edit_message_"] [data-testid="stPopoverButton"] {{
  min-height: 25px; padding: .1rem .3rem; border: 0; background: transparent;
  color: #64748b; box-shadow: none;
}}
[class*="st-key-edit_message_"] [data-testid="stPopoverButton"] > svg {{ display: none; }}
[data-testid="stChatMessageContent"] [data-testid="stMarkdownContainer"] table {{
  display: block; max-width: 100%; overflow-x: auto;
}}
[data-testid="stChatMessageAvatarCustom"] {{ border-radius: 9px; }}
.ne-sr {{
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden;
  clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
}}
[data-testid="stChatMessageContent"] [data-testid="stElementContainer"]:has(.ne-sr) {{
  position: absolute; width: 1px; height: 1px; overflow: hidden;
}}
.ne-chat-head {{
  display: flex; align-items: center; gap: .8rem; padding: .65rem 0 1rem;
  border-bottom: 1px solid var(--ne-border);
}}
.ne-chat-head img {{ width: 44px; height: 44px; flex: none; }}
.ne-chat-heading {{ flex: 1; min-width: 0; }}
.ne-chat-title {{ font-weight: 700; font-size: 1.19rem; margin: 0; padding: 0; }}
.ne-chat-sub {{ color: var(--ne-muted); margin: .18rem 0 0; font-size: .89rem;
  overflow-wrap: anywhere; }}
[data-testid="stBottomBlockContainer"] {{
  max-width: 920px; padding-bottom: max(1rem, env(safe-area-inset-bottom));
}}
[data-testid="stChatInput"] {{
  position: relative; background: #fff; border: 1px solid #cedfd6;
  border-radius: 30px; box-shadow: 0 5px 24px #153b3010;
  transition: border-color .18s, box-shadow .18s;
}}
[data-testid="stChatInput"]:focus-within {{
  border-color: #68a991; box-shadow: 0 0 0 3px #dcefe6, 0 5px 24px #153b3010;
}}
[data-testid="stChatInput"] > div:first-child {{
  background: transparent; border: 0; border-radius: inherit; box-shadow: none;
}}
[data-testid="stChatInput"] [data-baseweb="textarea"] {{
  border: 0; background: transparent; box-shadow: none;
}}
[data-testid="stChatInput"] textarea {{ padding: .48rem .5rem; background: transparent; }}
[data-testid="stChatInput"] button {{
  border-radius: 50%; transition: background-color .16s, transform .16s, color .16s;
}}
[data-testid="stChatInput"] button:not(:disabled):active {{ transform: scale(.91); }}
.ne-dictate {{
  display: inline-grid; place-items: center; flex: none; width: 36px; height: 36px;
  background: #e9f4ed; color: #155b4b; border: 0; cursor: pointer; margin: 0 .25rem;
}}
.ne-dictate svg {{ width: 19px; height: 19px; pointer-events: none; }}
.ne-dictate:hover:not(:disabled) {{ background: #d8eee3; }}
.ne-dictate:disabled {{ opacity: .45; cursor: default; }}
.ne-dictate[aria-pressed="true"] {{ color: #a02437; background: #fbe5e8; }}
.ne-dictation-status:not(:empty) {{
  position: absolute; bottom: calc(100% + .45rem); right: .5rem; z-index: 2;
  padding: .35rem .65rem; color: var(--ne-text); background: #edf5f0;
  border-radius: 12px; font-size: .78rem; max-width: calc(100% - 1rem);
}}
[data-testid="stChatInputSubmitButton"]:not(:disabled) {{
  background: var(--ne-green-dark); color: white;
}}
.ne-thinking {{ display: inline-flex; align-items: center; gap: .65rem; color: var(--ne-muted);
  padding: .35rem 0; font-size: .9rem; }}
.ne-thinking-dots {{ display: flex; gap: .24rem; color: var(--ne-green-dark); }}
.ne-thinking-dots i {{ width: .31rem; height: .31rem; border-radius: 50%;
  background: currentColor; animation: ne-pulse 1.1s ease-in-out infinite; }}
.ne-thinking-dots i:nth-child(2) {{ animation-delay: .14s; }}
.ne-thinking-dots i:nth-child(3) {{ animation-delay: .28s; }}
@keyframes ne-pulse {{ 0%, 70%, 100% {{ opacity: .34; }} 35% {{ opacity: 1; }} }}
@media (prefers-reduced-motion: reduce) {{ .ne-thinking-dots i {{ animation: none; }} }}

/* The recent list takes the available space; only that section scrolls. */
[data-testid="stSidebarUserContent"] {{
  display: flex; flex-direction: column; padding: 0 .75rem .7rem !important;
  flex: 1; min-height: 0; overflow: hidden;
}}
[data-testid="stSidebarContent"] {{
  position: relative; display: flex; flex-direction: column; height: 100dvh; overflow: hidden;
}}
[data-testid="stSidebarHeader"] {{
  position: absolute; top: .65rem; right: .6rem; z-index: 2; padding: 0; min-height: 0;
}}
.ne-side-brand {{ margin-top: .85rem; }}
@media (prefers-reduced-motion: reduce) {{
  [data-testid="stChatInput"], [data-testid="stChatInput"] button {{ transition: none; }}
}}
[data-testid="stSidebarUserContent"] > div {{
  display: flex; flex: 1; min-height: 0; flex-direction: column;
}}
[data-testid="stSidebarUserContent"] > div > [data-testid="stVerticalBlock"] {{
  flex: 1; min-height: 0; gap: .4rem;
}}
[data-testid="stSidebar"] .st-key-sidebar_main,
[data-testid="stSidebar"] .st-key-sidebar_bottom,
[data-testid="stSidebar"] .st-key-sidebar_recent {{ gap: .16rem; }}
[data-testid="stSidebar"] [data-testid="stLayoutWrapper"]:has(> .st-key-sidebar_recent) {{
  flex: 1 1 0; min-height: 0; overflow-y: auto; overscroll-behavior: contain;
  scrollbar-width: thin; padding: 2px;
}}
.ne-side-brand {{
  display: flex; align-items: center; gap: .55rem; font-weight: 740; font-size: .99rem;
  color: var(--ne-text); padding: .15rem .28rem .6rem; letter-spacing: -.025em;
}}
.ne-side-brand img {{ width: min(200px, calc(100% - 1.6rem)); height: auto; display: block; }}
.ne-sidebar-heading {{ color: var(--ne-muted); font-size: .73rem; font-weight: 650;
  margin: .85rem .55rem .2rem; padding: 0; }}
[data-testid="stSidebar"] :is([class*="st-key-nav_"], [class*="st-key-recent_"]) button {{
  justify-content: flex-start; width: 100%; min-height: 35px; padding: .33rem .55rem;
  border-radius: 8px; color: var(--ne-text); font-weight: 500; border: 0; background: transparent;
}}
[data-testid="stSidebar"] :is([class*="st-key-nav_"], [class*="st-key-recent_"]) button:hover {{
  background: #e9f0ec;
}}
[data-testid="stSidebar"] :is([class*="st-key-nav_on_"], [class*="st-key-recent_on_"]) button {{
  background: #dfeee6; font-weight: 650; color: #154f40;
}}
[data-testid="stSidebar"] :is([class*="st-key-nav_"], [class*="st-key-recent_"]) button p {{
  font-size: .89rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}}
[data-testid="stSidebar"] :is([class*="st-key-nav_"], [class*="st-key-recent_"]) button > div,
[data-testid="stSidebar"] :is([class*="st-key-nav_"], [class*="st-key-recent_"])
  button > div > span {{
  width: 100%; min-width: 0; justify-content: flex-start;
}}
[data-testid="stSidebar"] [class*="st-key-recent_"] button [data-testid="stMarkdownContainer"] {{
  min-width: 0; overflow: hidden; text-align: left;
}}
[data-testid="stSidebar"] [data-testid="stIconMaterial"] {{ font-size: 17px; }}
[data-testid="stSidebar"] .st-key-sidebar_bottom {{
  border-top: 1px solid var(--ne-border); padding-top: .55rem;
}}
@media (max-width: 640px) {{
  .ne-chat-head {{ gap: .6rem; flex-wrap: wrap; }}
  .ne-chat-head img {{ width: 36px; height: 36px; }}
  .ne-chat-title {{ font-size: 1.05rem; }}
  .ne-chat-head .ne-badge {{ margin-left: 2.95rem; margin-right: auto; }}
  .ne-chat-heading {{ flex-basis: calc(100% - 3rem); }}
  [data-testid="stChatMessage"] {{ gap: .5rem; }}
  [data-testid="stChatMessage"]:has(.ne-speaker-user) [data-testid="stChatMessageContent"] {{
    max-width: 90%;
  }}
}}
@media (max-height: 480px) {{
  [data-testid="stSidebarUserContent"] {{ overflow-y: auto; }}
  [data-testid="stSidebar"] [data-testid="stLayoutWrapper"]:has(> .st-key-sidebar_recent) {{
    flex: 1 0 5rem;
  }}
}}

/* Accueil et aperçu des projets */
[data-testid="stMainBlockContainer"]:has(.st-key-overview_summary) {{ max-width: 1400px; }}
[data-testid="stMainBlockContainer"]:has(.st-key-overview_home) {{
  padding: .8rem clamp(1rem, 3vw, 3rem) .75rem;
}}
.st-key-overview_home {{ gap: clamp(.45rem, 1.65dvh, 1.1rem); }}
.st-key-overview_account [data-testid="stPopoverButton"] {{
  border: 0; padding: 0; gap: .55rem; color: #472083; font-weight: 700;
  background: transparent;
}}
.st-key-overview_account [data-testid="stPopoverButton"] p {{
  display: grid; place-items: center; width: 39px; height: 39px;
  border-radius: 50%; background: #eae0fa; color: #472083;
}}
.ne-overview-hero {{ text-align: center; padding: .6rem 0 .35rem; color: #15122c; }}
.ne-overview-hero > span {{ color: #9e70ec; font-size: 3rem; line-height: 1.1; }}
.ne-overview-hero h1 {{ font-size: clamp(2rem, 4vw, 3.2rem); margin: .3rem 0; padding: 0; }}
.ne-overview-hero p {{ color: #615b74; font-size: clamp(1rem, 2vw, 1.4rem); }}
.st-key-overview_composer {{ max-width: 980px; margin: 0 auto 1.8rem; }}
.st-key-overview_composer [data-testid="stChatInput"] {{
  min-height: 100px; border-radius: 20px; border-color: #ddd5ed;
  box-shadow: 0 8px 24px #25104812; align-content: center;
}}
.st-key-overview_composer [data-testid="stChatInputSubmitButton"]:not(:disabled) {{
  background: #7543c2;
}}
.st-key-overview_summary {{ gap: 1.45rem; margin-bottom: 1.1rem; }}
.ne-overview-metric {{
  display: flex; align-items: center; gap: .95rem; padding: 1rem 1.15rem; min-height: 90px;
  border: 1px solid #e6e0ef; border-radius: 16px; background: #f8f6fc; color: #17132f;
}}
.ne-overview-metric strong {{ display: block; font-size: 1.85rem; line-height: 1.05; }}
.ne-overview-metric small, .ne-overview-empty small {{ display: block; color: #615b74; }}
.ne-overview-metric > span, .ne-overview-empty > span {{
  display: inline-grid; place-items: center; width: 48px; height: 48px; flex: none;
  border-radius: 14px; background: #ede6fa;
}}
.ne-overview-metric img, .ne-overview-empty img {{ filter: hue-rotate(120deg) saturate(1.5); }}
.st-key-overview_projects, .st-key-overview_tasks {{ min-height: 215px; }}
.st-key-overview_summary [data-testid="stSubheader"] {{ font-size: 1.2rem; }}
.st-key-overview_summary button {{ color: #52309a; }}
[class*="st-key-overview_row_"] {{ position: relative; }}
[class*="st-key-overview_row_"] [class*="st-key-resume_"] {{
  position: absolute; inset: 0; z-index: 1;
}}
[class*="st-key-overview_row_"] [class*="st-key-resume_"] button {{
  width: 100%; height: 100%; opacity: 0; cursor: pointer;
}}
[class*="st-key-overview_row_"]:hover {{ background: #f8f4ff; }}
[class*="st-key-overview_row_"]:has(button:focus-visible) {{ outline: 2px solid #7543c2; }}
.st-key-overview_summary .ne-badge {{ white-space: normal; background: #f1eafb; color: #52309a; }}
.st-key-overview_summary .ne-badge.ne-ok {{ background: #e5f5ed; color: #176b53; }}
.ne-overview-empty {{ text-align: center; padding: .65rem 0 1rem; }}
.ne-overview-empty strong {{ display: block; margin: .5rem 0 .2rem; }}
@media (min-width: 850px) and (max-height: 800px) {{
  .ne-overview-hero {{ padding: 0; }}
  .ne-overview-hero > span {{ font-size: 2.15rem; }}
  .ne-overview-hero h1 {{ font-size: clamp(1.85rem, 3vw, 2.6rem); margin: .15rem 0; }}
  .ne-overview-hero p {{ font-size: 1rem; margin-bottom: .2rem; }}
  .st-key-overview_composer {{ max-width: 79%; margin-bottom: .6rem; }}
  .st-key-overview_composer [data-testid="stChatInput"] {{ min-height: 78px; }}
  .st-key-overview_summary {{ gap: .9rem; margin-bottom: 0; }}
  .ne-overview-metric {{ min-height: 67px; padding: .55rem .9rem; }}
  .ne-overview-metric strong {{ font-size: 1.55rem; }}
  .ne-overview-metric > span, .ne-overview-empty > span {{ width: 38px; height: 38px; }}
  .st-key-overview_projects, .st-key-overview_tasks {{ min-height: 172px; gap: .35rem; }}
  [class*="st-key-overview_row_"] {{ gap: 0; }}
  .ne-overview-empty {{ padding: .2rem 0 .45rem; }}
}}
[data-testid="stAppViewContainer"]:has(.st-key-overview_summary) [data-testid="stSidebar"] {{
  background: #f5f3fa;
}}
[data-testid="stAppViewContainer"]:has(.st-key-overview_summary) .st-key-nav_on_accueil button,
[data-testid="stAppViewContainer"]:has(.st-key-overview_summary) .st-key-nav_on_projets button {{
  background: #e8dff9; color: #482380;
}}
.st-key-nav_on_taches button[data-testid="stBaseButton-tertiary"] {{
  background: #e8dff9 !important; color: #482380 !important;
}}
.st-key-nav_on_taches [data-testid="stIconMaterial"] {{ color: #482380 !important; }}
.st-key-tasks_tab [data-baseweb="tab-highlight"] {{ background-color: #7543c2 !important; }}
.st-key-tasks_tab [role="tab"][aria-selected="true"] {{ color: #52309a; }}
.st-key-card_empty_tasks .ne-tile-icon {{ background: #ede6fa; }}
.st-key-card_empty_tasks .ne-tile-icon img {{ filter: hue-rotate(120deg) saturate(1.5); }}

/* Onglets du projet */
[data-testid="stTabs"] button[role="tab"] p {{ font-size: .98rem; font-weight: 550; }}
[data-testid="stTabs"] [data-baseweb="tab-highlight"] {{ background-color: var(--ne-green); }}

/* Expandeurs et formulaires plus doux */
[data-testid="stExpander"] details {{ border-radius: 12px; border-color: var(--ne-border); }}
[data-testid="stForm"] {{ border-radius: var(--ne-radius); border-color: var(--ne-border); }}

/* Telephone : marges reduites, cartes empilees (colonnes natives) */
@media (max-width: 640px) {{
  [data-testid="stMainBlockContainer"] {{ padding-left: 1rem; padding-right: 1rem; }}
  .ne-hello {{ font-size: 1.55rem; }}
  .ne-topbar .ne-user-name {{ display: none; }}
  [data-testid="stVerticalBlock"][class*="st-key-tile"] {{ min-height: 140px; }}
}}
</style>
"""

ICONS = {
    "trend": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
        '<path d="m3 17 6-6 4 4 7-8m-6 0h6v6"/></svg>'
    ),
    "plus-circle": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<circle cx="12" cy="12" r="10"/><path d="M12 8v8M8 12h8"/></svg>'
    ),
    "folder-open": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<path d="m6 14 1.45-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.55 6a2 2 0 0 1-1.94 '
        "1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 "
        '0 0 1 2 2v2"/></svg>'
    ),
    "list-checks": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<path d="m3 17 2 2 4-4M3 7l2 2 4-4M13 6h8M13 12h8M13 18h8"/></svg>'
    ),
    "history": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>'
        '<path d="M12 7v5l4 2"/></svg>'
    ),
}
