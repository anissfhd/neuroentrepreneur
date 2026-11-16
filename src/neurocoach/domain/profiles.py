"""Profils locaux et titres proposes (refonte de l'interface, D-76).

Regles pures, sans acces a la base :

- un nom d'utilisateur est unique sans tenir compte des majuscules ni des espaces de bord
  (cle normalisee NFKC puis ``casefold``) ;
- prenom et nom sont des textes courts, sans chiffres ni symboles ;
- un titre de projet peut etre PROPOSE a partir de l'idee decrite, jamais enregistre sans
  le clic de l'utilisateur.

Le nom d'utilisateur identifie un espace local : ce n'est pas une authentification.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from neurocoach.domain.errors import DomainError, ErrorCode

USERNAME_MIN, USERNAME_MAX = 3, 30
NAME_MAX = 40
PLACEHOLDER_TITLE = "Nouveau projet"

_USERNAME = re.compile(r"^[\w.-]+$")
_NAME = re.compile(r"^[^\W\d_]+(?:[ '\u2019-][^\W\d_]+)*$")


@dataclass(frozen=True)
class ProfileInput:
    first_name: str
    last_name: str
    username: str
    username_key: str

    @property
    def display_name(self) -> str:
        return f"{self.first_name} {self.last_name}"[:NAME_MAX].strip()


def username_key(username: str) -> str:
    """Cle d'unicite : « Marie.D », « marie.d » et «  MARIE.D  » donnent la meme cle."""
    return unicodedata.normalize("NFKC", username).strip().casefold()


def _clean_name(value: str, label: str) -> str:
    text = " ".join(unicodedata.normalize("NFKC", value or "").split())
    if not text:
        raise DomainError(ErrorCode.VALIDATION_ERROR, f"Indiquez votre {label}.")
    if len(text) > NAME_MAX:
        raise DomainError(
            ErrorCode.VALIDATION_ERROR, f"Votre {label} doit faire au plus {NAME_MAX} caractères."
        )
    if not _NAME.match(text):
        raise DomainError(
            ErrorCode.VALIDATION_ERROR,
            f"Votre {label} ne peut contenir que des lettres, des espaces, des tirets ou des "
            "apostrophes.",
        )
    return text


def clean_username(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").strip()
    if len(text) < USERNAME_MIN or len(text) > USERNAME_MAX:
        raise DomainError(
            ErrorCode.VALIDATION_ERROR,
            f"Le nom d'utilisateur doit faire entre {USERNAME_MIN} et {USERNAME_MAX} caractères.",
        )
    if not _USERNAME.match(text):
        raise DomainError(
            ErrorCode.VALIDATION_ERROR,
            "Le nom d'utilisateur ne peut contenir que des lettres, des chiffres, des points, "
            "des tirets ou des traits bas, sans espace.",
        )
    return text


def validate_profile(first_name: str, last_name: str, username: str) -> ProfileInput:
    first = _clean_name(first_name, "prénom")
    last = _clean_name(last_name, "nom")
    name = clean_username(username)
    return ProfileInput(first, last, name, username_key(name))


def initials(first_name: str | None, last_name: str | None, fallback: str = "") -> str:
    letters = [part[0] for part in (first_name, last_name) if part]
    if not letters and fallback:
        letters = [fallback[0]]
    return "".join(letters).upper()[:2] or "?"


# --- titre propose a partir de l'idee -------------------------------------------------------

_LEAD = re.compile(
    r"^"
    r"(?:(?:alors|en fait|voil[àa]|donc)[\s,]+)?"
    r"(?:je\s+(?:veux|voudrais|souhaite|souhaiterais|r[êe]ve\s+de|pense|compte|aimerais|"
    r"vais|cherche\s+[àa])|j['\u2019](?:aimerais|ai\s+(?:envie|l['\u2019]id[ée]e|une\s+id[ée]e)"
    r"(?:\s+de)?|envisage)|mon\s+(?:id[ée]e|projet|r[êe]ve)(?:\s*:|\s+(?:est|serait|c['\u2019]est))|"
    r"l['\u2019]id[ée]e\s+(?:est|serait))?"
    r"[\s:,]*(?:de\s+|d['\u2019])?",
    re.IGNORECASE,
)
_VERB = re.compile(
    r"^(?:vendre|lancer|cr[ée]er|ouvrir|monter|d[ée]marrer|proposer|fabriquer|faire|"
    r"d[ée]velopper|cr[ée]er\s+et\s+vendre)\s+",
    re.IGNORECASE,
)
_ARTICLE = re.compile(
    r"^(?:(?:mon|ma|mes|une|un|des|du|de\s+la|de|la|le|les)\s+|(?:de\s+)?l['\u2019]\s*)",
    re.IGNORECASE,
)
_GREETING = re.compile(
    r"^(?:(?:bonjour|salut|hello|coucou|bon|ben|bah|euh|alors|voil[àa]|donc|en fait|"
    r"eh bien|bref)\b[\s,!.]*)+",
    re.IGNORECASE,
)
_PRONOUN = {"je", "j", "on", "nous", "il", "elle", "c", "ce", "ça", "ca"}
_CUT = re.compile(r"[.?!;:\n]|,\s*(?:mais|et|car|donc|parce)\b|\s+(?:mais|parce que|car)\s+")
_TRAILING = {
    "à", "a", "de", "du", "des", "et", "en", "pour", "avec", "sur", "dans", "au", "aux", "les",
    "la", "le", "un", "une", "mes", "mon", "ma", "ses", "son", "sa", "leur", "leurs", "par",
}  # fmt: skip


FALLBACK_TITLE = "Mon projet"
# Recette reelle du 11/11/2026 : « Propre business » etait propose pour des bougies. Un titre
# fait seulement de mots generiques n'est jamais propose quand le domaine est identifiable.
_GENERIC_WORDS = {
    "business", "projet", "projets", "entreprise", "idée", "idee", "activité", "activite",
    "marque", "société", "societe", "start-up", "startup", "boîte", "boite", "affaire",
    "propre", "petit", "petite", "nouveau", "nouvelle", "mon", "ma", "mes", "un", "une", "de",
    "d", "à", "a", "moi", "perso", "personnel", "personnelle", "truc", "chose", "commerce",
}  # fmt: skip
_GENERIC_HEAD = re.compile(
    r"^(?:(?:petite?s?|propre|nouvelle?|vraie?)\s+)*(?:marque|entreprise|soci[ée]t[ée]|"
    r"activit[ée]|boutique(?:\s+en\s+ligne)?|business|start-?up|micro-entreprise|affaire|"
    r"structure|projet)\s+(?:de|d['\u2019]|dans\s+(?:les?|la)|autour\s+(?:de|des|du))\s*",
    re.IGNORECASE,
)
_CITY_TAIL = re.compile(r"\s+(?:à|a|sur|en)\s+[A-ZÉ][\w\u2019'-]+$")
_AUDIENCE_TAIL = re.compile(
    r"\s+(?:à|a|pour|avec|chez|aupr[èe]s de)\s+(?:mes|mon|ma|nos|notre)\b.*$", re.I
)


def is_generic_title(title: str | None) -> bool:
    words = re.findall(r"[\w-]+", (title or "").lower())
    return not words or all(word in _GENERIC_WORDS for word in words)


def suggest_title(idea: str, max_words: int = 6) -> str:
    """Titre court PROPOSE (jamais enregistre sans confirmation) ; « Mon projet » a defaut."""
    text = " ".join((idea or "").split())
    text = _GREETING.sub("", text, count=1)
    text = _LEAD.sub("", text, count=1)
    text = _CUT.split(text, maxsplit=1)[0]
    text = _VERB.sub("", text, count=1)
    text = _ARTICLE.sub("", text, count=1).strip(" ,'\u2019\"«»")
    text = _GENERIC_HEAD.sub("", text, count=1)
    text = _ARTICLE.sub("", text, count=1).strip(" ,'\u2019\"«»")
    text = _CITY_TAIL.sub("", text)  # la ville est affichee a part
    text = _AUDIENCE_TAIL.sub("", text)
    words = text.split()[:max_words]
    while words and words[-1].lower() in _TRAILING:
        words.pop()
    title = " ".join(words)
    first = re.split(r"['\u2019]", words[0].lower())[0] if words else ""
    if len(title) < 3 or first in _PRONOUN or is_generic_title(title):
        return FALLBACK_TITLE
    return title[0].upper() + title[1:]


_PAIRS = (("(", ")"), ("[", "]"), ("«", "»"))
_UNDECIDED = re.compile(r"\b(à|a) (définir|preciser|préciser|trouver)\b|\?|\.\.\.|…", re.I)


def valid_title(proposed: str | None) -> str | None:
    """D-80 : titre propose par le modele, accepte seulement s'il est complet et concret
    (recette du 12/11/2026 : « Son propre business (offre et cible », coupe et generique)."""
    title = " ".join((proposed or "").split()).strip("\"' ")
    if title.startswith("«") and title.endswith("»"):
        title = title[1:-1].strip()
    if not 3 <= len(title) <= 60 or is_generic_title(title) or _UNDECIDED.search(title):
        return None
    if any(title.count(a) != title.count(b) for a, b in _PAIRS):
        return None
    return title


def compact_title(title: str) -> str:
    """Libellé court pour la conversation et la barre latérale."""
    if len(title.split()) <= 3:
        return title
    short = suggest_title(title, max_words=3)
    return short if short != FALLBACK_TITLE else " ".join(title.split()[:3])


def best_title(texts: list[str], proposed: str | None = None) -> str | None:
    """Titre le plus concret : celui du modele s'il n'est pas generique, sinon la premiere
    description precise parmi les messages de l'utilisateur. ``None`` si rien n'est concret."""
    candidate = " ".join((proposed or "").split()).strip("\u00ab\u00bb\"' ")
    if 3 <= len(candidate) <= 60 and not is_generic_title(candidate):
        return candidate
    for text in texts:
        title = suggest_title(text)
        if title != FALLBACK_TITLE:
            return title
    return None
