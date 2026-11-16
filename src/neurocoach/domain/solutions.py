"""Solutions aux problemes reperes (R6, D-73) : priorites, schemas et regles de preuve.

1. Les problemes viennent de l'analyse R4/R5 validee : tendances corroborees d'abord, puis
   frustrations, inconvenients et risques sources, puis signaux plus faibles.
2. Le modele de strategie propose, pour chaque probleme, des solutions (outil SaaS, API,
   logiciel libre, service, methode), les compare au developpement sur mesure et a une
   approche hybride, recommande et propose des actions.
3. Le code valide : une solution NOMMEE (produit, service, depot) doit figurer dans les
   sources citees ; un cout « fait » exige une citation contenant le chiffre ; les avantages
   et limites ne contiennent ni chiffre ni nom non sources ; la confiance est plafonnee.
Domaine pur : aucune entree-sortie.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from neurocoach.domain.analysis import CERTAINTY, ResearchAnalysis, dealias, finish
from neurocoach.domain.models import DomainModel, UtcDatetime
from neurocoach.domain.research import (
    ProblemTarget,
    SourceRecord,
    _names,
    _norm,
    minimize,
    offer_keywords,
)

OptionKind = Literal["saas", "api", "open_source", "service", "methode", "sur_mesure", "hybride"]
NAMED_KINDS = frozenset({"saas", "api", "open_source", "service"})  # produits nommes
KIND_LABELS = {
    "saas": "Outil en ligne (SaaS)",
    "api": "API",
    "open_source": "Logiciel libre",
    "service": "Service",
    "methode": "Méthode éprouvée",
    "sur_mesure": "Développement sur mesure",
    "hybride": "Approche hybride",
}
CostKind = Literal["fait", "estimation", "inconnu"]
Confidence = Literal["faible", "moyenne", "elevee"]
Text250 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=250)]
ShortId = Annotated[str, StringConstraints(strip_whitespace=True, max_length=12)]
MAX_PROBLEMS = 3
# Recherches par probleme : outils, logiciels libres, methodes (cf. R6, point 2).
SOLUTION_ANGLES = (
    ("outils", "logiciel outil SaaS application"),
    ("libre", "open source GitHub API"),
    ("methodes", "méthode bonnes pratiques entreprises"),
)
_NUMBER = re.compile(r"(?<![\w])\d+(?:[.,]\d+)?")
ENTREPRENEUR_TASK = re.compile(
    r"^\W*(r[ée]aliser |faire |mener )?(une |l')?([ée]tude de march[ée]|analyse (de la |des )?"
    r"concurren|veille|benchmark|d[ée]finir |identifier |choisir |tester )",
    re.I,
)


# --- problemes prioritaires ------------------------------------------------------------------


def select_problems(analysis: ResearchAnalysis, limit: int = MAX_PROBLEMS) -> list[ProblemTarget]:
    """Problemes a traiter, les mieux etayes d'abord ; un theme n'apparait qu'une fois."""
    candidates: list[ProblemTarget] = []
    for idea in analysis.ideas:
        if not idea.available:
            continue
        status_priority = {"corrobore": 0, "a_confirmer": 2, "meme_site": 3, "isole": 4,
                           "vendeur": 6}  # fmt: skip
        for theme in idea.customer_problems():
            quote = theme.mentions[0].sentence if theme.mentions else theme.label
            candidates.append(
                ProblemTarget(
                    idea=idea.idea,
                    label=theme.label,
                    evidence=quote[:300],
                    origin=f"avis clients : {theme.status}",
                    priority=status_priority[theme.status],
                    source_ids=[m.source_id for m in theme.mentions],
                )
            )
        for point in idea.pain_points:
            candidates.append(
                ProblemTarget(
                    idea=idea.idea,
                    label=short_label(point.theme or point.statement),
                    evidence=point.statement[:300],
                    origin=f"frustration ({point.scope})",
                    priority=1 if point.scope == "tendance" else 4,
                    source_ids=point.source_ids,
                )
            )
        for section, origin in (("weaknesses", "inconvénient"), ("risks", "risque"),
                                ("needs", "besoin client")):  # fmt: skip
            for claim in idea.sections.get(section, []):
                if ENTREPRENEUR_TASK.match(claim.text):
                    # Recette du 11/11/2026 : « Étude de marché et analyse de la concurrence »
                    # devenait un probleme a resoudre ; c'est une tache, pas une frustration.
                    continue
                priority = {"fait": 1, "estimation": 3, "hypothese": 5, "avis": 3}[claim.kind]
                if section == "needs":
                    priority += 1  # besoin decrit par le modele : apres les risques sources
                candidates.append(
                    ProblemTarget(
                        idea=idea.idea,
                        label=short_label(claim.text),
                        evidence=claim.text,
                        origin=f"{origin} ({claim.kind})",
                        priority=priority,
                        source_ids=claim.source_ids,
                    )
                )
    chosen: list[ProblemTarget] = []
    seen: set[str] = set()
    for problem in sorted(candidates, key=lambda p: p.priority):
        key = _norm(problem.label)[:40]
        if key in seen:
            continue
        seen.add(key)
        chosen.append(problem)
        if len(chosen) >= limit:
            break
    return chosen


def solution_queries(problem: ProblemTarget, forbidden: list[str] = ()) -> list[tuple[str, str]]:
    """(angle, requete minimisee) : le probleme et l'offre, jamais la conversation."""
    # Recette du 11/11/2026 : « obligations reglementaires assurance… logiciel SaaS », sans
    # le produit, ramenait des outils sans rapport. Le probleme (5 mots) puis l'offre (3).
    topic = f"{offer_keywords(problem.label, limit=5)} {offer_keywords(problem.idea, limit=3)}"
    return [(angle, minimize(f"{topic} {words}", forbidden)) for angle, words in SOLUTION_ANGLES]


# --- sorties du modele -----------------------------------------------------------------------


class _LLM(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CostDraft(_LLM):
    text: str = Field(default="", max_length=200)
    kind: CostKind = "inconnu"
    sources: list[ShortId] = Field(default_factory=list, max_length=3)
    quote: str | None = Field(default=None, max_length=300)


class OptionDraft(_LLM):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]
    kind: OptionKind
    how: Text250
    pros: list[Text250] = Field(default_factory=list, max_length=4)
    cons: list[Text250] = Field(default_factory=list, max_length=4)
    cost: CostDraft = Field(default_factory=CostDraft)
    fit: str = Field(default="", max_length=250)
    sources: list[ShortId] = Field(default_factory=list, max_length=4)


class ActionDraft(_LLM):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=120)]
    done_when: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)
    ]
    estimate_minutes: int = Field(ge=5, le=120)


class SolutionsDraft(_LLM):
    options: list[OptionDraft] = Field(default_factory=list, max_length=6)
    ready_vs_custom: str = Field(default="", max_length=500)
    recommended: str | None = Field(default=None, max_length=80)
    reasoning: str = Field(default="", max_length=600)
    confidence: Confidence = "faible"
    actions: list[ActionDraft] = Field(default_factory=list, max_length=5)
    unknowns: list[Text250] = Field(default_factory=list, max_length=5)


# --- version validee -------------------------------------------------------------------------


class Cost(DomainModel):
    text: str
    kind: CostKind
    source_ids: list[str] = Field(default_factory=list)


class SolutionOption(DomainModel):
    name: str
    kind: OptionKind
    how: str
    pros: list[str]
    cons: list[str]
    cost: Cost
    fit: str
    source_ids: list[str]


class SolutionAction(DomainModel):
    title: str
    done_when: str
    estimate_minutes: int


class ProblemSolutions(DomainModel):
    problem: ProblemTarget
    available: bool = True
    options: list[SolutionOption] = Field(default_factory=list)
    ready_vs_custom: str = ""
    recommended: str | None = None
    reasoning: str = ""
    confidence: Confidence = "faible"
    proposed_confidence: Confidence = "faible"
    actions: list[SolutionAction] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    source_count: int = 0


class SolutionPlan(DomainModel):
    id: str
    mission_id: str
    user_id: str
    created_at: UtcDatetime
    problems: list[ProblemSolutions]
    sources_hash: str
    simulated: bool = False

    @property
    def removed_count(self) -> int:
        return sum(len(p.removed) for p in self.problems)

    def all_actions(self) -> list[tuple[str, SolutionAction]]:
        return [(p.problem.label, a) for p in self.problems for a in p.actions]


def _corpus(sources: list[SourceRecord]) -> str:
    return _norm(" ".join(f"{s.title} {s.excerpt}" for s in sources))


def _resolve(ids: list[str], aliases: dict[str, str]) -> list[str]:
    out: list[str] = []
    for raw in ids:
        sid = aliases.get(raw.strip().upper())
        if sid and sid not in out:
            out.append(sid)
    return out


_DECORATION = re.compile(r"\s*\([^)]*\)?|\s+[\u2014\u2013-]\s+.*$|\s*:\s+.*$")


def core_name(name: str) -> str:
    """Recette du 11/11/2026 : gpt-5-mini nomme une option « Semrush (saas) » ou « Outil — "
    description » ; compare tel quel aux sources, ce nom etait rejete a tort."""
    core = _DECORATION.sub("", name).strip(" .,;:'\"«»")
    return core if len(core) >= 2 else name.strip()


def short_label(text: str, limit: int = 120) -> str:
    """Libelle borne, coupe a un mot entier (jamais en plein mot)."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rfind(" ")
    return text[: cut if cut > 40 else limit].rstrip(" ,;:(") + "…"


def _unsourced_names(text: str, corpus: str, known: set[str], markets: list[str]) -> set[str]:
    """Noms propres absents des sources et des options validees. En tete de phrase, le verbe
    a la majuscule (« Tester Planifix ») : le nom est alors lu sans ce premier mot."""
    found = set()
    for name in _names(text, markets):
        candidates = [name]
        if text.startswith(name) and " " in name:
            candidates.append(name.split(" ", 1)[1])
        if all(_norm(c) not in corpus and _norm(c) not in known for c in candidates):
            found.add(name)
    return found


def _clean_opinions(items: list[str], corpus: str, known_names: set[str], markets: list[str],
                    removed: list[str], where: str) -> list[str]:  # fmt: skip
    kept = []
    known_numbers = {n.replace(",", ".") for n in _NUMBER.findall(corpus)}
    for item in items:
        numbers = {n.replace(",", ".") for n in _NUMBER.findall(item)}
        names = _unsourced_names(item, corpus, known_names, markets)
        if numbers - known_numbers or names:
            removed.append(f"{where} : « {item[:50]} » retiré (chiffre ou nom non sourcé)")
            continue
        kept.append(CERTAINTY.sub("probablement", item))
    return kept


def _naming_sources(name: str, sources: dict[str, SourceRecord], limit: int = 3) -> list[str]:
    """Sources du lot qui nomment l'outil (mot entier, au moins 4 caracteres)."""
    wanted = _norm(name)
    if len(wanted) < 4:
        return []
    pattern = re.compile(rf"(?<!\w){re.escape(wanted)}(?!\w)")
    return [sid for sid, s in sources.items() if pattern.search(_corpus([s]))][:limit]


def validate_solutions(
    draft: SolutionsDraft,
    *,
    problem: ProblemTarget,
    aliases: dict[str, str],
    sources: dict[str, SourceRecord],
    markets: list[str],
    simulated: bool,
) -> ProblemSolutions:
    removed: list[str] = []
    flags: list[str] = []
    options: list[SolutionOption] = []
    corpus_all = _corpus(list(sources.values()))

    def clean(text: str, limit: int = 250) -> str:
        # Identifiants internes des sources remplaces par le site ; phrase coupee retiree.
        return finish(dealias(CERTAINTY.sub("probablement", text), aliases, sources), limit)

    for option in draft.options:
        ids = _resolve(option.sources, aliases)
        cited = [sources[s] for s in ids]
        corpus = _corpus(cited)
        named = option.kind in NAMED_KINDS
        name = core_name(option.name) if named else clean(option.name, 80)
        if named and (not cited or _norm(name) not in corpus):
            # Recette du 11/11/2026 : un outil bien present dans les sources trouvees, mais cite
            # avec une mauvaise source, disparaissait des options tout en restant dans les
            # actions. Il est rattache aux sources qui le nomment reellement, et c'est signale.
            ids = _naming_sources(name, sources)
            if not ids:
                removed.append(
                    f"Solution « {option.name[:40]} » retirée : absente des sources citées"
                )
                continue
            cited = [sources[s] for s in ids]
            corpus = _corpus(cited)
            flags.append(
                f"sources de « {name[:40]} » corrigées : celles citées ne le nommaient pas"
            )
        cost_ids = _resolve(option.cost.sources, aliases)
        cost_corpus = _corpus([sources[s] for s in cost_ids])
        cost_numbers = {n.replace(",", ".") for n in _NUMBER.findall(option.cost.text)}
        known = {n.replace(",", ".") for n in _NUMBER.findall(cost_corpus)}
        cost_kind: CostKind = option.cost.kind
        cost_text = option.cost.text
        quote_ok = bool(option.cost.quote) and _norm(option.cost.quote or "") in cost_corpus
        if cost_kind == "fait" and not (cost_ids and quote_ok and cost_numbers <= known):
            cost_kind = "estimation" if cost_ids and cost_numbers <= known else "inconnu"
            removed.append(f"Coût de « {option.name[:40]} » requalifié en {cost_kind}")
        if cost_kind == "estimation" and (not cost_ids or not cost_numbers <= known):
            cost_kind = "inconnu"
            removed.append(f"Coût de « {option.name[:40]} » non vérifiable : retiré")
        if cost_kind == "inconnu":
            cost_text, cost_ids = "coût non vérifié dans les sources", []
        names = {_norm(core_name(o.name)) for o in draft.options}
        pros = [clean(p) for p in option.pros]
        cons = [clean(c) for c in option.cons]
        options.append(
            SolutionOption(
                name=name,
                kind=option.kind,
                how=clean(option.how),
                pros=_clean_opinions(pros, corpus_all, names, markets, removed, "Avantage"),
                cons=_clean_opinions(cons, corpus_all, names, markets, removed, "Limite"),
                cost=Cost(text=cost_text, kind=cost_kind, source_ids=cost_ids),
                fit=clean(option.fit),
                source_ids=ids,
            )
        )
    kept_names = {_norm(o.name): o for o in options}
    recommended = None
    if draft.recommended:
        for candidate in (draft.recommended, core_name(draft.recommended)):
            if _norm(candidate) in kept_names:
                recommended = kept_names[_norm(candidate)].name
                break
    if draft.recommended and recommended is None:
        flags.append("recommandation retirée : solution absente des options validées")
    ready = [o for o in options if o.kind in NAMED_KINDS | {"methode"}]
    if recommended and kept_names[_norm(recommended)].kind == "sur_mesure" and ready:
        flags.append("développement sur mesure recommandé alors qu'une solution existante a été "
                     "trouvée : à justifier")  # fmt: skip
    reasoning = draft.reasoning
    if CERTAINTY.search(reasoning):
        flags.append("formule de certitude retirée")
        reasoning = CERTAINTY.sub("probablement", reasoning)
    order = ["faible", "moyenne", "elevee"]
    sourced = sum(1 for o in options if o.source_ids)
    cap: Confidence = (
        "faible" if simulated or sourced == 0 else ("moyenne" if sourced < 3 else "elevee")
    )
    confidence: Confidence = min(draft.confidence, cap, key=order.index)  # type: ignore[assignment]
    if confidence != draft.confidence:
        flags.append(f"confiance ramenée à « {confidence} »")
    known_names = set(kept_names)
    actions = []
    for action in draft.actions:
        title = clean(action.title, 120)[:120]  # identifiants de sources remplaces d'abord
        invented = _unsourced_names(title, corpus_all, known_names, markets)
        if invented:
            removed.append(f"Action « {action.title[:50]} » retirée : nom non sourcé")
            continue
        actions.append(SolutionAction(title=title,
                                      done_when=clean(action.done_when, 200)[:200],
                                      estimate_minutes=action.estimate_minutes))  # fmt: skip
    unknowns = list(draft.unknowns)
    if not [o for o in options if o.kind in NAMED_KINDS]:
        unknowns.append("Aucun outil existant confirmé par les sources pour ce problème.")
    if not any(o.cost.kind != "inconnu" for o in options):
        unknowns.append("Coûts : aucun tarif vérifié dans les sources.")
    return ProblemSolutions(
        problem=problem, options=options, ready_vs_custom=clean(draft.ready_vs_custom, 500),
        recommended=recommended, reasoning=clean(reasoning, 600),
        confidence=confidence, proposed_confidence=draft.confidence, actions=actions,
        unknowns=[clean(u) for u in unknowns], removed=removed, flags=flags,
        source_count=len(sources),
    )  # fmt: skip
