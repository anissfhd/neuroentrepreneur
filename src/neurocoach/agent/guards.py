"""Garde-fous deterministes appliques aux sorties du LLM (deuxieme campagne reelle, D-56).

Defauts constates avec gpt-5-mini (premiere campagne du 10 novembre 2026) : plans de 9 a 12
taches, aperçus pollues de metadonnees et d'hypotheses presentees comme des faits, reponses a
plusieurs questions, promesse de changer une preference, date traitee comme une dependance.
Les consignes au modele sont corrigees ; ces fonctions garantissent le resultat quel que soit
le modele. Aucune n'ecrit quoi que ce soit, et les limites du domaine restent inchangees.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from datetime import date
from typing import Any

from neurocoach.agent.schemas import ProjectBrief
from neurocoach.domain.plans import PlanDraft
from neurocoach.domain.preview import format_date_fr

MAX_INITIAL_TASKS = 12  # D-82 : plan detaille (etapes et taches)
MAX_ASSUMPTIONS = 3

PREFERENCES_MESSAGE = (
    "Je ne peux pas modifier vos préférences depuis la conversation : rien n'a changé. "
    "Pour des réponses plus courtes, moins d'actions affichées, un autre rythme ou des "
    "échéances, ouvrez le panneau « Préférences » dans la barre latérale, puis enregistrez."
)
DEADLINES_DISABLED_MESSAGE = (
    "Les échéances sont désactivées dans vos préférences : je ne peux pas fixer de date "
    "limite, et rien n'a été modifié. Pour en utiliser, activez les échéances dans le "
    "panneau « Préférences »."
)
DATE_NOT_PROPOSED_MESSAGE = (
    "Je n'ai pas pu traduire votre demande en date limite, et je ne propose pas d'autre "
    "modification à la place : rien n'a été modifié. Précisez la tâche et la date, par "
    "exemple « Échéance de T2 vendredi »."
)

PREFERENCE_REQUEST = re.compile(
    r"pr[ée]f[ée]rence|r[ée]ponds?(-moi)? (en|par|avec|plus|moins|toujours|d[ée]sormais)|"
    r"r[ée]ponses? (plus |moins )?(courtes?|longues?|d[ée]taill)|une seule phrase|"
    r"(plus|moins) (court|long|d[ée]taill)|tutoie|vouvoie|"
    r"(affiche|montre)(-moi)? (seulement|qu'une|une seule|moins|plus) "
)
DATE_REQUEST = re.compile(
    r"\b(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|demain|apr[eè]s-demain|"
    r"semaine prochaine|mois prochain|janvier|f[ée]vrier|mars|avril|mai|juin|juillet|"
    r"ao[uû]t|septembre|octobre|novembre|d[ée]cembre)\b|\b\d{1,2}/\d{1,2}\b|"
    r"[ée]ch[ée]ance|date limite|deadline"
)
_METADATA = re.compile(
    r"\b(draft|brouillon|statut|stade|intitul|[ée]valuation\s*:|s'appelle|nom du projet|titre du)",
    re.I,
)
_MISSING = re.compile(
    r"^\s*(aucun|aucune|pas (encore )?d[e']|rien n)|n'(a|ont) (pas )?[ée]t[ée] "
    r"(fourni|pr[ée]cis|indiqu|d[ée]fini)|n'avez pas (encore )?(fourni|pr[ée]cis|indiqu|"
    r"d[ée]fini|partag|commenc)|non (pr[ée]cis|fourni|indiqu|d[ée]fini)|inconnu",
    re.I,
)
_TIME_ONLY = re.compile(r"\d+\s*(min|minutes?|h|heures?)\b.*\b(jour|soir|matin|semaine)", re.I)
# Mots de reformulation (« vous pouvez consacrer… ») qui ne prouvent rien sur la source.
_STOPWORDS = {
    "vous", "votre", "vos", "avez", "pouvez", "voulez", "souhaitez", "etes", "pour", "dans",
    "avec", "sans", "plus", "moins", "cette", "leur", "leurs", "etre", "avoir", "faire",
    "projet", "consacrer", "environ", "chaque", "tous", "toutes", "tres", "ainsi", "comme",
    "mais", "donc", "alors", "aussi", "deja", "encore", "envisagez", "aimeriez", "veut",
    "savez", "pensez", "voudriez", "pourriez",
}  # fmt: skip
GROUNDING_THRESHOLD = 0.75  # un fait doit reprendre les mots de l'utilisateur (D-58)


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]{4,}", _fold(text)) if w not in _STOPWORDS]


def _grounding(item: str, sources: Iterable[str]) -> float:
    words = _words(item)
    if not words:
        return 0.0
    prefixes = {w[:5] for source in sources for w in _words(source)}
    return sum(w[:5] in prefixes for w in words) / len(words)


def _near(a: str, b: str) -> bool:
    """Doublon proche : memes mots porteurs, inclusion de l'un dans l'autre, ou recouvrement
    de 75 % (constate : « Vous avez beaucoup de bougies… » / « … de bougies artisanales… »)."""
    wa, wb = {w[:5] for w in _words(a)}, {w[:5] for w in _words(b)}
    if not wa or not wb:
        return _fold(a).strip() == _fold(b).strip()
    return wa <= wb or wb <= wa or len(wa & wb) / len(wa | wb) >= 0.75


def repeated_question(question: str, previous: Iterable[str]) -> bool:
    return bool(question) and any(_near(question, old) for old in previous)


def drop_near_duplicates(items: Iterable[str], sources: Iterable[str] = ()) -> list[str]:
    """Garde un seul element par groupe de doublons proches : le plus fidele aux paroles de
    l'utilisateur, puis le plus court (le moins enjolive)."""
    sources = list(sources)
    kept: list[str] = []
    for item in items:
        twin = next((k for k in kept if _near(k, item)), None)
        if twin is None:
            kept.append(item)
            continue
        better = (-_grounding(item, sources), len(item)) < (-_grounding(twin, sources), len(twin))
        if better:
            kept[kept.index(twin)] = item
    return kept


def _grounded(item: str, sources: Iterable[str], threshold: float = GROUNDING_THRESHOLD) -> bool:
    """Un fait n'est retenu que si ses mots porteurs viennent des messages de l'utilisateur."""
    words = _words(item)
    if not words:
        return False
    prefixes = {w[:5] for source in sources for w in _words(source)}
    return sum(w[:5] in prefixes for w in words) / len(words) >= threshold


PROFILE_FIELDS = ("interests", "skills", "past_attempts", "experience", "motivation", "market")


def ground_profile(
    brief: ProjectBrief, previous: ProjectBrief, user_texts: Iterable[str]
) -> ProjectBrief:
    """D-83 : un element du diagnostic n'est retenu que s'il vient des mots de la personne.
    Recette reelle du 12/11/2026 : « essais passés » rempli des le premier message, sans
    qu'elle en ait parle ; la question n'etait alors jamais posee. Sinon, la valeur
    precedente (deja verifiee) est gardee."""
    sources = list(user_texts)
    update = {}
    for name in PROFILE_FIELDS:
        value = getattr(brief, name)
        if value and value != getattr(previous, name) and not _grounded(value, sources, 0.4):
            update[name] = getattr(previous, name)
    return brief.model_copy(update=update) if update else brief


PARENTHESIZED_LIST = re.compile(r"\s*\((?=[^()]*(?:,|etc\.|…))[^()]*\)")


# D-84 : enumeration d'options apres deux-points ou tiret (recette reelle : « Quelle
# clientèle visez-vous : débutants, développeurs juniors, freelances ou entreprises ? »).
OPTION_LIST = re.compile(
    r"\s*[:\u2014\u2013]\s+(?=[^:\u2014\u2013?]*,)[^:\u2014\u2013?]*?(?=\s*\?)"
)
ASKING = re.compile(r"\bvous\b|^\s*(?:quel|quelle|quels|quelles|qu|combien|comment|o[uù])\b", re.I)


def drop_example_lists(question: str) -> str:
    """Une question de decouverte reste ouverte : la liste d'exemples entre parentheses
    (« (formation, travail, blog, etc.) ») est retiree, comme l'enumeration d'options qui
    suit un deux-points ou un tiret, si ce qui precede est deja une question."""
    question = PARENTHESIZED_LIST.sub("", question)
    match = OPTION_LIST.search(question)
    if match is not None:
        head = question[: match.start()]
        if len(head.split()) >= 3 and ASKING.search(head):
            question = head + question[match.end() :]
    return re.sub(r"\s+([?!.])", r" \1", question).strip()


# D-84 : une seule intention par question (recette reelle : « Dans quel pays comptez-vous
# vendre et quelle clientèle visez-vous ? », « Quelles compétences avez-vous et quel matériel
# utilisez-vous ? »). Une deuxieme proposition interrogative coordonnee est retiree.
SECOND_QUESTION = re.compile(
    r"\s*,?\s+(?:et|ou)\s+(?:(?:\u00e0|pour|avec|de|dans|sur|chez|aupr\u00e8s de)\s+)?"
    r"(?=(?:quel|quelle|quels|quelles|qui|combien|comment|o\u00f9|"
    r"pourquoi|est-ce)\b|qu['\u2019]|(?:avez|\u00eates|pouvez|voulez|souhaitez|comptez|visez|"
    r"utilisez|aimeriez)[-\u2011]vous\b)",
    re.IGNORECASE,
)


def single_question(question: str) -> str:
    """Garde la premiere des deux questions coordonnees ; une question simple est intacte."""
    match = SECOND_QUESTION.search(question)
    if match is None or "?" not in question[match.end() :]:
        return question
    head = question[: match.start()].rstrip(" ,;:\u2014\u2013-")
    if len(head.split()) < 3:
        return question
    return f"{head} ?"


def clean_brief(brief: ProjectBrief, user_texts: Iterable[str]) -> ProjectBrief:
    """Faits = paroles de l'utilisateur ; le reste devient hypothese a verifier, ou disparait.

    Retire les metadonnees internes (statut, titre), les constats d'information manquante
    (contradictoires des que l'information arrive) et les doublons.
    """
    sources = list(user_texts)
    usable = [
        item
        for item in brief.facts
        if not _METADATA.search(item)
        and not _MISSING.search(item)
        and not (brief.available_minutes_per_day and _TIME_ONLY.search(item))
    ]
    outcome = brief.target_outcome or ""
    # L'objectif a sa propre ligne : un fait qui le repete est retire.
    usable = [item for item in usable if not (outcome and _near(item, outcome))]
    facts = drop_near_duplicates([i for i in usable if _grounded(i, sources)], sources)
    inferred = [item for item in usable if not _grounded(item, sources)]
    # D-84 : une « hypothese » ecrite par le modele qui reprend les mots de la personne est
    # ce qu'elle a dit ou decide (recette reelle : objectif et budget declares listes comme
    # « hypothèses à vérifier ») ; une hypothese qui repete l'objectif est retiree.
    stated = [
        a for a in brief.assumptions if _grounded(a, sources) or _states_her_numbers(a, sources)
    ]
    facts = drop_near_duplicates(
        [*facts, *(a for a in stated if not (outcome and _near(a, outcome)))], sources
    )
    assumptions = [
        item
        for item in [*brief.assumptions, *inferred]
        if item not in stated
        and not (outcome and _near(item, outcome))
        and not _METADATA.search(item)
        and not _MISSING.search(item)
    ]
    assumptions = [
        a for a in drop_near_duplicates(assumptions) if not any(_near(a, f) for f in facts)
    ]
    return brief.model_copy(
        update={"facts": facts[:5], "assumptions": assumptions[:MAX_ASSUMPTIONS]}
    )


def fit_plan(
    draft: PlanDraft, minutes_per_day: int | None, max_tasks: int = MAX_INITIAL_TASKS
) -> PlanDraft:
    """Plan initial court : au plus ``max_tasks`` taches dans l'ordre propose, dependances
    coherentes, phases vides retirees, estimations ramenees au temps quotidien disponible.

    S'applique aux nouvelles propositions uniquement : les plans deja enregistres et les
    limites du domaine (20 taches) ne changent pas.
    """
    kept: set[str] = set()
    phases = []
    for phase in draft.phases:
        tasks = []
        for task in phase.tasks:
            if len(kept) >= max_tasks or any(dep not in kept for dep in task.depends_on):
                continue
            estimate = task.estimate_minutes
            if minutes_per_day and estimate and estimate > minutes_per_day:
                estimate = max(5, minutes_per_day)
            tasks.append(task.model_copy(update={"estimate_minutes": estimate}))
            kept.add(task.key)
        if tasks:
            phases.append(phase.model_copy(update={"tasks": tasks}))
    if not phases:  # aucune tache sans dependance prealable : on garde la proposition
        return draft
    return PlanDraft.model_validate(
        {**draft.model_dump(), "phases": [phase.model_dump() for phase in phases]}
    )


def keep_one_question(text: str) -> str:
    """PF-03 : une seule question par reponse. Le texte s'arrete a la premiere question."""
    first = text.find("?")
    if first == -1 or "?" not in text[first + 1 :]:
        return text
    return text[: first + 1]


def drop_questions(text: str) -> str:
    """Une justification n'interroge pas l'utilisateur : la question vient de l'interface."""
    sentences = re.split(r"(?<=[.!?…])\s+", text.strip())
    return " ".join(s for s in sentences if s and not s.endswith("?"))


# --- designation d'une tache (troisieme campagne, D-57) ------------------------------------
# Constate avec gpt-5-mini : « J'ai fini » sans reference a termine T2, devinee par le modele.
# Une tache n'est designee que par le message lui-meme : reference, ordinal ou titre.

STATUS_QUESTIONS = {
    "done": "Quelle tâche avez-vous terminée ?",
    "in_progress": "Quelle tâche voulez-vous commencer ?",
    "blocked": "Quelle tâche est bloquée ?",
    "todo": "Quelle tâche voulez-vous rouvrir ?",
}
DEFAULT_STATUS_QUESTION = "De quelle tâche parlez-vous ?"
NEXT_QUERY = re.compile(
    r"^\s*(et\s+)?(maintenant|ensuite|apr[eè]s)\s*\??\s*$|que (dois-je|faut-il|faire)|"
    r"quoi faire|par quoi (je )?(continue|commence)|prochaine (étape|action|tâche)|"
    r"je fais quoi|on fait quoi"
)
_ORDINALS = {
    "premier": 1, "premiere": 1, "1re": 1, "1ere": 1, "1er": 1,
    "deuxieme": 2, "second": 2, "seconde": 2, "2e": 2, "2eme": 2,
    "troisieme": 3, "3e": 3, "3eme": 3, "quatrieme": 4, "4e": 4, "4eme": 4,
    "cinquieme": 5, "5e": 5, "5eme": 5, "sixieme": 6, "6e": 6, "6eme": 6,
    "septieme": 7, "huitieme": 8, "neuvieme": 9, "dixieme": 10,
}  # fmt: skip
_ORDINAL = re.compile(
    r"\b(?:la|le|l')\s*(" + "|".join(_ORDINALS) + r")\b(?!\s+(?:phase|fois|semaine|etape|"
    r"partie|jour|mois))|\b(" + "|".join(_ORDINALS) + r")\s+tache\b"
)
_REF_IN_TEXT = re.compile(r"\b[Tt]([1-9][0-9]{0,3})\b")
_STATUS_WORDS = {
    "fini", "finie", "finis", "termine", "terminee", "boucle", "bouclee", "faite",
    "commence", "commencee", "bloque", "bloquee", "rouvre", "tache", "taches", "maintenant",
    "aujourd", "enfin", "voila",
}  # fmt: skip


def _title_words(title: str) -> set[str]:
    return {w[:5] for w in _words(title) if w not in _STATUS_WORDS}


def designate_tasks(
    text: str, tasks: Iterable[tuple[str, int, str]], proposed: Iterable[str] = ()
) -> list[str]:
    """D-85 : toutes les taches que le message designe (references, titres clairement repris),
    plus celles que le modele propose SI le message reprend au moins un mot porteur de leur
    titre (D-57 : jamais de tache devinee). La personne confirme ensuite par un clic."""
    catalog = list(tasks)
    by_number = {number: task_id for task_id, number, _ in catalog}
    titles = {task_id: title for task_id, _, title in catalog}
    chosen = [by_number[n] for n in sorted({int(n) for n in _REF_IN_TEXT.findall(text)})
              if n in by_number]  # fmt: skip
    said = {w[:5] for w in _words(text) if w not in _STATUS_WORDS}
    for task_id, _, title in catalog:
        words = _title_words(title)
        hits = len(words & said)
        if words and hits >= 2 and hits / len(words) >= 0.5:
            chosen.append(task_id)
    for ref in proposed:
        task_id = by_number.get(int(ref[1:])) if ref[1:].isdigit() else None
        if task_id is not None and _title_words(titles[task_id]) & said:
            chosen.append(task_id)
    return list(dict.fromkeys(chosen))


# D-86 (campagne reelle V1) : « Vous avez déjà lancé une boutique de vêtements… ça n'a pas
# marché et vous voulez retenter… » : la phrase repete le message au lieu d'apporter quelque
# chose. Le mot d'ecoute qui l'ouvre (« Parfait — utile : ») ne compte pas.
_LEAD_IN = re.compile(r"^[^:\u2014\u2013]{0,25}[:\u2014\u2013]\s*")


def echoes(reply: str, said: str, threshold: float = 0.4) -> bool:
    """La phrase reprend-elle surtout les mots du dernier message de la personne ?"""
    body = _LEAD_IN.sub("", reply.strip(), count=1)
    words = _words(body)
    if len(words) < 5 or not said.strip():
        return False
    prefixes = {w[:5] for w in _words(said)}
    return sum(w[:5] in prefixes for w in words) / len(words) >= threshold


# D-86 (campagne reelle V1) : « (avis) », « (faits/estimations, niveau de preuve partiel à
# factuel) », « (niveau_de_preuve : inconnu…) » dans la conclusion montree a la personne.
_INTERNAL_LABELS = re.compile(
    r"\s*\((?=[^()]*\b(?:niveau_de_preuve|niveau de preuve|faits?|estimations?|avis|"
    r"hypoth\w*|sources?)\b)[^()]*\)",
    re.IGNORECASE,
)
_FIELD_NAME = re.compile(r"\b[a-z]+(?:_[a-z]+)+\b")


# D-86 (campagne reelle V1) : « budget limité à 200 € », « objectif : atteindre ~150 €/mois »
# listes en hypotheses alors qu'il les avait dits (« je peux investir 200 € au maximum »).
_OWN_FIGURE = re.compile(
    r"budget|investi|objectif|gagner|revenu|heures?|\bh\b|minutes?|temps|disponib", re.I
)


def _states_her_numbers(item: str, sources: Iterable[str]) -> bool:
    """Budget, objectif ou temps dont tous les chiffres viennent de ses messages."""
    numbers = set(re.findall(r"\d+", item))
    said = {n for source in sources for n in re.findall(r"\d+", source)}
    return bool(numbers) and numbers <= said and bool(_OWN_FIGURE.search(item))


def humanize_field_names(text: str) -> str:
    """« (prix_local) » -> « (prix local) » : jamais d'identifiant interne affiche."""
    return _FIELD_NAME.sub(lambda m: m.group(0).replace("_", " "), text)


def drop_internal_labels(text: str) -> str:
    """Retire les natures et noms de champs entre parentheses, puis tout identifiant interne."""
    text = _INTERNAL_LABELS.sub("", text)
    text = _FIELD_NAME.sub(lambda m: m.group(0).replace("_", " "), text)
    return re.sub(r"\s+([,.;:!?])", r"\1", re.sub(r"[ \t]{2,}", " ", text)).strip()


def keep_concrete_instructions(proposal: Any, snapshot: Any) -> Any:
    """D-87 : une description detaillee n'est jamais remplacee par une consigne bien plus
    courte (campagne reelle V1 : liste d'outils remplacee par « par étapes »). Le changement
    de description est retire ; les autres champs proposes restent."""
    by_ref = {task.ref: task for task in snapshot.tasks.values()}
    kept = []
    for change in proposal.changes:
        task = by_ref.get(change.task_ref or "")
        new = change.fields.description
        old = (task.description or "") if task is not None else ""
        if new is not None and len(old) >= 120 and len(new) < len(old) / 2:
            fields = change.fields.model_copy(update={"description": None})
            if fields == type(fields)():
                continue
            change = change.model_copy(update={"fields": fields})
        kept.append(change)
    return proposal.model_copy(update={"changes": kept})


def tasks_over(proposal: Any, snapshot: Any, session: int | None) -> list[str]:
    """Taches restantes dont la duree, apres la proposition, depasse une seance."""
    if not session:
        return []
    new = {
        c.task_ref: c.fields.estimate_minutes
        for c in proposal.changes
        if c.op == "update" and c.fields.estimate_minutes
    }
    removed = {c.task_ref for c in proposal.changes if c.op == "delete"}
    over = []
    for task in snapshot.ordered_tasks():
        if task.status.value == "done" or task.ref in removed:
            continue
        minutes = new.get(task.ref, task.estimate_minutes)
        if minutes and minutes > session:
            over.append(f"{task.ref} ({minutes} min)")
    for change in proposal.changes:
        minutes = change.fields.estimate_minutes
        if change.op == "add" and minutes and minutes > session:
            over.append(f"{change.fields.title} ({minutes} min)")
    return over


def grounded_in(item: str, sources: Iterable[str], threshold: float = 0.4) -> bool:
    """Le texte reprend-il les mots de la personne ? (raison d'une pause, D-85)"""
    return _grounded(item, list(sources), threshold)


def designate_task(text: str, tasks: Iterable[tuple[str, int, str]]) -> tuple[str | None, str]:
    """Tache designee par le message, ou ``None`` avec la raison. ``tasks`` : (id, numero, titre).

    Ordre : reference explicite (« T2 »), ordinal non ambigu (« la deuxieme tache »), puis
    correspondance claire et unique avec un titre. En cas de doute, aucune tache.
    """
    catalog = list(tasks)
    by_number = {number: task_id for task_id, number, _ in catalog}
    refs = {int(n) for n in _REF_IN_TEXT.findall(text)}
    if len(refs) > 1:
        return None, "ambigue"
    if refs:
        number = refs.pop()
        return (by_number[number], "reference") if number in by_number else (None, f"T{number}")
    folded = _fold(text)
    ordinals = {_ORDINALS[a or b] for a, b in _ORDINAL.findall(folded)}
    if len(ordinals) > 1:
        return None, "ambigue"
    if ordinals:
        number = ordinals.pop()
        return (by_number[number], "ordinal") if number in by_number else (None, f"T{number}")
    said = {w[:5] for w in _words(text) if w not in _STATUS_WORDS}
    matches = []
    for task_id, _, title in catalog:
        words = _title_words(title)
        hits = len(words & said)
        if words and hits >= 2 and hits / len(words) >= 0.5:
            matches.append(task_id)
    if len(matches) == 1:
        return matches[0], "titre"
    return None, "ambigue" if matches else "absente"


# Constate avec gpt-5-mini (campagne ciblee) : statut vise parfois absent pour « J'ai bouclé la
# première » ou « J'ai fini ». Le verbe du message suffit ; plusieurs verbes = ambigu.
_TARGET_VERBS = (
    ("blocked", re.compile(r"bloqu")),
    ("todo", re.compile(r"rouvr|r[ée]ouvr|remet\w* [àa] faire")),
    ("in_progress", re.compile(r"commenc|d[ée]marr|attaqu")),
    ("done", re.compile(r"termin|fini|boucl|achev|c'est fait|j'ai fait")),
)
_TECHNICAL = re.compile(
    r"\b(due_date|depends_on|task_ref|due_in_days|estimate_minutes|acceptance_criteria|"
    r"phase_title|rationale|json)\b|l'utilisateur",
    re.IGNORECASE,
)


def infer_target_status(text: str) -> str | None:
    found = {status for status, verb in _TARGET_VERBS if verb.search(text.lower())}
    return found.pop() if len(found) == 1 else None


def drop_technical(text: str) -> str:
    """Une justification s'adresse a l'utilisateur : ni nom de champ interne, ni « l'utilisateur »
    a la troisieme personne (constate : « j'ai fixé la due_date »)."""
    sentences = re.split(r"(?<=[.!?…])\s+", text.strip())
    return " ".join(s for s in sentences if s and not _TECHNICAL.search(s))


# --- vouvoiement et dates dans les textes libres du modele (campagne finale, D-58) ---------------
# Constate avec gpt-5-mini : tutoiement dans la reponse a une injection (2 campagnes sur 2),
# date « 2026-11-13 » au format technique dans une justification.
_TUTOIEMENT = re.compile(r"\b(tu|toi|ta|tes|te|tien|tienne)\b|\bt['\u2019]\s*\w|-(tu|toi)\b", re.I)
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
VOUVOIEMENT_FALLBACK = "Je peux vous aider à avancer sur votre projet. Que souhaitez-vous faire ?"


def uses_tutoiement(text: str) -> bool:
    return _TUTOIEMENT.search(text) is not None


def keep_vouvoiement(text: str, fallback: str = VOUVOIEMENT_FALLBACK) -> str:
    """Retire les phrases au tutoiement ; si rien ne reste, une reponse neutre au vouvoiement."""
    if not uses_tutoiement(text):
        return text
    sentences = re.split(r"(?<=[.!?…])\s+", text.strip())
    kept = " ".join(s for s in sentences if s and not uses_tutoiement(s))
    return kept or fallback


def localize_dates(text: str) -> str:
    """Dates ISO ecrites par le modele → « vendredi 13 novembre 2026 » (affichage seulement)."""

    def replace(match: re.Match[str]) -> str:
        try:
            return format_date_fr(date(*map(int, match.groups())))
        except ValueError:
            return match.group(0)

    return _ISO_DATE.sub(replace, text)


# Constate avec gpt-5-mini (validation D-58) : « Cette semaine je n'ai rien pu faire, je suis
# débordée » classe tantot etat_projet, tantot autre ; « une version plus légère du plan »
# classe demande_plan. Sur un projet actif, ces demandes sont des replanifications.
REPLAN_REQUEST = re.compile(
    r"pas avanc|rien pu faire|pas eu le temps|en retard|d[ée]bord|surcharg|"
    r"trop (gros|long|lourd|dur|charg)|simplifi|all[éèe]g|plus l[ée]g[eè]r|replanifi|"
    r"plus petit(e)? (étape|plan)|version (plus )?(courte|l[ée]g[eè]re)|"
    # Reponses a REPLAN_QUESTION (correction R0) : « réduire la durée », « en mettre une de côté ».
    r"r[ée]dui|de c[ôo]t[ée]|"
    # D-61 : fatigue et epuisement sont aussi des demandes d'allegement.
    r"fatigu|[ée]puis|crev[ée]|[àa] bout|n'en peux plus|trop de (choses|t[âa]ches)"
)


# --- Corrections R0 (gpt-5.6-terra, 10 novembre 2026) -----------------------------------
# 1. « Je veux vendre des bougies artisanales, mais je ne sais pas par où commencer » classé
#    « aide » : l'utilisateur recevait le message d'aide générique au lieu d'une réponse sur
#    son idée. Sur un projet sans plan, une idée entrepreneuriale se clarifie toujours.
IDEA_STATEMENT = re.compile(
    r"vend|vente|lanc|cr[ée]e|cr[ée]a|ouvri|ouvre|mont[ae]|d[ée]marr|commerc|client|produit|"
    r"servic|boutique|atelier|march[ée]|entrepr|business|activit[ée]|projet|id[ée]e|offre|"
    r"cours|formation|artisan|fabriqu|tarif|prix|bougie|savon|v[ée]lo|cuisine"
)
# Demandes d'aide sur l'outil et consignes adressees a l'assistant : jamais une idee.
NOT_AN_IDEA = re.compile(
    r"^\W*(bonjour|salut|bonsoir|coucou|aide|help|merci)\W*$|comment (ça|ca) (marche|fonctionne)|"
    r"(que|quoi) (peux|pouvez|sais|savez)[- ](tu|vous)|(tu|vous) (peux|pouvez|sais|savez) faire "
    r"quoi|[àa] quoi (sers|servez)|mode d'emploi|comment (vous |t')?utiliser|"
    r"\bignore|r[èe]gles|confirme"
)
IDEA_ORIENTATION = (
    "Pour démarrer sans vous disperser, une première orientation simple : vérifier à petite "
    "échelle que des personnes sont intéressées, avant d'investir du temps ou de l'argent."
)


def is_idea_statement(text: str) -> bool:
    """Message qui décrit une idée ou une activité, et non une demande d'aide sur l'outil."""
    lower = text.lower().strip()
    return (
        len(lower.split()) >= 4
        and bool(IDEA_STATEMENT.search(lower))
        and not (NOT_AN_IDEA.search(lower))
    )


# 2. Modification vide (aucun champ) : l'utilisateur lisait « Certaines informations ne sont
#    pas valides. Aucune modification n'a été précisée. » Une demande vide ou ambiguë reçoit
#    une seule question de clarification, simple ; rien n'est proposé ni écrit.
REPLAN_QUESTION = (
    "Aucun souci, nous pouvons alléger le plan sans pression. Que préférez-vous : réduire la "
    "durée des tâches, ou en mettre une de côté pour l'instant ?"
)
ADD_QUESTION = "Quelle tâche souhaitez-vous ajouter ? Décrivez-la en quelques mots."
WHICH_TASK_QUESTION = "Quelle tâche souhaitez-vous modifier (par exemple T2) ?"
WHICH_DELETE_QUESTION = "Quelle tâche souhaitez-vous retirer (par exemple T2) ?"


def change_question(intent: str | None, task_ref: str | None, *, deadlines: bool) -> str:
    """Question posée à la place d'une erreur technique quand la modification est imprécise."""
    if intent == "replanifier":
        return REPLAN_QUESTION
    if intent == "ajouter_tache":
        return ADD_QUESTION
    if task_ref is None:
        return WHICH_DELETE_QUESTION if intent == "supprimer_tache" else WHICH_TASK_QUESTION
    fields = (
        "le titre, la durée estimée, la description ou l'échéance"
        if deadlines
        else "le titre, la durée estimée ou la description"
    )
    return f"Que souhaitez-vous changer pour {task_ref} : {fields} ?"


# --- D-61 (apres la confirmation Terra, 10 novembre 2026) ---------------------------------
# 1. Une tache n'est jamais devinee : pour « Je voudrais changer quelque chose dans le plan »,
#    Terra visait T1 et la question nommait T1. Seules comptent les taches que l'utilisateur
#    designe (reference, ordinal, titre), ou celle que le coach vient de nommer a sa demande.
WHOLE_PLAN = re.compile(
    r"\b(tout le plan|l'ensemble du plan|le plan entier|tout mon plan|toutes les t[âa]ches|"
    r"les t[âa]ches|chaque t[âa]che)\b|"
    r"\b(all[éèe]g|simplifi|r[ée]dui|raccourc|replanifi)\w*\s+(le|mon|ce|du) plan\b"
)
_NAMED_IN_QUESTION = re.compile(r"Que souhaitez-vous changer pour (T[1-9][0-9]{0,3}) :")


def designated_refs(
    text: str, tasks: Iterable[tuple[str, int, str]], previous_reply: str | None
) -> set[str]:
    """References « T<n> » que l'utilisateur a designees ; jamais une tache supposee."""
    catalog = list(tasks)
    refs = {f"T{n}" for n in _REF_IN_TEXT.findall(text)}
    task_id, _ = designate_task(text, catalog)
    refs |= {f"T{number}" for tid, number, _ in catalog if tid == task_id}
    named = _NAMED_IN_QUESTION.search(previous_reply or "")
    if named:
        refs.add(named.group(1))  # le coach venait de demander quoi changer sur cette tache
    return refs


# 2. Surcharge : Terra produisait 3 fois sur 4 une modification vide. Le code propose alors un
#    allegement concret du plan existant, toujours en attente de confirmation : la prochaine
#    tache faisable, deja estimee a plus de 10 minutes, ramenee a une etape de 10 minutes.
#    Aucune tache ni aucune duree n'est inventee.
OVERLOAD = re.compile(
    r"d[ée]bord|surcharg|fatigu|[ée]puis|crev[ée]|[àa] bout|n'en peux plus|rien pu faire|"
    r"pas eu le temps|pas avanc|trop (gros|long|lourd|dur|charg)|trop de (choses|t[âa]ches)"
)
LIGHT_STEP_MINUTES = 10
OVERLOAD_RATIONALE = (
    "Une période chargée, cela arrive : le plan s'adapte. Une première étape de {new} minutes "
    "suffit pour reprendre ; les autres tâches ne changent pas."
)


def lighter_step(tasks: list[dict], next_refs: list[str]) -> tuple[str, int] | None:
    """(reference, duree actuelle) de la tache a alleger, ou ``None`` si rien ne s'y prete."""
    by_ref = {task["ref"]: task for task in tasks}
    order = [*next_refs, *(task["ref"] for task in tasks)]
    for ref in dict.fromkeys(order):
        task = by_ref.get(ref)
        if task is None or task.get("status") not in ("todo", "in_progress"):
            continue
        minutes = task.get("estimate_minutes")
        if minutes and minutes > LIGHT_STEP_MINUTES:
            return ref, minutes
    return None


def is_lightening(changes: Iterable, tasks: list[dict]) -> bool:
    """Proposition du modele acceptable face a une surcharge : elle allege le plan existant,
    sans tache ajoutee ni supprimee, sans duree inventee ou allongee. Une echeance repoussee
    (« reporter ») reste possible ; si les echeances sont desactivees, D-58 la retire."""
    by_ref = {task["ref"]: task for task in tasks}
    changes = list(changes)
    if not changes:
        return False
    for change in changes:
        if change.op != "update" or change.task_ref not in by_ref:
            return False
        fields = change.fields
        if fields.estimate_minutes is not None:
            current = by_ref[change.task_ref].get("estimate_minutes")
            if not current or fields.estimate_minutes >= current:
                return False
    return True


# 3. D-80 : l'objectif provisoire code en dur (D-61, « Voici un objectif provisoire… ») a
#    ete supprime : il reprenait le titre du projet au lieu du sujet (recette du
#    11/11/2026). Le coach (le modele) conseille lui-meme.
