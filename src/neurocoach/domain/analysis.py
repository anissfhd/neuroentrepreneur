"""Analyse des recherches (R4, D-71) : schemas du modele de strategie et regles de preuve.

Le modele de strategie (role ``strategy``) propose une analyse par idee puis une comparaison.
Rien n'est publie tel quel : le code valide chaque affirmation contre les sources stockees.
- un « fait » exige une source et une citation presente dans l'extrait cite (regles de R1) ;
- un chiffre absent des sources devient une estimation ; un nom absent, une hypothese ;
- un concurrent absent des sources est retire ; un prix ou une opportunite sans source aussi ;
- l'« avis du coach » (jugement) est permis pour les avantages, inconvenients et risques,
  sans chiffre ni nom absents des sources ;
- l'adequation au profil n'utilise que ce que l'utilisateur a dit : sinon « inconnu » ;
- la confiance de la recommandation est plafonnee par la quantite de faits sources, et les
  formules de certitude sont retirees.
Domaine pur : aucune entree-sortie.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from neurocoach.domain.models import DomainModel, UtcDatetime
from neurocoach.domain.research import (
    _MONEY,
    FindingCandidate,
    Nature,
    ResearchCategory,
    SourceRecord,
    _names,
    _norm,
    mark_contradictions,
    validate_finding,
)
from neurocoach.domain.voice import VoiceReport, VoiceTheme

Kind = Literal["fait", "estimation", "hypothese", "avis"]
Evidence = Literal["suffisant", "partiel", "insuffisant"]
EVIDENCE_ORDER = {"insuffisant": 0, "partiel": 1, "suffisant": 2}
# D-80 : un prix est un montant chiffre avec sa monnaie (« 30 € », « 25 euros/h », « $40 ») ;
# une phrase sur la facon de fixer ses tarifs n'en est pas un (recette du 12/11/2026).
PRICE_AMOUNT = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:€|euros?\b|eur\b|\$|usd\b|dh\b|dirhams?\b|tnd\b|chf\b|fcfa\b)"
    r"|(?:€|\$)\s*\d",
    re.I,
)
Rating = Literal["favorable", "mitige", "defavorable", "inconnu"]
Criterion = Literal["budget", "temps", "competences", "objectifs"]
Confidence = Literal["faible", "moyenne", "elevee"]
Text300 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]
ShortId = Annotated[str, StringConstraints(strip_whitespace=True, max_length=12)]

KIND_LABELS = {
    "fait": "Fait sourcé",
    "estimation": "Estimation",
    "hypothese": "Hypothèse à vérifier",
    "avis": "Avis du coach",
}
RATING_LABELS = {
    "favorable": "favorable",
    "mitige": "mitigé",
    "defavorable": "défavorable",
    "inconnu": "inconnu (information non fournie)",
}
CRITERION_LABELS = {
    "budget": "Budget",
    "temps": "Temps",
    "competences": "Compétences",
    "objectifs": "Objectifs",
}
CONFIDENCE_LABELS = {"faible": "faible", "moyenne": "moyenne", "elevee": "élevée"}
SECTIONS = (
    "strengths", "weaknesses", "needs", "prices", "opportunities", "risks",
)  # fmt: skip
SECTION_LABELS = {
    "strengths": "Avantages",
    "weaknesses": "Inconvénients",
    "needs": "Besoins et problèmes des clients",
    "prices": "Prix observés",
    "opportunities": "Opportunités",
    "risks": "Risques",
}
SECTION_CATEGORY = {
    "strengths": ResearchCategory.MARKET,
    "weaknesses": ResearchCategory.PROBLEMS,
    "needs": ResearchCategory.PROBLEMS,
    "prices": ResearchCategory.PRICES,
    "opportunities": ResearchCategory.MARKET,
    "risks": ResearchCategory.PROBLEMS,
}
OPINION_SECTIONS = frozenset({"strengths", "weaknesses", "risks"})  # jugement du coach permis
SOURCED_ONLY = frozenset({"prices", "opportunities"})  # jamais sans source
CERTAINTY = re.compile(
    r"\b(sans aucun doute|sans doute possible|certainement|assur[ée]ment|garanti[es]?|"
    r"à coup sûr|a coup sur|forc[ée]ment|indiscutablement|sans risque)\b",
    re.I,
)
GENERIC = re.compile(
    r"(faites|dressez|établissez) (une|la) liste (des|de vos) (avantages|points)|"
    r"pesez le pour et le contre|tout dépend de vos objectifs|cela dépend de vous|"
    r"chaque idée a ses avantages et ses inconvénients",
    re.I,
)
_NUMBER = re.compile(r"(?<![\w])\d+(?:[.,]\d+)?")


_ALIAS = re.compile(r"\bS(\d{1,2})\b")
_END_MARKS = ".!?…»)"


def dealias(text: str, aliases: dict[str, str], sources: dict[str, SourceRecord]) -> str:
    """Recette du 10/11/2026 : le modele cite parfois ses sources par leur identifiant court
    (« S1, S2 »), qui n'a aucun sens pour l'utilisateur : il est remplace par le site."""

    def name(match: re.Match[str]) -> str:
        source = sources.get(aliases.get(f"S{match.group(1)}", ""))
        return source.domain if source is not None else match.group(0)

    return _ALIAS.sub(name, text)


def finish(text: str, limit: int) -> str:
    """Meme recette : pour tenir dans la limite du schema (``limit`` caracteres), le modele
    coupe un texte en plein mot. Seul un texte qui ATTEINT cette limite est considere comme
    coupe : la phrase inachevee est retiree ; a defaut, il s'arrete au dernier mot entier. Un
    texte plus court sans point final (titre, fragment) est laisse tel quel."""
    text = text.strip()
    if not text or text[-1] in _END_MARKS or len(text) < limit - 3:
        return text
    end = max(text.rfind(mark) for mark in ".!?…")
    if end >= len(text) * 0.5:
        return text[: end + 1]
    cut = text.rfind(" ")
    return (text[:cut] if cut > 0 else text).rstrip(" ,;:(") + "…"


# --- sorties attendues du modele (schemas structures) --------------------------------------


class _LLM(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClaimDraft(_LLM):
    text: Text300
    kind: Kind
    sources: list[ShortId] = Field(default_factory=list, max_length=4)
    quote: str | None = Field(default=None, max_length=300)
    # D-83 : pour un prix, l'offre est-elle de meme nature, taille et cible que l'idee ?
    # (recette reelle : 60 000 EUR de deploiement presente comme prix d'un audit court)
    comparable: bool | None = None


class CompetitorDraft(_LLM):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]
    positioning: str = Field(default="", max_length=200)
    sources: list[ShortId] = Field(min_length=1, max_length=3)


class PainPointDraft(_LLM):
    """R5 : frustration, besoin non satisfait ou attente, cite mot pour mot d'un avis."""

    theme: str = Field(max_length=60)
    statement: Text300
    scope: Literal["temoignage", "tendance"]
    sources: list[ShortId] = Field(min_length=1, max_length=4)
    quote: str = Field(max_length=300)


class FitDraft(_LLM):
    criterion: Criterion
    rating: Rating
    reason: str = Field(default="", max_length=250)


class IdeaAnalysisDraft(_LLM):
    summary: str = Field(max_length=400)
    strengths: list[ClaimDraft] = Field(default_factory=list, max_length=5)
    weaknesses: list[ClaimDraft] = Field(default_factory=list, max_length=5)
    competitors: list[CompetitorDraft] = Field(default_factory=list, max_length=6)
    needs: list[ClaimDraft] = Field(default_factory=list, max_length=4)
    prices: list[ClaimDraft] = Field(default_factory=list, max_length=4)
    opportunities: list[ClaimDraft] = Field(default_factory=list, max_length=4)
    risks: list[ClaimDraft] = Field(default_factory=list, max_length=5)
    unknowns: list[Text300] = Field(default_factory=list, max_length=6)
    fit: list[FitDraft] = Field(default_factory=list, max_length=4)
    pain_points: list[PainPointDraft] = Field(default_factory=list, max_length=6)
    # D-80 : sources jugees hors sujet (autre sens du mot, autre marche, sans rapport) et
    # niveau de preuve juge par le modele ; le code applique l'ecart et plafonne le niveau.
    off_topic: list[ShortId] = Field(default_factory=list, max_length=30)
    evidence: Evidence = "partiel"


class RankDraft(_LLM):
    idea: int = Field(ge=1, le=5)
    rank: int = Field(ge=1, le=5)
    rationale: str = Field(max_length=300)


class ComparisonDraft(_LLM):
    ranking: list[RankDraft] = Field(default_factory=list, max_length=5)
    trade_offs: list[Text300] = Field(default_factory=list, max_length=4)
    recommended_idea: int | None = Field(default=None, ge=1, le=5)
    reasoning: str = Field(max_length=700)
    confidence: Confidence
    conditions: list[Text300] = Field(default_factory=list, max_length=4)
    next_checks: list[Text300] = Field(default_factory=list, max_length=4)


# --- analyse validee -----------------------------------------------------------------------


class Claim(DomainModel):
    text: str
    kind: Kind
    proposed_kind: Kind
    source_ids: list[str] = Field(default_factory=list)
    quotes: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    comparable: bool | None = None


class Competitor(DomainModel):
    name: str
    positioning: str
    source_ids: list[str]


class PainPoint(DomainModel):
    theme: str
    statement: str
    scope: Literal["temoignage", "tendance"]
    proposed_scope: Literal["temoignage", "tendance"]
    source_ids: list[str]
    quote: str
    domains: list[str]


class Fit(DomainModel):
    criterion: Criterion
    rating: Rating
    reason: str


class IdeaAnalysis(DomainModel):
    idea: str
    available: bool = True  # faux si le modele n'a pas pu produire d'analyse valide
    summary: str = ""
    sections: dict[str, list[Claim]] = Field(default_factory=dict)
    competitors: list[Competitor] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    fit: list[Fit] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)  # ce que le code a retire, et pourquoi
    source_count: int = 0
    voice: VoiceReport | None = None  # R5 : themes recurrents, calcules par le code
    pain_points: list[PainPoint] = Field(default_factory=list)  # R5 : lecture du modele
    # D-80 : niveau de preuve (plafonne par le code) et sources ecartees comme hors sujet.
    evidence: Literal["suffisant", "partiel", "insuffisant", "inconnu"] = "inconnu"
    off_topic_count: int = 0

    @property
    def sourced_facts(self) -> int:
        return sum(1 for claims in self.sections.values() for c in claims if c.kind == "fait")

    def solution_targets(self) -> list[Claim]:
        """Prepare R6 : inconvenients, besoins et risques auxquels chercher des solutions."""
        return [c for key in ("weaknesses", "needs", "risks") for c in self.sections.get(key, [])]

    def customer_problems(self) -> list[VoiceTheme]:
        """Prepare R6 : frustrations des clients, tendances corroborees d'abord."""
        return self.voice.problem_targets() if self.voice else []


class Ranking(DomainModel):
    idea: str
    rank: int
    rationale: str


class Comparison(DomainModel):
    ranking: list[Ranking] = Field(default_factory=list)
    trade_offs: list[str] = Field(default_factory=list)
    recommended: str | None = None
    reasoning: str = ""
    confidence: Confidence = "faible"
    proposed_confidence: Confidence = "faible"
    conditions: list[str] = Field(default_factory=list)
    next_checks: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class ResearchAnalysis(DomainModel):
    id: str
    mission_id: str
    user_id: str
    created_at: UtcDatetime
    ideas: list[IdeaAnalysis]
    comparison: Comparison | None = None
    profile: dict[str, list[str]] = Field(default_factory=dict)
    sources_hash: str
    simulated: bool = False

    @property
    def removed_count(self) -> int:
        return sum(len(i.removed) for i in self.ideas)


# --- profil de l'utilisateur (ce qu'il a dit, rien d'autre) -------------------------------

PROFILE_PATTERNS: dict[str, re.Pattern[str]] = {
    "budget": re.compile(
        r"budget|\d+\s*(€|euros?|dh|dirhams?)|sans argent|investi\w*|[ée]conomies|"
        r"pas les moyens|peu d'argent",
        re.I,
    ),
    "temps": re.compile(
        r"\d+\s*(min|minutes|h|heures?)\b|le soir|week-?ends?|temps (plein|partiel)|"
        r"[àa] c[ôo]t[ée]|par (jour|semaine)|disponib",
        re.I,
    ),
    "competences": re.compile(
        r"je sais|je ma[iî]trise|comp[ée]ten|exp[ée]rience|dipl[ôo]m|formation|j'ai travaill|"
        r"m[ée]tier|j'ai d[ée]j[àa]|savoir-faire|j'ai [ée]t[ée] \w+|"
        r"je suis (cuisini|d[ée]velopp|prof|coach|infirm|graphiste|commer[cç]|artisan)",
        re.I,
    ),
    "objectifs": re.compile(
        r"objectif|revenu|vite|rapid|rentab|libert[ée]|impact|compl[ée]ment|stable|"
        r"r[ée]gulier|passion|plaisir|vivre de",
        re.I,
    ),
}


def build_profile(texts: Iterable[str], *, minutes_per_day: int | None = None,
                  target_outcome: str | None = None) -> dict[str, list[str]]:  # fmt: skip
    """Phrases de l'utilisateur utiles a chaque critere ; liste vide = information inconnue."""
    profile: dict[str, list[str]] = {key: [] for key in PROFILE_PATTERNS}
    sentences = [
        " ".join(s.split())[:200]
        for text in texts
        if text
        for s in re.split(r"(?<=[.!?\n])\s+", text)
        if s.strip()
    ]
    for key, pattern in PROFILE_PATTERNS.items():
        for sentence in sentences:
            if pattern.search(sentence) and sentence not in profile[key]:
                profile[key].append(sentence)
    if minutes_per_day:
        profile["temps"].insert(0, f"{minutes_per_day} minutes par jour (projet)")
    if target_outcome:
        profile["objectifs"].insert(0, f"Objectif du projet : {target_outcome}"[:200])
    return {key: values[:3] for key, values in profile.items()}


# --- validation ----------------------------------------------------------------------------


_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def _amount(raw: str) -> float:
    return float(raw.replace(",", "."))


def merged_price_spread(claim: Claim, sources: dict[str, SourceRecord]) -> bool:
    """Recette du 11/11/2026 : le modele fusionne parfois deux prix de sources differentes
    (« entre 9 et 18 € ») dans une seule affirmation, que la comparaison entre affirmations ne
    voit pas. Un ecart de plus de 20 % entre montants repris de sources DIFFERENTES est signale."""
    if len(set(claim.source_ids)) < 2:
        return False
    stated = {_amount(n) for n in _NUMBER.findall(claim.text)}
    origin: dict[float, set[str]] = {}
    for sid in claim.source_ids:
        source = sources.get(sid)
        if source is None:
            continue
        found = {_amount(v) for v in _MONEY.findall(f"{source.title} {source.excerpt}")}
        for value in found & stated:
            origin.setdefault(value, set()).add(source.domain)
    values = sorted(v for v in origin if v > 0)
    return any(
        (high - low) / low > 0.2 and origin[low] != origin[high]
        for i, low in enumerate(values)
        for high in values[i + 1 :]
    )


def _corpus(sources: Iterable[SourceRecord]) -> str:
    return _norm(" ".join(f"{s.title} {s.excerpt}" for s in sources))


def _resolve(ids: Iterable[str], aliases: dict[str, str]) -> list[str]:
    resolved = []
    for raw in ids:
        sid = aliases.get(raw.strip().upper())
        if sid and sid not in resolved:
            resolved.append(sid)
    return resolved


def _validate_claim(
    draft: ClaimDraft,
    section: str,
    aliases: dict[str, str],
    sources: dict[str, SourceRecord],
    markets: list[str],
    removed: list[str],
) -> Claim | None:
    source_ids = _resolve(draft.sources, aliases)
    label = SECTION_LABELS[section]
    if draft.kind == "avis":
        if section not in OPINION_SECTIONS:
            removed.append(f"{label} : avis sans source retiré (« {draft.text[:60]} »)")
            return None
        corpus = _corpus(sources.values())
        numbers = {n.replace(",", ".") for n in _NUMBER.findall(draft.text)}
        known = {n.replace(",", ".") for n in _NUMBER.findall(corpus)}
        invented = {n for n in _names(draft.text, markets) if _norm(n) not in corpus}
        if numbers - known or invented:
            removed.append(f"{label} : avis contenant un chiffre ou un nom non sourcé retiré")
            return None
        return Claim(text=draft.text, kind="avis", proposed_kind="avis", source_ids=source_ids)
    nature = {"fait": Nature.FACT, "estimation": Nature.ESTIMATE, "hypothese": Nature.HYPOTHESIS}
    finding = validate_finding(
        FindingCandidate(
            category=SECTION_CATEGORY[section],
            statement=draft.text,
            nature=nature[draft.kind],
            source_ids=source_ids,
            quotes=[draft.quote] if draft.quote else [],
        ),
        sources,
        finding_id="tmp",
        project_markets=markets,
    )
    kind: Kind = {Nature.FACT: "fait", Nature.ESTIMATE: "estimation",
                  Nature.HYPOTHESIS: "hypothese"}[finding.nature]  # fmt: skip
    if section in SOURCED_ONLY and (kind == "hypothese" or not finding.source_ids):
        removed.append(f"{label} : affirmation non étayée par une source retirée")
        return None
    if kind != draft.kind:
        removed.append(f"{label} : « {draft.text[:60]} » requalifié en {KIND_LABELS[kind]}")
    return Claim(
        text=draft.text,
        kind=kind,
        proposed_kind=draft.kind,
        comparable=draft.comparable,
        source_ids=finding.source_ids,
        quotes=finding.quotes,
        flags=[f for f in finding.flags if f != "simulé"]
        + (["simulé"] if "simulé" in finding.flags else []),
    )


def _validate_pain_point(
    draft: PainPointDraft,
    aliases: dict[str, str],
    sources: dict[str, SourceRecord],
    excluded: set[str],
    removed: list[str],
    vendors: set[str] | None = None,
) -> PainPoint | None:
    ids = [s for s in _resolve(draft.sources, aliases) if s not in excluded]
    cited = [sources[s] for s in ids]
    quote = draft.quote.strip()
    holders = [s for s in cited if quote and _norm(quote) in _norm(f"{s.title} {s.excerpt}")]
    if not holders:
        removed.append(f"Témoignage « {draft.statement[:50]} » retiré : absent des avis cités")
        return None
    corpus = _corpus(cited)
    numbers = {n.replace(",", ".") for n in _NUMBER.findall(draft.statement)}
    if numbers - {n.replace(",", ".") for n in _NUMBER.findall(corpus)}:
        removed.append(f"Témoignage « {draft.statement[:50]} » retiré : chiffre non sourcé")
        return None
    domains = sorted({s.domain for s in cited})
    neutral = sorted({s.domain for s in cited if s.id not in (vendors or set())})
    scope = draft.scope
    if scope == "tendance" and len(neutral) < 2:
        scope = "temoignage"
        why = (
            "des avis publiés par des vendeurs ne font pas une tendance"
            if len(domains) >= 2
            else "un seul site"
        )
        removed.append(
            f"« {draft.theme[:40]} » présenté comme tendance, mais {why} : témoignage individuel"
        )
    return PainPoint(theme=draft.theme, statement=draft.statement, scope=scope,
                     proposed_scope=draft.scope, source_ids=ids, quote=quote,
                     domains=domains)  # fmt: skip


def validate_idea_analysis(
    draft: IdeaAnalysisDraft,
    *,
    idea: str,
    aliases: dict[str, str],
    sources: dict[str, SourceRecord],
    profile: dict[str, list[str]],
    markets: list[str],
    voice: VoiceReport | None = None,
) -> IdeaAnalysis:
    """``aliases`` : identifiants courts montres au modele (S1...) -> identifiants stockes."""
    removed: list[str] = []
    sections: dict[str, list[Claim]] = {}
    # D-80 : une source jugee hors sujet n'etaye plus rien (affirmations, concurrents, avis).
    off_topic = set(_resolve(draft.off_topic, aliases)) & set(sources)
    if off_topic:
        sources = {sid: s for sid, s in sources.items() if sid not in off_topic}
        removed.append(f"{len(off_topic)} source(s) jugée(s) hors sujet écartée(s)")

    def off_topic_only(item: ClaimDraft, section: str) -> bool:
        cited = set(_resolve(item.sources, aliases))
        if cited and cited <= off_topic:
            removed.append(
                f"{SECTION_LABELS[section]} : « {item.text[:60]} » retiré : appuyé sur une "
                "source hors sujet"
            )
            return True
        return False

    for section in SECTIONS:
        claims = [
            claim
            for d in getattr(draft, section)
            if not off_topic_only(d, section)
            and (claim := _validate_claim(d, section, aliases, sources, markets, removed))
        ]
        sections[section] = claims
    # D-80 : un prix doit etre un montant chiffre, present dans une source citee.
    priced = []
    for claim in sections["prices"]:
        cited = " ".join(f"{sources[s].title} {sources[s].excerpt or ''}" for s in claim.source_ids
                         if s in sources)  # fmt: skip
        if PRICE_AMOUNT.search(claim.text) and PRICE_AMOUNT.search(cited):
            if not claim.comparable:
                # Garde, mais jamais compte comme reference de prix pour l'idee.
                claim = claim.model_copy(
                    update={"flags": [*claim.flags, "prestation non comparable"]}
                )
            priced.append(claim)
        else:
            removed.append(
                f"Prix : « {claim.text[:60]} » retiré : aucun tarif chiffré dans les sources citées"
            )
    sections["prices"] = priced
    # Contradictions de prix entre sources differentes : signalees, confiance abaissee.
    if sections["prices"]:
        probe = [
            validate_finding(
                FindingCandidate(category=ResearchCategory.PRICES, statement=c.text,
                                 nature=Nature.ESTIMATE if c.kind == "estimation" else Nature.FACT,
                                 source_ids=c.source_ids, quotes=c.quotes),
                sources, finding_id=str(i), project_markets=markets,
            )
            for i, c in enumerate(sections["prices"])
        ]  # fmt: skip
        contradicted = {
            int(f.id) for f in mark_contradictions(probe) if "contradictoire" in f.flags
        }
        contradicted |= {
            i for i, c in enumerate(sections["prices"]) if merged_price_spread(c, sources)
        }
        sections["prices"] = [
            c.model_copy(update={"flags": [*c.flags, "contradictoire"]}) if i in contradicted else c
            for i, c in enumerate(sections["prices"])
        ]
    competitors = []
    for comp in draft.competitors:
        ids = _resolve(comp.sources, aliases)
        cited = [sources[s] for s in ids]
        if not cited or _norm(comp.name) not in _corpus(cited):
            removed.append(f"Concurrent « {comp.name[:40]} » retiré : absent des sources citées")
            continue
        competitors.append(Competitor(name=comp.name, positioning=comp.positioning, source_ids=ids))
    unknowns = list(dict.fromkeys(draft.unknowns))
    mentioned = " ".join(unknowns).lower()
    comparable_prices = [c for c in sections["prices"] if c.comparable]
    if not comparable_prices and not any(u.lower().startswith("prix") for u in unknowns):
        # Toujours dit de la meme facon (recette du 11/11/2026 : une inconnue du modele qui
        # evoquait le « modele de prix » masquait l'absence de tout prix source).
        unknowns.append(
            "Prix observés : insuffisant (aucun tarif chiffré vérifiable dans les sources "
            "retenues)."
        )
    if not competitors and "concurren" not in mentioned:
        unknowns.append("Concurrents : aucun acteur confirmé par les sources.")
    fit = []
    for criterion in ("budget", "temps", "competences", "objectifs"):
        item = next((f for f in draft.fit if f.criterion == criterion), None)
        known = bool(profile.get(criterion))
        if not known:
            # Jamais de suppose sur la personne : ce qu'elle n'a pas dit reste inconnu.
            fit.append(Fit(criterion=criterion, rating="inconnu",
                           reason="Vous ne l'avez pas encore précisé."))  # fmt: skip
        elif item is None:
            fit.append(Fit(criterion=criterion, rating="inconnu", reason="Non évalué."))
        else:
            fit.append(Fit(criterion=criterion, rating=item.rating, reason=item.reason))
    # R5 : un avis promotionnel ecarte ne peut etayer aucun temoignage.
    excluded = set(voice.promotional) if voice else set()
    vendors = set(voice.vendor_sources) if voice else set()
    pain_points = [
        p
        for d in draft.pain_points
        if (p := _validate_pain_point(d, aliases, sources, excluded, removed, vendors))
    ]

    def clean(text: str, limit: int = 300) -> str:
        return finish(dealias(text, aliases, sources), limit)

    # D-80 : niveau de preuve. Celui du modele, plafonne par ce que le code a valide : aucun
    # fait source pertinent -> insuffisant ; sans prix chiffre ou sans concurrent -> partiel.
    facts = sum(1 for claims in sections.values() for c in claims if c.kind == "fait")
    ceiling = "suffisant"
    if facts == 0:
        ceiling = "insuffisant"
    elif not any(c.comparable for c in sections["prices"]) or not competitors or facts < 3:
        ceiling = "partiel"
    evidence = min(draft.evidence, ceiling, key=EVIDENCE_ORDER.__getitem__)

    sections = {
        key: [c.model_copy(update={"text": clean(c.text)}) for c in claims]
        for key, claims in sections.items()
    }
    return IdeaAnalysis(
        idea=idea,
        voice=voice,
        pain_points=[p.model_copy(update={"statement": clean(p.statement)}) for p in pain_points],
        summary=clean(CERTAINTY.sub("probablement", draft.summary), 400),
        sections=sections,
        competitors=[
            c.model_copy(
                update={
                    "positioning": ""
                    if _norm(c.name) in _norm(c.positioning)
                    else clean(c.positioning, 200)
                }
            )
            for c in competitors
        ],
        unknowns=[clean(u) for u in unknowns[:8]],
        fit=[f.model_copy(update={"reason": clean(f.reason, 250)}) for f in fit],
        removed=removed,
        source_count=len(sources),
        evidence=evidence,
        off_topic_count=len(off_topic),
    )


def confidence_cap(
    ideas: list[IdeaAnalysis], profile: dict[str, list[str]], *, simulated: bool = False
) -> Confidence:
    """Plafond de confiance : pas de certitude artificielle quand les preuves manquent.
    Des resultats simules (fictifs) ne justifient jamais plus qu'une confiance faible."""
    available = [i for i in ideas if i.available]
    if not available or simulated:
        return "faible"
    facts = [i.sourced_facts for i in available]
    unknown_profile = sum(1 for values in profile.values() if not values)
    if min(facts) == 0 or sum(facts) < 3:
        return "faible"
    if sum(facts) < 4 * len(available) or unknown_profile >= 2:
        return "moyenne"
    return "elevee"


def validate_comparison(
    draft: ComparisonDraft,
    ideas: list[IdeaAnalysis],
    profile: dict[str, list[str]],
    *,
    simulated: bool = False,
) -> Comparison:
    order = ["faible", "moyenne", "elevee"]
    labels = {n: idea.idea for n, idea in enumerate(ideas, 1)}
    flags: list[str] = []
    ranking = []
    seen: set[int] = set()
    for item in sorted(draft.ranking, key=lambda r: r.rank):
        if item.idea in labels and item.idea not in seen:
            seen.add(item.idea)
            rationale = finish(CERTAINTY.sub("probablement", item.rationale), 300)
            ranking.append(
                Ranking(idea=labels[item.idea], rank=len(ranking) + 1, rationale=rationale)
            )
    recommended = labels.get(draft.recommended_idea) if draft.recommended_idea else None
    if recommended and not next(i for i in ideas if i.idea == recommended).available:
        recommended = None
        flags.append("idée recommandée sans analyse disponible : recommandation retirée")
    reasoning = draft.reasoning
    if CERTAINTY.search(reasoning):
        flags.append("formule de certitude retirée")
        reasoning = CERTAINTY.sub("probablement", reasoning)
    if GENERIC.search(reasoning):
        flags.append("conclusion générique")
    cap = confidence_cap(ideas, profile, simulated=simulated)
    confidence: Confidence = min(draft.confidence, cap, key=order.index)  # type: ignore[assignment]
    if confidence != draft.confidence:
        flags.append(f"confiance ramenée à « {CONFIDENCE_LABELS[confidence]} » (preuves limitées)")
    return Comparison(
        ranking=ranking,
        trade_offs=[finish(t, 300) for t in draft.trade_offs],
        recommended=recommended,
        reasoning=finish(reasoning, 700),
        confidence=confidence,
        proposed_confidence=draft.confidence,
        conditions=[finish(c, 300) for c in draft.conditions],
        next_checks=[finish(c, 300) for c in draft.next_checks],
        flags=flags,
    )


def sources_fingerprint(sources: Iterable[SourceRecord]) -> str:
    import hashlib

    joined = "\n".join(sorted(s.content_hash for s in sources))
    return hashlib.sha256(joined.encode()).hexdigest()
