"""Faits connus du projet, lus par le code dans TOUT ce que l'utilisateur a ecrit (D-77).

Recette manuelle reelle du 11/11/2026 : budget, temps, objectif et refus des echeances etaient
perdus quand la clarification ne s'executait pas, et le coach redemandait le temps disponible
alors qu'il etait connu. Ces faits sont extraits de facon deterministe (jamais inventes : seule
une phrase de l'utilisateur les fournit), reutilises a chaque tour et transmis au modele.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field

_NUMBER_WORDS = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7,
    "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "quinze": 15, "vingt": 20,
}  # fmt: skip
_NUM = (
    r"(\d+(?:[.,]\d+)?|un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|"
    r"quinze|vingt)"
)

_BUDGET = re.compile(
    rf"budget[^.\d]{{0,40}}?{_NUM}\s*(?:k\s*)?(?:€|euros?)|{_NUM}\s*(?:€|euros?)\s*(?:de budget|"
    r"maximum|max|au maximum|à investir|pour (?:démarrer|commencer|lancer))",
    re.IGNORECASE,
)
_WEEKLY = re.compile(
    rf"{_NUM}\s*(?:h|heures?)(?:\s*(?:\d+|et demie))?\s*(?:par|/|chaque|toutes les|dans la)\s*"
    r"semaines?",
    re.IGNORECASE,
)
_DAILY_MIN = re.compile(rf"{_NUM}\s*(?:min|minutes)\s*(?:par|/|chaque)\s*(?:jour|soir)", re.I)
_DAILY_HOURS = re.compile(
    rf"{_NUM}\s*(?:h|heures?)\s*(?:par|/|chaque)\s*(?:jour|soir)|une heure par jour", re.I
)
_HORIZON = re.compile(
    rf"(?:dans|d'ici|d\u2019ici|en|sous)\s+(?:les?\s+)?(?:{_NUM}\s+)?(prochains?\s+)?"
    r"(jours?|semaines?|mois|ans?)\b",
    re.IGNORECASE,
)
_CITY = re.compile(
    r"\b(?:à|a|sur|vers|autour de)\s+([A-ZÉÈÎÔ][\w\u2019'-]+(?:[- ][A-ZÉÈ][\w\u2019'-]+)?)"
)
_BEGINNER = re.compile(
    r"je d[ée]bute|d[ée]butant|d[ée]butante|aucune exp[ée]rience|pas d'exp[ée]rience|"
    r"jamais (?:fait|vendu|cr[ée][ée])|je n'y connais rien|je pars de z[ée]ro|novice",
    re.IGNORECASE,
)
_NO_DEADLINES = re.compile(
    r"(?:pas|aucune?|sans)\s+(?:de\s+)?(?:dates?\s*(?:limites?|butoirs?)?|[ée]ch[ée]ances?|"
    r"deadlines?|d[ée]lais? impos[ée]s?)|ne (?:veux|souhaite) pas (?:de |d')?(?:dates?|"
    r"[ée]ch[ée]ances?|deadlines?)",
    re.IGNORECASE,
)
_PROGRESSIVE = re.compile(
    r"progressivement|pas à pas|pas a pas|étape par étape|etape par etape|petit à petit|"
    r"à mon rythme|a mon rythme|doucement",
    re.IGNORECASE,
)
_OBJECTIVE = re.compile(
    r"(?:mon|notre)\s+objectif\s+(?:est|serait|c'est)\s+(?:de\s+|d'|d\u2019)?([^.!?\n]{4,200})|"
    r"objectif\s*:\s*([^.!?\n]{4,200})",
    re.IGNORECASE,
)
_SKIP = re.compile(
    r"\bje passe\b|\bje ne sais pas\b|\bje sais pas\b|aucune id[ée]e|peu importe|"
    r"\bpas de pr[ée]f[ée]rence|\bn'importe\b|on verra|\bpasse\b",
    re.IGNORECASE,
)
# Repartition du temps : jours de travail par semaine estimes a partir de la reponse.
_SCHEDULES = (
    (re.compile(r"\bweek-?ends?\b|\bsamedis?\b|\bdimanches?\b", re.I), "le week-end", 2),
    (
        re.compile(r"\b(?:le |les |en )?soir(?:s|ée|ées)?\b|apr[èe]s le travail", re.I),
        "en soirée",
        5,
    ),
    (re.compile(r"\btous les jours\b|\bchaque jour\b|\bquotidien", re.I), "chaque jour", 7),
    (
        re.compile(r"plusieurs (?:jours|journées)|\br[ée]parti|\ben semaine\b", re.I),
        "sur plusieurs journées",
        3,
    ),
    (re.compile(r"\bmatin(?:s|ées?)?\b|\bmidi\b|\bpause\b", re.I), "en journée", 5),
)
_WEEKDAYS = re.compile(r"\b(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)s?\b", re.I)
_NOT_CITIES = {
    "Je", "Mon", "Ma", "Mes", "Le", "La", "Les", "Un", "Une", "Pour", "Avec", "En", "Et",
    "Il", "Elle", "Nous", "Vous", "Quel", "Quelle", "Bonjour", "Merci", "Dans",
}  # fmt: skip


def _number(raw: str) -> float:
    raw = raw.lower()
    if raw in _NUMBER_WORDS:
        return float(_NUMBER_WORDS[raw])
    return float(raw.replace(",", "."))


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


@dataclass(frozen=True)
class KnownFacts:
    """Ce que l'utilisateur a dit lui-meme, et rien d'autre."""

    budget_eur: int | None = None
    budget_mad: float | None = None
    weekly_hours: float | None = None
    daily_minutes: int | None = None
    horizon_text: str | None = None
    horizon_days: int | None = None
    objective: str | None = None
    city: str | None = None
    beginner: bool = False
    no_deadlines: bool = False
    progressive: bool = False
    schedule: str | None = None
    schedule_days: int | None = None
    sources: dict[str, str] = field(default_factory=dict)  # fait -> phrase d'origine

    def session_minutes(self) -> int | None:
        """Duree d'une seance de travail : dite par l'utilisateur, ou deduite de ses heures
        par semaine et de sa repartition (a defaut, 5 jours : une hypothese, signalee)."""
        if self.daily_minutes:
            return self.daily_minutes
        if self.weekly_hours:
            days = self.schedule_days or 5
            return max(10, min(720, round(self.weekly_hours * 60 / days / 5) * 5))
        return None

    def as_facts(self) -> dict[str, object]:
        """Version transmise au modele (donnees, pas instructions)."""
        values: dict[str, object] = {
            "budget_eur": self.budget_eur,
            "budget_mad": self.budget_mad,
            "heures_par_semaine": self.weekly_hours,
            "minutes_par_jour": self.daily_minutes,
            "repartition": self.schedule,
            "minutes_par_seance": self.daily_minutes,
            "horizon": self.horizon_text,
            "objectif": self.objective,
            "ville": self.city,
            "debute": self.beginner or None,
            "sans_dates_limites": self.no_deadlines or None,
            "avancer_progressivement": self.progressive or None,
        }
        return {key: value for key, value in values.items() if value not in (None, "")}


def _horizon(match: re.Match[str]) -> tuple[str, int | None]:
    count_raw, _, unit = match.group(1), match.group(2), match.group(3).lower()
    count = _number(count_raw) if count_raw else 1
    per = 1 if unit.startswith("jour") else 7 if unit.startswith("semaine") else 30
    if unit.startswith("an"):
        per = 365
    return match.group(0).strip(), min(365, int(count * per))


def extract_known(texts: Iterable[str], *, asked_schedule: bool = False) -> KnownFacts:
    """Faits connus, du plus ancien au plus recent message (le plus recent l'emporte)."""
    values: dict[str, object] = {}
    sources: dict[str, str] = {}
    for raw in texts:
        text = _fold(raw)
        if not text.strip():
            continue
        if match := _BUDGET.search(text):
            amount = match.group(1) or match.group(2)
            multiplier = 1000 if re.search(r"\d\s*k\s*(?:€|euros?)", match.group(0), re.I) else 1
            values["budget_eur"] = int(_number(amount) * multiplier)
            values.pop("budget_mad", None)
            sources["budget"] = match.group(0)
        elif match := re.search(
            rf"(?:budget|maximum|au plus|investir)[^.?!]{{0,40}}?({_NUM})\s*(?:dh|mad)\b"
            rf"|({_NUM})\s*(?:dh|mad)\s*(?:maximum|au plus|de budget)\b",
            text,
        ):
            values["budget_mad"] = _number(match.group(1) or match.group(2))
            values.pop("budget_eur", None)
            sources["budget"] = match.group(0)
        elif match := re.search(r"\b(?:aucun budget|sans budget|budget nul|zero budget)\b", text):
            values["budget_eur"] = 0
            values.pop("budget_mad", None)
            sources["budget"] = match.group(0)
        weekly = _WEEKLY.search(text)
        daily = _DAILY_MIN.search(text) or _DAILY_HOURS.search(text)
        if weekly:
            values["weekly_hours"] = _number(weekly.group(1))
            sources["temps"] = weekly.group(0)
            if not daily:
                # D-87 : le temps dit en dernier l'emporte (« 30 minutes par jour », puis
                # « je n'ai plus que 2 heures par semaine »).
                values.pop("daily_minutes", None)
        if match := _DAILY_MIN.search(text):
            values["daily_minutes"] = int(_number(match.group(1)))
            sources["temps"] = match.group(0)
        elif match := _DAILY_HOURS.search(text):
            hours = _number(match.group(1)) if match.group(1) else 1
            values["daily_minutes"] = int(hours * 60)
            sources["temps"] = match.group(0)
        if daily and not weekly:
            values.pop("weekly_hours", None)
        if match := _OBJECTIVE.search(text):
            objective = (match.group(1) or match.group(2)).strip(" ,;:")
            values["objective"] = objective[0].upper() + objective[1:]
            if horizon := _HORIZON.search(objective):
                values["horizon_text"], values["horizon_days"] = _horizon(horizon)
        if "horizon_days" not in values and (horizon := _HORIZON.search(text)):
            values["horizon_text"], values["horizon_days"] = _horizon(horizon)
        for city in _CITY.findall(text):
            if city.split()[0] not in _NOT_CITIES and not _WEEKDAYS.fullmatch(city):
                values["city"] = city
                break
        if _BEGINNER.search(text):
            values["beginner"] = True
        if _NO_DEADLINES.search(text):
            values["no_deadlines"] = True
        if _PROGRESSIVE.search(text):
            values["progressive"] = True
        schedule = _schedule(text)
        if schedule:
            values["schedule"], values["schedule_days"] = schedule
        elif asked_schedule and _SKIP.search(text):
            values["schedule"], values["schedule_days"] = "non précisée", None
    return KnownFacts(**values, sources=sources)  # type: ignore[arg-type]


def _schedule(text: str) -> tuple[str, int] | None:
    days = {d.lower().rstrip("s") for d in _WEEKDAYS.findall(text)}
    if len(days) >= 2 and not {"samedi", "dimanche"} >= days:
        order = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
        return f"le {', le '.join(sorted(days, key=order.index))}", len(days)
    for pattern, label, count in _SCHEDULES:
        if pattern.search(text):
            return label, count
    return None


def recap(known: KnownFacts, idea_label: str | None) -> str:
    """Reformulation de ce que l'utilisateur a dit, sans rien ajouter."""
    parts = []
    if idea_label:
        where = f" à {known.city}" if known.city and known.city not in idea_label else ""
        parts.append(f"Vous souhaitez lancer : {idea_label}{where}")
    elif known.city:
        parts.append(f"Votre projet se situe à {known.city}")
    means = []
    if known.budget_eur:
        means.append(f"un budget de {known.budget_eur} €")
    if known.weekly_hours:
        hours = f"{known.weekly_hours:g}".replace(".", ",")
        means.append(f"environ {hours} heures par semaine")
    elif known.daily_minutes:
        means.append(f"environ {known.daily_minutes} minutes par jour")
    text = ""
    if parts:
        text = parts[0] + (f", avec {' et '.join(means)}" if means else "") + "."
    elif means:
        text = f"Vous disposez de {' et '.join(means)}."
    if known.beginner:
        text += " Vous débutez dans ce domaine."
    if known.objective:
        objective = second_person(known.objective[0].lower() + known.objective[1:])
        text += f" Votre objectif : {objective}."
    return text.strip()


_POSSESSIVES = {"mes": "vos", "mon": "votre", "ma": "votre", "me": "vous", "moi": "vous"}


def second_person(text: str) -> str:
    """« mes premières ventes » devient « vos premières ventes » dans une reformulation."""
    return re.sub(
        r"\b(mes|mon|ma|me|moi)\b", lambda m: _POSSESSIVES[m.group(1).lower()], text, flags=re.I
    )
