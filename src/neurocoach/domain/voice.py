"""Voix des clients (R5, D-72) : themes recurrents tires des avis, temoignages et plaintes.

Regles appliquees par le code, sans modele :
- une phrase n'est retenue que si elle est citee mot pour mot d'une source stockee ;
- un theme est une **tendance corroboree** seulement s'il apparait sur au moins deux sites
  differents ; repete sur un seul site, c'est un **signal d'un seul site** ; une seule
  mention, un **temoignage individuel** ;
- des avis positifs et negatifs sur un meme theme sont signales **avis partages** ;
- un avis qui ressemble a de la promotion (code promo, appel a l'achat, superlatifs) est
  ecarte ; un texte copie a l'identique sur plusieurs sites n'est compte qu'une fois ;
- rien n'est invente : sans source d'avis, le rapport le dit.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Literal

from pydantic import Field

from neurocoach.domain.models import DomainModel
from neurocoach.domain.research import VOICE_CATEGORIES, ResearchCategory, SourceRecord, _norm

Status = Literal["corrobore", "a_confirmer", "meme_site", "isole", "vendeur"]
Origin = Literal["independant", "vendeur", "promotionnel", "inconnu"]
Sentiment = Literal["negatif", "positif", "partage"]
STATUS_LABELS = {
    "corrobore": "tendance corroborée",
    "a_confirmer": "signal sur plusieurs sites, indépendance non établie",
    "meme_site": "signal d'un seul site",
    "isole": "témoignage individuel",
    "vendeur": "avis affichés par des vendeurs (non indépendants)",
}
ORIGIN_LABELS = {
    "independant": "indépendant",
    "vendeur": "publié par un vendeur",
    "promotionnel": "promotionnel",
    "inconnu": "origine incertaine",
}
STATUS_ORDER = {"corrobore": 0, "a_confirmer": 1, "meme_site": 2, "isole": 3, "vendeur": 4}
SENTIMENT_LABELS = {"negatif": "négatif", "positif": "positif", "partage": "avis partagés"}

THEMES: dict[str, tuple[str, re.Pattern[str]]] = {
    "prix": (
        "Prix",
        re.compile(
            r"\bcher|\bprix\b|\btarifs?\b|co[uû]te?u?x?\b|on[ée]reu|abordable|"
            r"rapport qualit[ée]",
            re.I,
        ),
    ),
    "delais": (
        "Délais et livraison",
        re.compile(
            r"d[ée]lais?|livraison|livr[ée]|attente|"
            r"attendu|retard|\blent",
            re.I,
        ),
    ),
    "qualite": (
        "Qualité",
        re.compile(
            r"qualit[ée]|fragile|cass|solide|durable|d[ée]faut|"
            r"abîm|coule|tient",
            re.I,
        ),
    ),
    "service": (
        "Service client",
        re.compile(
            r"service client|\bsav\b|accueil|joignable|"
            r"r[ée]ponse|contact",
            re.I,
        ),
    ),
    "disponibilite": (
        "Disponibilité de l'offre",
        re.compile(
            r"introuvable|disponib|rupture|stock|pr[èe]s de chez|proximit[ée]|offre adapt", re.I
        ),
    ),
    "simplicite": (
        "Simplicité",
        re.compile(
            r"compliqu|difficile|simple|facile|prise en main|"
            r"ergonom|intuiti",
            re.I,
        ),
    ),
    "confiance": (
        "Confiance et sécurité",
        re.compile(
            r"arnaque|confiance|s[ée]curit|fiable|"
            r"rassur",
            re.I,
        ),
    ),
    "sensoriel": (
        "Goût, odeur, apparence",
        re.compile(
            r"odeur|parfum|\bsent(ent)?\b|go[uû]t|saveur|"
            r"apparence|joli",
            re.I,
        ),
    ),
}
NEGATIVE = re.compile(
    r"d[ée]çu|d[ée]cevant|plain|probl[èe]me|regrett|trop (cher|long|lent)|jamais|mauvais|"
    r"arnaque|retard|cass|frustr|ne trouv|pas trouv|introuvable|compliqu|difficile|n'ai pas|"
    r"aucune r[ée]ponse|attendu|coule|sent peu|inutile|d[ée]faut",
    re.I,
)
POSITIVE = re.compile(
    r"satisfait|ravi|excellent|recommand|g[ée]nial|parfait|appr[ée]ci|saluent|top\b|super\b|"
    r"rapide|facile|simple|fiable|qualit[ée] (est |)(excellente|irr[ée]prochable)|adore",
    re.I,
)
PROMOTIONAL = re.compile(
    r"code promo|achetez (maintenant|vite)|cliquez|offre exclusive|lien en bio|sponsoris|"
    r"partenariat r[ée]mun|affili|meilleure? (produit|service|offre) (du|au) monde|"
    r"!!!|100 ?% (satisfait|garanti)",
    re.I,
)
# Finalisation (11/11/2026) : la recette reelle a montre des « avis » qui etaient des textes
# de marque ou des temoignages choisis et affiches par le vendeur lui-meme.
INDEPENDENT_SITE = re.compile(
    r"forum|communaut|discussion|entraide|question|avis-|-avis|comparatif|blog|magazine|"
    r"journal|actu|presse|60millions|quechoisir|ufc|consommat|temoignage|t[ée]moignage",
    re.I,
)
VENDOR_MARKERS = re.compile(
    r"ajouter au panier|\bpanier\b|livraison (offerte|gratuite)|"
    r"\bnotre (boutique|atelier|gamme|collection|marque|savoir-faire|entreprise|maison)|"
    r"\bnos (bougies|cr[ée]ations|produits|clients|collections|parfums|mod[eè]les)|"
    r"d[ée]couvrez (notre|nos)|commandez|en stock|vente en gros|boutique en ligne|"
    r"avis v[ée]rifi[ée]s|\d[,.]\d/5 sur|fabriqu[ée]e?s? (dans notre|par nos|par nous)",
    re.I,
)
BRAND_VOICE = re.compile(r"\b(notre|nos|nous)\b", re.I)
VENDOR_HOST = re.compile(r"boutique|shop|store|atelier|maison|creations?", re.I)
RATING_WIDGET = re.compile(r"\b[1-5](?:[.,]\d)?/5\b")
TESTIMONY = re.compile(
    r"\b(je|j'|j\u2019|mon|ma|mes|moi)\b|\bclients?\b|\bacheteu?r?s?|\butilisat|\d/5\b|★",
    re.I,
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_CLAUSE = re.compile(r"\s+mais\s+|\s*;\s*|,\s+(?:et\s+)?(?=\w)", re.I)
MAX_MENTIONS = 4


class VoiceMention(DomainModel):
    source_id: str
    domain: str
    sentence: str
    sentiment: Literal["negatif", "positif", "mixte"]
    origin: Origin = "inconnu"


class VoiceTheme(DomainModel):
    theme: str
    label: str
    sentiment: Sentiment
    status: Status
    domains: list[str]  # sites non commerciaux (independants ou d'origine incertaine)
    mentions: list[VoiceMention] = Field(default_factory=list)
    vendor_domains: list[str] = Field(default_factory=list)  # vendeurs : jamais comptes
    independent_domains: list[str] = Field(default_factory=list)
    contradiction: str | None = None

    @property
    def is_problem(self) -> bool:
        return self.sentiment in ("negatif", "partage") and self.status != "vendeur"


class VoiceReport(DomainModel):
    themes: list[VoiceTheme] = Field(default_factory=list)
    voice_sources: int = 0
    promotional: list[str] = Field(default_factory=list)  # sources ecartees
    vendor_sources: list[str] = Field(default_factory=list)  # avis publies par un vendeur
    independent_sources: int = 0
    brand_texts: int = 0  # textes commerciaux de vendeurs, ignores (ce ne sont pas des avis)
    duplicates: int = 0
    notes: list[str] = Field(default_factory=list)

    def problem_targets(self) -> list[VoiceTheme]:
        """Prepare R6 : frustrations et besoins non satisfaits, les mieux etayes d'abord.
        Un theme porte seulement par des vendeurs n'est jamais un probleme a traiter."""
        problems = [t for t in self.themes if t.is_problem]
        return sorted(problems, key=lambda t: (STATUS_ORDER[t.status], -len(t.domains)))


def is_promotional(text: str) -> bool:
    return bool(PROMOTIONAL.search(text or ""))


def _stem(domain: str) -> str:
    parts = domain.split(".")
    return parts[-2] if len(parts) >= 2 else domain


def source_origin(
    source: SourceRecord, vendor_domains: Iterable[str] = (), offer_terms: Iterable[str] = ()
) -> Origin:
    """Origine d'un avis, par le code : promotionnel, publie par un vendeur (site d'un
    concurrent, boutique, voix de marque), independant (forum, comparatif, presse), sinon
    incertaine. Prudence : un site incertain ne suffit jamais seul a etablir une tendance."""
    text = f"{source.title} {source.excerpt}"
    if is_promotional(text):
        return "promotionnel"
    if INDEPENDENT_SITE.search(source.domain) or INDEPENDENT_SITE.search(source.title):
        return "independant"
    stem = _stem(source.domain).lower()
    folded = text.lower()
    if (
        source.domain in set(vendor_domains)
        or VENDOR_MARKERS.search(text)
        or len(BRAND_VOICE.findall(text)) >= 2
        or VENDOR_HOST.search(stem)  # boutique en ligne, atelier, marque
        or (len(stem) >= 4 and stem.replace("-", " ") in folded)  # le site parle de lui-meme
        or len(RATING_WIDGET.findall(text)) >= 2  # bloc d'avis affiche par une boutique
        or any(len(t) >= 5 and t.lower() in stem for t in offer_terms)  # vend le produit
    ):
        return "vendeur"
    return "inconnu"


def offer_terms_of(text: str) -> list[str]:
    """Mots du produit etudie (« bougies » -> « bougie ») : un site qui les porte dans son nom
    de domaine vend ce produit."""
    words = re.findall(r"[a-zà-ÿ]{5,}", (text or "").lower())
    return list(dict.fromkeys(w.rstrip("s") for w in words))[:8]


def classify_sources(
    sources: Iterable[SourceRecord], offer_terms: Iterable[str] = ()
) -> dict[str, Origin]:
    """Origine de chaque source ; les sites des concurrents trouves sont des vendeurs."""
    items = list(sources)
    terms = list(offer_terms)
    vendors = {s.domain for s in items if s.category is ResearchCategory.COMPETITION}
    return {s.id: source_origin(s, vendors, terms) for s in items}


def _sentiment(sentence: str) -> Literal["negatif", "positif", "mixte"] | None:
    neg, pos = bool(NEGATIVE.search(sentence)), bool(POSITIVE.search(sentence))
    if neg and pos:
        return "mixte"
    if neg:
        return "negatif"
    if pos:
        return "positif"
    return None


def analyze_voice(sources: Iterable[SourceRecord], offer: str = "") -> VoiceReport:
    every = list(sources)
    origins = classify_sources(every, offer_terms_of(offer))
    pool = [s for s in every if s.category in VOICE_CATEGORIES and s.excerpt.strip()]
    pool = [s for s in pool if not s.suspicious]
    promotional = [s.id for s in pool if origins[s.id] == "promotionnel"]
    vendor_sources = [s.id for s in pool if origins[s.id] == "vendeur"]
    seen_text: set[str] = set()
    duplicates = 0
    brand_texts = 0
    by_theme: dict[str, list[VoiceMention]] = {}
    for source in pool:
        origin = origins[source.id]
        if origin == "promotionnel":
            continue
        for sentence in _SENTENCE.split(source.excerpt):
            sentence = sentence.strip()
            if len(sentence) < 12:
                continue
            if origin == "vendeur" and not TESTIMONY.search(sentence):
                # Texte de marque (« notre gamme… ») : pas un avis client.
                brand_texts += 1
                continue
            key = _norm(re.sub(r"^\(simulation\)\s*", "", sentence, flags=re.I))
            # Theme et sentiment par proposition : « saluent la qualite MAIS regrettent les
            # delais » est positif sur la qualite et negatif sur les delais.
            pairs: dict[str, str] = {}
            for clause in _CLAUSE.split(sentence):
                feeling = _sentiment(clause)
                if feeling is None:
                    continue
                for name, (_, rx) in THEMES.items():
                    if rx.search(clause):
                        previous = pairs.get(name)
                        pairs[name] = feeling if previous in (None, feeling) else "mixte"
            if not pairs:
                continue
            if key in seen_text:
                duplicates += 1  # texte copie a l'identique : compte une seule fois
                continue
            seen_text.add(key)
            for theme, sentiment in pairs.items():
                by_theme.setdefault(theme, []).append(
                    VoiceMention(
                        source_id=source.id,
                        domain=source.domain,
                        sentence=sentence[:300],
                        sentiment=sentiment,
                        origin=origin,  # type: ignore[arg-type]
                    )
                )
    themes = []
    for name, mentions in by_theme.items():
        neutral = [m for m in mentions if m.origin != "vendeur"]
        vendor = [m for m in mentions if m.origin == "vendeur"]
        domains = sorted({m.domain for m in neutral})
        independent = sorted({m.domain for m in neutral if m.origin == "independant"})
        counted = neutral or vendor  # le sentiment vient des avis non commerciaux s'il y en a
        kinds = {m.sentiment for m in counted}
        if "mixte" in kinds or {"negatif", "positif"} <= kinds:
            sentiment: Sentiment = "partage"
        else:
            sentiment = "negatif" if "negatif" in kinds else "positif"
        # Corroboration renforcee : au moins deux sites non commerciaux, dont un independant
        # reconnu (ou trois sites). Les avis affiches par des vendeurs ne comptent jamais.
        if len(domains) >= 2 and (independent or len(domains) >= 3):
            status: Status = "corrobore"
        elif len(domains) >= 2:
            status = "a_confirmer"
        elif len(neutral) >= 2:
            status = "meme_site"
        elif neutral:
            status = "isole"
        else:
            status = "vendeur"
        contradiction = None
        vendor_kinds = {m.sentiment for m in vendor}
        neutral_kinds = {m.sentiment for m in neutral}
        if "positif" in vendor_kinds and "negatif" in neutral_kinds:
            contradiction = (
                "les vendeurs affichent des avis positifs que des avis non commerciaux contredisent"
            )
        themes.append(
            VoiceTheme(
                theme=name,
                label=THEMES[name][0],
                sentiment=sentiment,
                status=status,
                domains=domains,
                mentions=(neutral + vendor)[:MAX_MENTIONS],
                vendor_domains=sorted({m.domain for m in vendor}),
                independent_domains=independent,
                contradiction=contradiction,
            )
        )
    themes.sort(key=lambda t: (STATUS_ORDER[t.status], -len(t.mentions), t.theme))
    notes = []
    independent_count = sum(1 for s in pool if origins[s.id] == "independant")
    if not pool:
        notes.append("Aucun avis ni témoignage exploitable dans les sources : rien n'est supposé.")
    elif not themes:
        notes.append("Les avis trouvés ne dégagent aucun thème récurrent identifiable.")
    if pool and not [s for s in pool if origins[s.id] not in ("vendeur", "promotionnel")]:
        notes.append(
            "Aucun avis indépendant : les avis trouvés sont publiés par des vendeurs ; aucune "
            "tendance n'en est tirée."
        )
    if vendor_sources:
        notes.append(
            f"{len(vendor_sources)} source(s) d'avis publiée(s) par des vendeurs, non comptée(s) "
            "comme indépendante(s)."
        )
    if brand_texts:
        notes.append(f"{brand_texts} texte(s) commercial(aux) de vendeurs ignoré(s) : ce ne sont "
                     "pas des avis.")  # fmt: skip
    if promotional:
        notes.append(f"{len(promotional)} avis d'apparence promotionnelle écarté(s).")
    if duplicates:
        notes.append(f"{duplicates} témoignage(s) copié(s) à l'identique compté(s) une fois.")
    return VoiceReport(themes=themes, voice_sources=len(pool), promotional=promotional,
                       vendor_sources=vendor_sources, independent_sources=independent_count,
                       brand_texts=brand_texts, duplicates=duplicates,
                       notes=notes)  # fmt: skip
