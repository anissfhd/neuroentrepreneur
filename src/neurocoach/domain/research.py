"""Business Researcher, R1 : missions de recherche, sources et regles de preuve (domaine pur).

Aucune entree-sortie ici : ni base, ni reseau, ni modele. Le service d'application
(``application/research_service.py``) orchestre ; les fournisseurs passent par un port
(``neurocoach.research.ports``). En R1, seuls des fournisseurs SIMULES existent.

Principes (docs/R1_RESEARCH_PROPOSAL.md) :
- l'utilisateur approuve une MISSION delimitee (objectif, projets, marches, categories,
  fournisseurs, donnees transmises, budget et limites) ; dans ce perimetre, plusieurs
  recherches s'enchainent sans nouvelle confirmation ; toute extension en demande une ;
- une recherche n'ecrit jamais dans les projets ni les taches ;
- un « fait » exige une source et une citation presente dans son extrait ; sinon il est
  retrograde (estimation ou hypothese) ; rien n'est invente ;
- le contenu du Web est une donnee, jamais une consigne.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator

from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.models import DomainModel, UtcDatetime

MAX_EXCERPT = 500  # D-R8 : extrait conserve par source, jamais de page entiere
MAX_QUOTE = 300
MAX_QUERY_WORDS = 25
DEFAULT_BUDGET_USD = 0.40  # D-R6 : plafond par analyse d'idee
DEFAULT_MAX_QUERIES = 15
DEFAULT_RESULTS_PER_QUERY = 5
DEFAULT_VALIDITY_DAYS = 7
INTERNATIONAL = "international"


class ResearchCategory(StrEnum):
    MARKET = "marche"
    COMPETITION = "concurrence"
    PRICES = "prix"
    REVIEWS = "avis"
    PROBLEMS = "problemes"
    SOLUTIONS = "solutions"
    TESTIMONIALS = "temoignages"  # R5 : retours d'experience, forums, discussions


# Categories historiques (R1 a R4) : defaut d'une mission preparee sans precision.
CORE_CATEGORIES = [
    ResearchCategory.MARKET,
    ResearchCategory.COMPETITION,
    ResearchCategory.PRICES,
    ResearchCategory.REVIEWS,
    ResearchCategory.PROBLEMS,
    ResearchCategory.SOLUTIONS,
]
# R5 : categories ou parlent les clients (avis, temoignages, plaintes).
VOICE_CATEGORIES = frozenset(
    {ResearchCategory.REVIEWS, ResearchCategory.TESTIMONIALS, ResearchCategory.PROBLEMS}
)


CATEGORY_LABELS = {
    ResearchCategory.MARKET: "marché",
    ResearchCategory.COMPETITION: "concurrence",
    ResearchCategory.PRICES: "prix",
    ResearchCategory.REVIEWS: "avis",
    ResearchCategory.PROBLEMS: "problèmes",
    ResearchCategory.SOLUTIONS: "solutions",
    ResearchCategory.TESTIMONIALS: "retours d'expérience",
}
# Categories dont le resultat depend du pays : une seule question si le marche manque.
MARKET_REQUIRED = frozenset(
    {ResearchCategory.MARKET, ResearchCategory.COMPETITION, ResearchCategory.PRICES}
)
MARKET_QUESTION = "Dans quel pays ou quelle zone souhaitez-vous vendre en priorité ?"


class Nature(StrEnum):
    FACT = "fait"
    ESTIMATE = "estimation"
    HYPOTHESIS = "hypothese"


NATURE_LABELS = {
    Nature.FACT: "Fait sourcé",
    Nature.ESTIMATE: "Estimation",
    Nature.HYPOTHESIS: "Hypothèse à vérifier",
}


class MissionStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    COMPLETED = "completed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"  # remplacee par une extension approuvee


class Origin(StrEnum):
    USER = "dit par vous"
    PROJECT = "projet"
    ASSUMED = "supposé"
    UNKNOWN = "inconnu"


# --- fiche de recherche ------------------------------------------------------------------


class BriefField(DomainModel):
    value: str | None = None
    origin: Origin = Origin.UNKNOWN


class ResearchBrief(DomainModel):
    offer: BriefField
    target: BriefField
    channel: BriefField
    markets: list[str] = Field(default_factory=list)
    market_origin: Origin = Origin.UNKNOWN
    constraints: list[str] = Field(default_factory=list)

    @property
    def hypotheses(self) -> list[str]:
        items = []
        for label, item in (("cible", self.target), ("canal", self.channel)):
            if item.origin is Origin.ASSUMED and item.value:
                items.append(f"{label} supposée : {item.value}")
        return items


def _fold(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text)
    return "".join(c for c in stripped if not unicodedata.combining(c)).casefold()


# Pays, et villes qui designent un pays sans ambiguite. Aucun marche par defaut (D-R10).
_COUNTRIES = {
    "france": "France", "maroc": "Maroc", "tunisie": "Tunisie", "algerie": "Algérie",
    "belgique": "Belgique", "suisse": "Suisse", "canada": "Canada", "senegal": "Sénégal",
    "cote d'ivoire": "Côte d'Ivoire", "espagne": "Espagne", "allemagne": "Allemagne",
    "royaume-uni": "Royaume-Uni", "etats-unis": "États-Unis", "luxembourg": "Luxembourg",
}  # fmt: skip
_CITIES = {
    "paris": "France", "lyon": "France", "marseille": "France", "lille": "France",
    "toulouse": "France", "bordeaux": "France", "nantes": "France", "nice": "France",
    "strasbourg": "France", "casablanca": "Maroc", "rabat": "Maroc", "marrakech": "Maroc",
    "tanger": "Maroc", "fes": "Maroc", "agadir": "Maroc", "tunis": "Tunisie",
    "sfax": "Tunisie", "alger": "Algérie", "oran": "Algérie", "bruxelles": "Belgique",
    "geneve": "Suisse", "lausanne": "Suisse", "montreal": "Canada", "dakar": "Sénégal",
    "abidjan": "Côte d'Ivoire",
}  # fmt: skip
_WORLDWIDE = re.compile(r"\b(international|partout dans le monde|dans le monde entier)\b")
# D-80 : pays designe par un adjectif apres un nom de marche (« marché français »,
# « clientèle belge », « PME québécoises »). Jamais seul : « en français » est une langue.
_MARKET_NOUNS = (
    r"march[eé]s?|clients?|client[eè]le|public|consommateurs?|acheteurs?|entreprises?|pme|tpe|"
    r"professionnels?|particuliers?|territoire|pays"
)
_ADJECTIVES = {
    "francais": "France", "francaise": "France", "francaises": "France",
    "belge": "Belgique", "belges": "Belgique", "suisse": "Suisse", "suisses": "Suisse",
    "quebecois": "Canada", "quebecoise": "Canada", "quebecoises": "Canada",
    "canadien": "Canada", "canadienne": "Canada", "canadiens": "Canada",
    "canadiennes": "Canada", "marocain": "Maroc", "marocaine": "Maroc", "marocains": "Maroc",
    "marocaines": "Maroc", "tunisien": "Tunisie", "tunisienne": "Tunisie",
    "tunisiens": "Tunisie", "tunisiennes": "Tunisie", "algerien": "Algérie",
    "algerienne": "Algérie", "algeriens": "Algérie", "algeriennes": "Algérie",
    "senegalais": "Sénégal", "senegalaise": "Sénégal", "senegalaises": "Sénégal",
    "ivoirien": "Côte d'Ivoire", "ivoirienne": "Côte d'Ivoire", "ivoiriens": "Côte d'Ivoire",
    "luxembourgeois": "Luxembourg", "luxembourgeoise": "Luxembourg",
}  # fmt: skip
_ADJECTIVE = re.compile(rf"\b(?:{_MARKET_NOUNS})\s+(?:[a-z'-]+\s+)?({'|'.join(_ADJECTIVES)})\b")
_TARGETS = (
    (re.compile(r"\bentreprises?\b|\bb2b\b|\bprofessionnels?\b"), "entreprises"),
    (re.compile(r"\benfants?\b"), "familles avec enfants"),
    (re.compile(r"\bparents?\b"), "parents"),
    (re.compile(r"\betudiants?\b"), "étudiants"),
    (re.compile(r"\bcollegues?\b"), "collègues de bureau"),
    (re.compile(r"\bvoisins?\b"), "voisinage"),
    (re.compile(r"\btouristes?\b"), "touristes"),
    (re.compile(r"\bparticuliers?\b"), "particuliers"),
)
_CHANNELS = (
    (re.compile(r"\ben ligne\b|\binternet\b|\bsite\b|\bplateforme\b"), "vente en ligne"),
    (re.compile(r"\bmarches?\b(?! cible)|\bstand\b"), "marchés et stands"),
    (re.compile(r"\bboutique\b|\bmagasin\b"), "boutique"),
)


def detect_markets(texts: Iterable[str]) -> list[str]:
    """Marches cites explicitement (pays, ville connue, international). Jamais de defaut."""
    found: list[str] = []
    for text in texts:
        folded = _fold(text or "")
        for key, country in [*_COUNTRIES.items(), *_CITIES.items()]:
            if re.search(rf"\b{re.escape(key)}\b", folded) and country not in found:
                found.append(country)
        for match in _ADJECTIVE.finditer(folded):
            country = _ADJECTIVES[match.group(1)]
            if country not in found:
                found.append(country)
        if _WORLDWIDE.search(folded) and INTERNATIONAL not in found:
            found.append(INTERNATIONAL)
    return found


def build_brief(
    *,
    title: str,
    idea: str | None,
    user_texts: Iterable[str] = (),
    constraints: Iterable[str] = (),
    markets: Iterable[str] = (),
    segment: str | None = None,
) -> ResearchBrief:
    """Fiche construite a partir de ce qui est DEJA connu : aucune question si possible."""
    texts = [t for t in user_texts if t]
    offer_text = (idea or "").strip() or title.strip()
    offer = BriefField(value=offer_text, origin=Origin.USER if idea else Origin.PROJECT)
    folded = _fold(" ".join([offer_text, *texts]))
    target = next(
        (
            BriefField(value=label, origin=Origin.USER)
            for rx, label in _TARGETS
            if rx.search(folded)
        ),
        BriefField(value="particuliers", origin=Origin.ASSUMED),
    )
    if segment:
        # D-82 : la clientele comprise de la conversation (recette : « cible supposée :
        # particuliers » sous une recherche pour des TPE).
        target = BriefField(value=segment, origin=Origin.USER)
    channel = next(
        (
            BriefField(value=label, origin=Origin.USER)
            for rx, label in _CHANNELS
            if rx.search(folded)
        ),
        BriefField(),
    )
    given = [m for m in markets if m]
    detected = given or detect_markets([offer_text, *texts])
    origin = Origin.USER if detected else Origin.UNKNOWN
    return ResearchBrief(
        offer=offer,
        target=target,
        channel=channel,
        markets=detected,
        market_origin=origin,
        constraints=list(constraints)[:10],
    )


def missing_question(brief: ResearchBrief, categories: Iterable[ResearchCategory]) -> str | None:
    """Une seule question, et seulement si le marche est indispensable et inconnu."""
    if not brief.markets and any(c in MARKET_REQUIRED for c in categories):
        return MARKET_QUESTION
    return None


# --- minimisation et requetes ------------------------------------------------------------

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?:\+?\d[\s.-]?){6,}")
_URL = re.compile(r"https?://\S+|www\.\S+")
_INTERNAL_ID = re.compile(r"\b(usr|prj|pha|tsk|pac|evt|thr|rsm|rsq|rss|rsf)_[0-9a-f]{8,}\b")
_HEALTH = re.compile(
    r"\b(tdah|tdha|adhd|autis\w*|asperger|dys(lex|prax|calcul|phas)\w*|bipolai\w*|"
    r"d[ée]pressi\w*|anxi[ée]t\w*|diagnosti\w*|maladie\w*|handicap\w*|m[ée]dicament\w*|"
    r"traitement\w* m[ée]dica\w*|th[ée]rapi\w*|neuroatypi\w*|neurodivergen\w*|"
    r"haut potentiel|hpi|burn[- ]?out|trouble\w*)\b",
    re.I,
)
_NAME_INTRO = re.compile(r"\b(je m'appelle|mon nom est|moi c'est)\s+\S+(\s+\S+)?", re.I)
_STOPWORDS = {
    "je", "j", "veux", "voudrais", "aimerais", "souhaite", "mais", "ne", "sais", "pas", "par",
    "ou", "où", "commencer", "un", "une", "des", "de", "du", "la", "le", "les", "l", "d", "et",
    "mes", "mon", "ma", "a", "à", "au", "aux", "pour", "en", "sur", "avec", "qui", "que",
    "vendre", "lancer", "faire", "creer", "créer", "ouvrir", "idée", "idee", "projet",
}  # fmt: skip


def minimize(text: str, forbidden: Iterable[str] = ()) -> str:
    """Retire adresses, telephones, URL, identifiants internes, termes de sante, noms
    declares et noms donnes (utilisateur) ; 25 mots au plus. Applique a TOUTE requete."""
    cleaned = _NAME_INTRO.sub(" ", text)
    for rx in (_EMAIL, _URL, _INTERNAL_ID, _PHONE, _HEALTH):
        cleaned = rx.sub(" ", cleaned)
    for word in forbidden:
        if word and len(word) > 1:
            cleaned = re.sub(re.escape(word), " ", cleaned, flags=re.I)
    words = cleaned.split()
    return " ".join(words[:MAX_QUERY_WORDS])


def offer_keywords(offer: str, limit: int = 6) -> str:
    words = re.findall(r"[\wÀ-ÿ'-]+", offer)
    kept = [w for w in words if w.casefold() not in _STOPWORDS and len(w) > 1]
    return " ".join(kept[:limit]) or offer[:60]


_TEMPLATES = {
    ResearchCategory.MARKET: "{offer} marché demande tendances {market}",
    ResearchCategory.COMPETITION: "{offer} concurrents entreprises {market}",
    ResearchCategory.PRICES: "{offer} prix tarifs {market}",
    ResearchCategory.REVIEWS: "{offer} avis clients",
    ResearchCategory.PROBLEMS: "{offer} problèmes plaintes clients",
    ResearchCategory.SOLUTIONS: "{offer} solutions alternatives",
    ResearchCategory.TESTIMONIALS: "{offer} retour d'expérience forum témoignage",
}


class PlannedQuery(DomainModel):
    category: ResearchCategory
    text: str = Field(min_length=1, max_length=300)
    provider: str
    market: str | None = None
    project_id: str | None = None
    subject: str | None = None  # R3 : idee comparee a laquelle la requete se rapporte


class RequestedQuery(DomainModel):
    """D-80 : requete redigee par le modele a partir de la conversation, puis minimisee."""

    category: ResearchCategory
    text: str = Field(min_length=3, max_length=300)


def spec_queries(
    requested: Iterable[RequestedQuery],
    brief: ResearchBrief,
    categories: Iterable[ResearchCategory],
    routing: dict[ResearchCategory, list[str]],
    forbidden: Iterable[str] = (),
    project_id: str | None = None,
) -> list[PlannedQuery]:
    """Requetes redigees par le modele (termes exacts, langue et zone du marche) ; le code
    les minimise, ajoute le marche s'il manque et borne leur nombre. Une categorie sans
    requete du modele garde la requete deterministe."""
    requested = list(requested)
    markets = brief.markets or [None]
    planned: list[PlannedQuery] = []
    seen: set[tuple[str, str, str, str | None]] = set()
    for category in categories:
        providers = routing.get(category, [])
        texts = [q.text for q in requested if q.category is category]
        if not texts:
            planned += plan_queries(brief, [category], routing, forbidden, project_id)
            continue
        # Au plus deux formulations quand un seul fournisseur couvre la categorie, une sinon :
        # le nombre de recherches (et leur cout) reste celui d'une mission classique.
        texts = texts[: 2 if len(providers) == 1 else 1]
        targets = markets if category in MARKET_REQUIRED else [None]
        for market in targets:
            market_text = "" if market in (None, INTERNATIONAL) else market
            for raw in texts:
                text = raw
                if market_text and _fold(market_text) not in _fold(text):
                    text = f"{text} {market_text}"
                text = minimize(text, forbidden)
                for provider in providers:
                    key = (provider, category.value, text, market)
                    if not text or key in seen:
                        continue
                    seen.add(key)
                    planned.append(
                        PlannedQuery(category=category, text=text, provider=provider,
                                     market=market, project_id=project_id)
                    )  # fmt: skip
    return planned


def plan_queries(
    brief: ResearchBrief,
    categories: Iterable[ResearchCategory],
    routing: dict[ResearchCategory, list[str]],
    forbidden: Iterable[str] = (),
    project_id: str | None = None,
    subject: str | None = None,
) -> list[PlannedQuery]:
    """Requetes deterministes en R1 (un modele pourra les rediger en R3), toujours minimisees."""
    keywords = offer_keywords(brief.offer.value or "")
    markets = brief.markets or [None]
    planned: list[PlannedQuery] = []
    for category in categories:
        targets = markets if category in MARKET_REQUIRED else [None]
        for market in targets:
            market_text = "" if market in (None, INTERNATIONAL) else market
            text = minimize(
                _TEMPLATES[category].format(offer=keywords, market=market_text), forbidden
            )
            for provider in routing.get(category, []):
                planned.append(
                    PlannedQuery(
                        category=category,
                        text=text,
                        provider=provider,
                        market=market,
                        project_id=project_id,
                        subject=subject,
                    )
                )
    return planned


# --- mission et perimetre ----------------------------------------------------------------


class ProblemTarget(DomainModel):
    """R6 (D-73) : probleme a resoudre, tire de l'analyse validee (R4, R5)."""

    idea: str = Field(max_length=200)
    label: str = Field(max_length=120)
    evidence: str = Field(max_length=300)
    origin: str = Field(max_length=80)  # « avis clients : corrobore », « risque (fait »)...
    priority: int = 0  # 0 = le mieux etaye
    source_ids: list[str] = Field(default_factory=list)


class MissionScope(DomainModel):
    objective: str = Field(min_length=3, max_length=300)
    project_ids: list[str] = Field(min_length=1, max_length=5)
    markets: list[str] = Field(default_factory=list)
    categories: list[ResearchCategory] = Field(min_length=1)
    providers: list[str] = Field(min_length=1)
    transmitted: list[str] = Field(min_length=1)  # ce qui part chez les fournisseurs
    max_budget_usd: float = Field(gt=0, le=10)
    max_queries: int = Field(gt=0, le=50)
    max_results_per_query: int = Field(gt=0, le=10)
    validity_days: int = Field(gt=0, le=30)
    simulated: bool = True
    # R3 : idees comparees dans un meme projet (au plus 5), montrees dans l'apercu.
    subjects: list[str] = Field(default_factory=list, max_length=5)
    # R6 : mission de solutions (sujets = problemes traites, rappeles dans l'apercu).
    purpose: Literal["research", "solutions"] = "research"
    problems: list[ProblemTarget] = Field(default_factory=list, max_length=5)
    # D-80 : sujet precis de la recherche, cible et sens homonymes a ecarter, rediges par le
    # modele a partir de la conversation (le titre du projet peut etre provisoire).
    subject: str | None = Field(default=None, max_length=200)
    segment: str | None = Field(default=None, max_length=150)
    exclude_senses: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("categories", "providers", "markets", "project_ids")
    @classmethod
    def _unique(cls, value: list) -> list:
        if len(set(value)) != len(value):
            raise ValueError("valeurs en double")
        return value


def scope_lines(
    scope: MissionScope,
    project_titles: dict[str, str],
    provider_labels: dict[str, str] | None = None,
) -> list[str]:
    """Apercu montre AVANT l'approbation : tout ce que la mission autorise."""
    labels = provider_labels or {}
    specific = [m for m in scope.markets if m != INTERNATIONAL]
    markets = ", ".join(specific) if specific else "international (non spécifique)"
    heading = "Problèmes traités" if scope.purpose == "solutions" else "Idées comparées"
    subjects = (
        [f"{heading} : " + " ; ".join(f"{i}) {s}" for i, s in enumerate(scope.subjects, 1))]
        if scope.subjects
        else []
    )
    described = []
    if scope.subject:
        described.append(f"Sujet : {scope.subject}")
        if scope.segment:
            described.append(f"Clientèle visée : {scope.segment}")
        if scope.exclude_senses:
            described.append("Sens écartés : " + " ; ".join(scope.exclude_senses))
    else:
        described.append(
            "Projet(s) : " + ", ".join(project_titles.get(p, p) for p in scope.project_ids)
        )
    return [
        f"Objectif : {scope.objective}",
        *described,
        *subjects,
        f"Marché(s) : {markets}",
        "Recherches prévues : " + ", ".join(CATEGORY_LABELS[c] for c in scope.categories),
        "Fournisseurs : " + ", ".join(labels.get(p, p) for p in scope.providers),
        "Données transmises : " + " ; ".join(scope.transmitted),
        f"Budget maximal : {scope.max_budget_usd:.2f} $ ; au plus {scope.max_queries} "
        f"recherches de {scope.max_results_per_query} résultats ; valable "
        f"{scope.validity_days} jours",
        "Mode : SIMULÉ (aucun appel réel)"
        if scope.simulated
        else "Mode : recherche web réelle (quotas gratuits protégés)",
    ]


def check_in_scope(
    scope: MissionScope,
    *,
    project_id: str,
    category: ResearchCategory,
    provider: str,
    market: str | None,
) -> None:
    """Toute recherche hors du perimetre approuve est refusee : nouvelle approbation requise."""
    problems = []
    if project_id not in scope.project_ids:
        problems.append("projet")
    if category not in scope.categories:
        problems.append(f"catégorie « {CATEGORY_LABELS[category]} »")
    if provider not in scope.providers:
        problems.append(f"fournisseur « {provider} »")
    if market not in (None, INTERNATIONAL) and market not in scope.markets:
        problems.append(f"marché « {market} »")
    if problems:
        raise DomainError(
            ErrorCode.VALIDATION_ERROR,
            "Hors du périmètre approuvé (" + ", ".join(problems) + ") : une nouvelle "
            "approbation est nécessaire.",
        )


def scope_extension(old: MissionScope, new: MissionScope) -> list[str]:
    """Ce qu'une nouvelle mission ajoute a l'ancienne : a montrer avant l'approbation."""
    added = []
    for name in ("project_ids", "markets", "categories", "providers"):
        extra = [v for v in getattr(new, name) if v not in getattr(old, name)]
        if extra:
            added.append(f"{name} : {', '.join(map(str, extra))}")
    for name in ("max_budget_usd", "max_queries", "max_results_per_query", "validity_days"):
        if getattr(new, name) > getattr(old, name):
            added.append(f"{name} : {getattr(old, name)} → {getattr(new, name)}")
    if old.simulated and not new.simulated:
        added.append("passage en mode réel")
    return added


# --- sources et constats ------------------------------------------------------------------

_SUSPICIOUS = re.compile(
    r"ignore[sz]? (tes|les|vos|toutes les) (r[èe]gles|instructions|consignes)|system prompt|"
    r"tu es d[ée]sormais|confirme (toi-m[êe]me|le plan)|nouvelle consigne",
    re.I,
)


class SourceRecord(DomainModel):
    id: str
    query_id: str
    category: ResearchCategory
    provider: str
    url: str = Field(min_length=8, max_length=2000)
    domain: str
    title: str = Field(max_length=300)
    excerpt: str = Field(max_length=MAX_EXCERPT)
    published_date: date | None = None
    retrieved_at: datetime
    market: str | None = None
    content_hash: str
    suspicious: bool = False  # contient une consigne : reste une donnee, signalee
    simulated: bool = True


def excerpt_of(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= MAX_EXCERPT else text[: MAX_EXCERPT - 1].rstrip() + "…"


def domain_of(url: str) -> str:
    match = re.match(r"https?://([^/:?#]+)", url)
    return (match.group(1) if match else url).lower().removeprefix("www.")


def content_hash(url: str, excerpt: str) -> str:
    return hashlib.sha256(f"{url}\n{excerpt}".encode()).hexdigest()


def is_suspicious(text: str) -> bool:
    return bool(_SUSPICIOUS.search(text or ""))


class FindingCandidate(DomainModel):
    """Ce qu'un extracteur (modele en R3, simulation en R1) propose : jamais publie tel quel."""

    category: ResearchCategory
    statement: str = Field(min_length=3, max_length=500)
    nature: Nature
    source_ids: list[str] = Field(default_factory=list)
    quotes: list[str] = Field(default_factory=list, max_length=5)


class Finding(DomainModel):
    id: str
    category: ResearchCategory
    statement: str
    nature: Nature
    proposed_nature: Nature
    source_ids: list[str]
    quotes: list[str]
    confidence: str
    flags: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


_NUMBER = re.compile(r"(?<![\w])\d+(?:[.,]\d+)?")
_APOS = "\u2019"  # apostrophe typographique
_NAME = re.compile(
    rf"(?<![\w{_APOS}'])[A-ZÉÈÀÂÎÔ][\w{_APOS}'-]*"
    rf"(?:\s+(?:d['{_APOS}]|de\s+|du\s+)?[A-ZÉÈÀÂÎÔ][\w{_APOS}'-]*)*"
)
_COMMON = {
    "le", "la", "les", "un", "une", "des", "en", "au", "aux", "pour", "sur", "dans", "selon",
    "ce", "cette", "ces", "il", "elle", "ils", "elles", "on", "plusieurs", "certains",
    "nous", "vous", "leur", "leurs", "chaque", "tous", "toutes", "après", "avant",
}  # fmt: skip
_MONEY = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:€|euros?|\$|mad|dh|dirhams?|tnd|dinars?)", re.I)


def _norm(text: str) -> str:
    return " ".join(_fold(text).replace(_APOS, "'").split())


def _names(statement: str, markets: Iterable[str]) -> set[str]:
    known = {_norm(m) for m in markets} | {_norm(c) for c in _COUNTRIES.values()}
    names = set()
    for match in _NAME.finditer(statement):
        name = match.group(0).strip()
        if match.start() == 0 and " " not in name:
            continue  # premier mot de la phrase : majuscule de position
        if _norm(name) in _COMMON or _norm(name) in known:
            continue
        names.add(name)
    return names


def validate_finding(
    candidate: FindingCandidate,
    sources: dict[str, SourceRecord],
    *,
    finding_id: str,
    project_markets: Iterable[str] = (),
) -> Finding:
    """Regles de preuve appliquees par le code (aucune invention publiee)."""
    markets = [m for m in project_markets if m]
    reasons: list[str] = []
    flags: list[str] = []
    cited = [sources[s] for s in candidate.source_ids if s in sources]
    if len(cited) != len(candidate.source_ids):
        reasons.append("sources inconnues retirées")
    corpus = _norm(" ".join(f"{s.title} {s.excerpt}" for s in cited))
    quotes = [q[:MAX_QUOTE] for q in candidate.quotes if q and _norm(q[:MAX_QUOTE]) in corpus]
    if len(quotes) != len(candidate.quotes):
        reasons.append("citations absentes des sources retirées")
    nature = candidate.nature
    if nature is not Nature.HYPOTHESIS and not cited:
        nature = Nature.HYPOTHESIS
        reasons.append("aucune source : hypothèse")
    if nature is Nature.FACT and not quotes:
        nature = Nature.HYPOTHESIS
        reasons.append("aucune citation vérifiable : hypothèse")
    numbers = {n.replace(",", ".") for n in _NUMBER.findall(candidate.statement)}
    in_sources = {n.replace(",", ".") for n in _NUMBER.findall(corpus)}
    if nature is Nature.FACT and numbers - in_sources:
        nature = Nature.ESTIMATE
        reasons.append("chiffre absent des sources : estimation")
    invented = {n for n in _names(candidate.statement, markets) if _norm(n) not in corpus}
    if invented and nature is not Nature.HYPOTHESIS:
        nature = Nature.HYPOTHESIS
        reasons.append("nom absent des sources (" + ", ".join(sorted(invented)) + ") : hypothèse")
    if any(s.published_date is None for s in cited):
        flags.append("date inconnue")
    if (
        markets
        and INTERNATIONAL not in markets
        and any(s.market and s.market not in markets for s in cited)
    ):
        flags.append("autre marché")
    if any(s.suspicious for s in cited):
        flags.append("source contenant une consigne (ignorée)")
    if any(s.simulated for s in cited):
        flags.append("simulé")
    domains = {s.domain for s in cited}
    confidence = {
        Nature.FACT: "élevée" if len(domains) >= 2 else "moyenne",
        Nature.ESTIMATE: "faible",
        Nature.HYPOTHESIS: "à vérifier",
    }[nature]
    return Finding(
        id=finding_id,
        category=candidate.category,
        statement=candidate.statement,
        nature=nature,
        proposed_nature=candidate.nature,
        source_ids=[s.id for s in cited],
        quotes=quotes,
        confidence=confidence,
        flags=flags,
        reasons=reasons,
    )


def mark_contradictions(findings: list[Finding], tolerance: float = 0.2) -> list[Finding]:
    """Prix incompatibles entre constats de sources differentes : signales, confiance abaissee
    (fourchette affichee avec les sources)."""
    priced = []
    for finding in findings:
        if finding.category is ResearchCategory.PRICES and finding.nature is not Nature.HYPOTHESIS:
            values = [float(v.replace(",", ".")) for v in _MONEY.findall(finding.statement)]
            if values:
                priced.append((finding, min(values), max(values)))
    contradicted: set[str] = set()
    for i, (a, a_low, _) in enumerate(priced):
        for b, b_low, _ in priced[i + 1 :]:
            if set(a.source_ids) & set(b.source_ids):
                continue
            low, high = sorted((a_low, b_low))
            if low > 0 and (high - low) / low > tolerance:
                contradicted |= {a.id, b.id}
    if not contradicted:
        return findings
    return [
        f.model_copy(update={"flags": [*f.flags, "contradictoire"], "confidence": "faible"})
        if f.id in contradicted
        else f
        for f in findings
    ]


# --- mission enregistree -------------------------------------------------------------------


class ResearchMission(DomainModel):
    id: str
    user_id: str
    status: MissionStatus
    scope: MissionScope
    briefs: dict[str, ResearchBrief]  # par projet
    planned: list[PlannedQuery]
    preview: list[str]
    scope_hash: str
    parent_mission_id: str | None = None
    spent_usd: float = 0.0
    queries_used: int = 0
    created_at: UtcDatetime
    expires_at: UtcDatetime
    approved_at: UtcDatetime | None = None
    valid_until: UtcDatetime | None = None
    decided_at: UtcDatetime | None = None
    finished_at: UtcDatetime | None = None

    @property
    def simulated(self) -> bool:
        return self.scope.simulated

    @property
    def remaining_usd(self) -> float:
        return max(0.0, round(self.scope.max_budget_usd - self.spent_usd, 6))


class QueryRecord(DomainModel):
    id: str
    mission_id: str
    user_id: str
    project_id: str
    category: ResearchCategory
    provider: str
    market: str | None
    text: str
    status: str
    estimated_cost_usd: float
    result_count: int
    error: str | None = None
    simulated: bool = True
    created_at: UtcDatetime
    actual_cost_usd: float | None = None  # cout annonce par le service (R2)
    error_kind: str | None = None  # auth, rate_limited, quota, error
    subject: str | None = None  # R3 : idee comparee
    blocked_count: int = 0  # R5 : resultats ecartes (sites non autorises)


def mission_fingerprint(scope: MissionScope, planned: list[PlannedQuery]) -> str:
    """Empreinte de ce que l'utilisateur voit et approuve : perimetre ET requetes exactes."""
    payload = json.dumps(
        {
            "scope": scope.model_dump(mode="json"),
            "planned": [q.model_dump(mode="json") for q in planned],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()
