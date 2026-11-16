"""Detection des besoins de recherche et recueil des informations utiles (R3, D-70).

Le code, et non le modele, decide qu'une recherche est pertinente : hesitation entre
plusieurs idees, question de marche, de concurrence, de prix, d'avis ou de risques, ou
demande explicite. Les questions sont courtes, posees une a une et jamais repetees ; une
information deja connue (projet, conversation) n'est jamais redemandee.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from neurocoach.domain.research import ResearchCategory, detect_markets

C = ResearchCategory
NUMBERS = {"deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "2": 2, "3": 3, "4": 4, "5": 5}
MAX_IDEAS = 5
COMPARE = re.compile(
    r"\b(deux|trois|quatre|cinq|[2-5]|plusieurs)\s+(id[ée]es|projets|pistes|options|activit[ée]s)"
    r"|laquelle (choisir|prendre)|lequel (choisir|prendre)|h[ée]site(r)? entre|"
    r"choisir entre|d[ée]partager|comparer (mes|ces|les|deux|plusieurs)"
)
COUNT = re.compile(
    r"\b(deux|trois|quatre|cinq|[2-5])\s+(id[ée]es|projets|pistes|options|activit[ée]s)"
)
EXPLICIT = re.compile(
    r"\b(fai[st]e?s?|lance[rz]?|pr[ée]pare[rz]?|faire|relance[rz]?)\s+(une |des |la |ma )?"
    r"(nouvelles? |autres? |petites? )?(recherches?|[ée]tude)\b|"
    r"cherche[rz]? sur (le )?(web|internet)|recherche (web|internet)"
)
CATEGORY_TRIGGERS: tuple[tuple[re.Pattern[str], ResearchCategory], ...] = (
    (re.compile(r"\bconcurren\w*|\bqui (vend|fait|propose) d[ée]j[àa]"), C.COMPETITION),
    (
        re.compile(
            r"\bquels? prix\b|\bprix (pratiqu|du march|moyen|des autres)|\btarifs? (pratiqu|des|"
            r"moyen)|combien (vendent|co[uû]te|facturent|font payer)|\bvendre (à|a) quel prix"
        ),
        C.PRICES,
    ),
    (
        re.compile(
            r"\bavis (des |de |)clients?|\b(les|des|dans les|leurs) avis\b|\bce qu'en pensent|"
            r"\bles clients (aiment|pens)"
        ),
        C.REVIEWS,
    ),
    (
        re.compile(
            r"[ée]tude de march|taille du march|\b(le|ce|du|mon|un) march[ée] (est|existe|pour|"
            r"de ce)|y a-t-il (une |de la )?demande|\bla demande (pour|existe|est)|est-ce que "
            r"(ça|ca|cela) (se vend|marche|int[ée]resse)|\brentab"
        ),
        C.MARKET,
    ),
    (
        re.compile(r"\brisques?\b|\binconv[ée]nients?\b|\bpi[èe]ges?\b|\bobstacles?\b"),
        C.PROBLEMS,
    ),
    (re.compile(r"\bsolutions? (existantes|alternatives)|\balternatives?\b"), C.SOLUTIONS),
    (
        re.compile(
            r"\bforums?\b|t[ée]moignages?|retours? d'exp[ée]rience|\bce que disent (les )?"
            r"(clients|gens|utilisateurs)|\bfrustrations?\b|\bplaintes?\b|besoins? (r[ée]els|non "
            r"satisfaits)|\bdiscussions?\b"
        ),
        C.TESTIMONIALS,
    ),
)
# Comparaison et recherche generale : demande, concurrents, prix, avis, risques et, depuis R5,
# retours d'experience (forums et temoignages autorises).
DEFAULT_CATEGORIES = [C.MARKET, C.COMPETITION, C.PRICES, C.REVIEWS, C.PROBLEMS, C.TESTIMONIALS]
SKIP = re.compile(r"^\s*(je\s+)?(passe|passer)\b|^\s*je ne sais pas|^\s*peu importe|^\s*aucune")
CRITERIA = re.compile(
    r"\b(rapid\w*|vite|tout de suite|peu d'investissement|investir peu|petit budget|budget|"
    r"sans argent|revenus?|rentab\w*|temps|week-?ends?|le soir|[àa] c[ôo]t[ée]|passion|plaisir|"
    r"risque|stable|r[ée]gulier|libert[ée]|impact)\b"
)

ASK_IDEAS = (
    "Avec plaisir, comparons-les avec des données. Quelles sont vos {n} idées ? Écrivez-les "
    "en une phrase chacune, une par ligne."
)
ASK_IDEAS_UNKNOWN = (
    "Avec plaisir. Quelles idées hésitez-vous à départager ? Une phrase par idée, une par ligne."
)
ASK_CRITERIA = (
    "Qu'est-ce qui compte le plus pour vous dans ce choix : démarrer vite, investir peu, un "
    "revenu régulier, ou autre chose ? Vous pouvez répondre « je passe »."
)
ASK_MARKET_SUFFIX = " Vous pouvez répondre « je passe » pour une recherche non spécifique."
NOT_ENABLED = (
    "Je peux préparer une recherche web sur la concurrence, les prix et les avis clients, mais "
    "elle n'est pas encore activée : il faut ajouter une clé Tavily ou Exa dans le fichier "
    "`.env` local, puis redémarrer l'application. En attendant, continuons avec ce que vous "
    "savez déjà."
)
OFFER = (
    "Je peux aussi préparer une recherche web sur la concurrence, les prix et les avis "
    "clients : il suffit de me le demander."
)
PROPOSAL_INTRO = "Voici la recherche que je vous propose"
RESEARCH_WITH_BUTTON = (
    "Pour lancer la recherche, cliquez sur « Approuver et lancer », sous la conversation. "
    "Rien n'est envoyé sans ce clic."
)
CANCELLED = "D'accord, aucune recherche n'est lancée."
# R6 : demande de solutions (apres une analyse) et conversion des actions en taches.
SOLVE = re.compile(
    r"(cherch|trouv|propos)\w* (moi |nous )?(des |de |les |quelques )?solutions|"
    r"comment (r[ée]soudre|r[ée]gler|corriger|[ée]viter|g[ée]rer) (ces|ce|les|le)|"
    r"des solutions (pour|à|aux|a)|quels? outils?|solutions? (concr[eè]tes?|existantes?)"
)
TO_TASKS = re.compile(
    r"(transform|convert|ajout|met|mets|cr[ée]e|int[eè]gr)\w* (ces |les |mes )?(actions?|"
    r"[ée]tapes?|solutions?)( en| dans| à| a| au)? (t[âa]ches?|mon plan|plan|le plan)|"
    r"\ben t[âa]ches\b"
)
SOLUTIONS_INTRO = "Voici la recherche de solutions que je vous propose :"
# Finalisation : commandes explicites et courtes, sans question ; leur route est certaine.
RESEARCH_COMMAND = re.compile(
    r"^(analyse[rz]?|(re)?fai[st]e?s? l'analyse|lance[rz]? l'analyse|analyse ces r[ée]sultats|"
    r"(cherche|trouve)[rz]?( moi)? (des |les )?solutions|"
    r"(transforme|convertis|ajoute)[rz]? (ces |les )?actions "
    r"(en t[âa]ches|(à|a|dans) (mon |le )?plan)"
    r")[^?]*$"
)
NO_PROBLEMS = (
    "Je n'ai pas encore de problème assez étayé pour chercher des solutions : il faut "
    "d'abord une recherche, dont l'analyse repère les problèmes."
)
NO_ACTIONS = (
    "Je n'ai pas encore d'actions à transformer en tâches : cherchons d'abord des solutions."
)
TASKS_PHASE = "Solutions aux problèmes repérés"
# Apres une recherche : demande d'analyse (R4) ou question sur ses resultats.
ANALYZE = re.compile(
    r"\banaly[sz]\w*|approfondi\w*|\bcompar(e|er|ez|aison)\b|\brecommand\w*|conseill\w*|"
    r"\b(ton|votre) avis\b|\blaquelle\b|\blequel\b|\bmeilleure?\b|qu'en pens|que choisir|"
    r"\bbilan\b|synth[eè]se|avantages|inconv[ée]nients"
)
# Recette du 11/11/2026 : « Laquelle de ces solutions me conseillez-vous, avec mon budget ? »
# etait classee « conseil financier » par le modele. Une question qui porte sur les resultats
# de la recherche y est repondue ; une vraie demande medicale, juridique, fiscale ou de
# placement reste hors perimetre.
RESULT_QUESTION = re.compile(
    r"\b(ces|vos|les|tes) (solutions?|outils?|options?|id[ée]es?|pistes?|r[ée]sultats?|"
    r"actions?|approches?)\b|\b(laquelle|lequel)s? (de|des|d')"
)
SENSITIVE_ADVICE = re.compile(
    r"m[ée]dic|m[ée]decin|diagnosti|th[ée]rapi|maladie|sant[ée]|avocat|juridique|proc[èe]s|"
    r"litige|imp[ôo]ts?|fiscal|placement|placer|bourse|actions? en bourse|crypto|emprunt|"
    r"cr[ée]dit|pr[êe]t (bancaire|immobilier)|assurance[- ]vie|[ée]pargne|retraite"
)
REDO = re.compile(r"\b(refai[st]|à nouveau|a nouveau|mets? à jour|actualise|relance l'analyse)")
FOLLOWUP = re.compile(
    r"\blaquelle\b|\blequel\b|r[ée]sultats?|qu'en pens|conseill|recommand|meilleure?\b|"
    r"que retenir|synth[eè]se|r[ée]sum|qu'est-ce que (ça|ca|cela) (donne|montre)"
)


@dataclass(frozen=True)
class ResearchNeed:
    kind: str  # compare, topic, explicit
    categories: tuple[ResearchCategory, ...]
    count: int | None = None


def detect_research_need(text: str) -> ResearchNeed | None:
    lower = " ".join(text.lower().split())
    found = tuple(dict.fromkeys(cat for rx, cat in CATEGORY_TRIGGERS if rx.search(lower)))
    if COMPARE.search(lower):
        match = COUNT.search(lower)
        count = NUMBERS.get(match.group(1)) if match else None
        return ResearchNeed("compare", tuple(DEFAULT_CATEGORIES), count)
    if found:
        return ResearchNeed("topic", found)
    if EXPLICIT.search(lower):
        return ResearchNeed("explicit", tuple(DEFAULT_CATEGORIES))
    return None


_BULLET = re.compile(r"^\s*(?:[-*•\u2013]|\(?\d{1,2}[).:-]|id[ée]e\s*\d+\s*[:.-])\s*", re.I)


def _clean(item: str) -> str:
    item = _BULLET.sub("", item).strip(" .;,:\t")
    return " ".join(item.replace("?", "").split())


def parse_ideas(text: str) -> list[str]:
    """Idees listees par l'utilisateur : lignes, puces, numeros, points-virgules, ou liste
    « a, b, c et d ». Rien n'est devine : moins de deux elements = aucune liste."""
    lines = [line for line in text.splitlines() if line.strip()]
    items: list[str] = []
    if len(lines) >= 2:
        items = [_clean(line) for line in lines]
        if items and items[0].endswith(("idées", "idees")):
            items = items[1:]
    elif ";" in text:
        items = [_clean(part) for part in text.split(";")]
    elif re.search(r"\b1[).]", text):
        items = [_clean(p) for p in re.split(r"\s*\b\d{1,2}[).]\s*", text) if p.strip()]
        if items and not re.match(r"^\s*1[).]", text):
            items = items[1:]  # le texte avant « 1) » est une introduction
    else:
        body = text.split(":", 1)[1] if ":" in text else text
        parts = re.split(r",\s*|\s+et\s+(?=\w)", body)
        if len(parts) >= 3 and all(len(p.split()) >= 2 for p in parts):
            items = [_clean(p) for p in parts]
    items = [i for i in items if len(i) >= 3 and len(i.split()) >= 1][:MAX_IDEAS]
    return items if len(items) >= 2 else []


def known_criteria(texts: list[str]) -> list[str]:
    found: list[str] = []
    for text in texts:
        for match in CRITERIA.finditer(text.lower()):
            word = match.group(1)
            if word not in found:
                found.append(word)
    return found[:5]


def market_from_answer(text: str) -> list[str] | None:
    """Reponse a la question du marche : pays reconnus, zone courte, ou « je passe »."""
    if SKIP.search(text.lower()):
        return ["international"]
    detected = detect_markets([text])
    if detected:
        return detected
    words = text.strip(" .!").split()
    if 1 <= len(words) <= 4 and not re.search(r"\d|@", text):
        return [" ".join(words)[:40]]
    return None
