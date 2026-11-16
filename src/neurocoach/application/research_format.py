"""Textes de la recherche dans la conversation (R3, D-70) : gabarits deterministes.

Aucun modele ne redige ces textes : la proposition reprend l'apercu approuvable, le resume
ne cite que des constats valides par les regles de preuve, avec leur source. Le texte venu
du Web est echappe (aucun lien, image ni formule interpretes dans le Markdown du fil).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from neurocoach.domain.analysis import (
    CONFIDENCE_LABELS,
    CRITERION_LABELS,
    KIND_LABELS,
    RATING_LABELS,
    SECTION_LABELS,
    SECTIONS,
    IdeaAnalysis,
    ResearchAnalysis,
)
from neurocoach.domain.research import (
    CATEGORY_LABELS,
    NATURE_LABELS,
    VOICE_CATEGORIES,
    Nature,
    SourceRecord,
)
from neurocoach.domain.solutions import (
    KIND_LABELS as OPTION_LABELS,
)
from neurocoach.domain.solutions import (
    NAMED_KINDS,
    ProblemSolutions,
    SolutionPlan,
    select_problems,
)
from neurocoach.domain.voice import (
    ORIGIN_LABELS,
    SENTIMENT_LABELS,
    STATUS_LABELS,
    VoiceReport,
    classify_sources,
    offer_terms_of,
)

MAX_THEMES = 4
SCOPE_LABELS = {"tendance": "tendance corroborée", "temoignage": "témoignage individuel"}

if TYPE_CHECKING:
    from neurocoach.application.research_service import MissionReport
    from neurocoach.domain.research import ResearchMission

# Caracteres actifs en Markdown Streamlit : liens et images ([ ] !), emphase, code, HTML,
# tableaux, titres et formules ($ ... $ est rendu en LaTeX).
_MD_SPECIAL = re.compile(r"([\\`*_\[\]!<>|#~$])")
ITEMS_PER_CATEGORY = 2
NEXT_STEPS = (
    "Ce sont des extraits de pages, pas encore une analyse : leur pertinence n'est pas "
    "vérifiée. Le détail des sources est dans l'onglet Recherche."
)
ANALYSIS_LEGEND = (
    "Légende : « Fait sourcé » = la source l'affirme (ce n'est pas une garantie) ; "
    "« Estimation » = déduction prudente ; « Hypothèse à vérifier » ; « Avis du coach » = mon "
    "jugement."
)
SOLVE_HINT = (
    "Étape suivante possible : chercher des solutions concrètes (outils existants, logiciels "
    "libres, méthodes éprouvées) aux problèmes les mieux étayés : {problems}. Demandez-le "
    "simplement : je vous proposerai une recherche à approuver."
)
NO_PROBLEM_HINT = "Aucun problème assez étayé pour lancer une recherche de solutions."
TASKS_HINT = (
    "Ces actions ne sont pas encore dans votre plan. Dites « transforme ces actions en tâches » "
    "pour obtenir une proposition, que vous pourrez confirmer ou annuler."
)
COST_LABELS = {"fait": "tarif sourcé", "estimation": "estimation", "inconnu": "non vérifié"}
MAX_PER_SECTION = 3


def md_escape(text: str) -> str:
    return _MD_SPECIAL.sub(r"\\\1", " ".join((text or "").split()))


# D-82 : un message de conversation court, puis son detail (affiche replie par l'interface,
# et en clair dans la carte de consentement). Commentaire HTML : invisible en Markdown.
DETAILS_MARKER = "<!-- détails -->"


def split_details(text: str) -> tuple[str, str]:
    head, _, tail = text.partition(DETAILS_MARKER)
    return head.strip(), tail.strip()


def proposal_message(mission: ResearchMission, intro: str) -> str:
    scope = mission.scope
    subject = scope.subject or " ; ".join(scope.subjects) or scope.objective
    specific = [m for m in scope.markets if m != "international"]
    where = f" ({', '.join(specific)})" if specific else ""
    what = ", ".join(CATEGORY_LABELS[c] for c in scope.categories)
    # Recette du 12/11/2026 : « … (marché, prix) : : marché, prix, pour … » (intro deja
    # accompagnee des categories, puis repetee).
    base = intro.rstrip().rstrip(":").rstrip()
    lead = base if "(" in base else f"{base} ({what})"
    # D-84 : la conversation ne montre ni fournisseurs, ni requetes, ni donnees transmises :
    # ils sont dans la fiche d'approbation, sous la conversation (vision V1, point 5).
    return (
        f"{lead}, pour « {md_escape(subject)} »{where}. La fiche ci-dessous détaille ce qui "
        "sera consulté, les données transmises et le coût : rien n'est lancé sans votre clic "
        "sur « Approuver et lancer »."
    )


def mission_head(report: MissionReport) -> str:
    mode = "simulée, résultats fictifs" if report.simulated else "recherche web réelle"
    done = [q for q in report.queries if q.status == "done"]
    return (
        f"Résultats de la recherche ({mode}) : {len(done)} recherche(s) faite(s), "
        f"{len(report.sources)} résultat(s) reçu(s)."
    )


def format_mission_summary(report: MissionReport) -> str:
    """Resume factuel : constats sources par idee et par categorie, manques et incidents."""
    mode = "simulée, résultats fictifs" if report.simulated else "recherche web réelle"
    done = [q for q in report.queries if q.status == "done"]
    head = (
        f"Résultats de la recherche ({mode}) : {len(done)} recherche(s) faite(s), "
        f"{len(report.sources)} résultat(s) reçu(s), pertinence non vérifiée."
    )
    domains = {s.id: s.domain for s in report.sources}
    offer = " ".join(b.offer.value or "" for b in report.mission.briefs.values())
    origins = classify_sources(report.sources, offer_terms_of(offer))
    subjects = report.mission.scope.subjects or [None]
    blocks = []
    for subject in subjects:
        lines = []
        for category in report.categories:
            findings = [
                f
                for f in category.findings
                if subject is None or {report.subject_of.get(s) for s in f.source_ids} == {subject}
            ][:ITEMS_PER_CATEGORY]
            label = category.label.capitalize()
            if not findings:
                ran = any(
                    q.category is category.category and (subject is None or q.subject == subject)
                    for q in done
                )
                if ran:
                    lines.append(f"- {label} : aucune donnée fiable trouvée.")
                continue
            for finding in findings:
                cited = ", ".join(sorted({domains[s] for s in finding.source_ids if s in domains}))
                nature = NATURE_LABELS[finding.nature]
                if "simulé" in finding.flags:
                    nature += ", simulé"
                warn = [f for f in finding.flags if f in ("contradictoire", "autre marché",
                                                           "date inconnue")]  # fmt: skip
                extra = f", {', '.join(warn)}" if warn else ""
                if category.category in VOICE_CATEGORIES:
                    kinds = {origins.get(s) for s in finding.source_ids}
                    if kinds & {"vendeur", "promotionnel"}:
                        extra += ", contenu publié par un vendeur, pas un avis indépendant"
                text = finding.statement
                if finding.nature is Nature.FACT:
                    text = f"« {text} »"
                lines.append(
                    f"- {label} ({nature}{extra}) : {md_escape(text)} "
                    f"(source : {md_escape(cited or 'aucune')})"
                )
        if subject is not None:
            body = "\n".join(lines) or "- Aucune donnée fiable trouvée."
            blocks.append(f"**{md_escape(subject)}**\n\n{body}")
        elif lines:
            blocks.append("\n".join(lines))
        else:
            blocks.append("Aucune donnée fiable trouvée.")
    notes = []
    failed = [q for q in report.queries if q.status == "failed"]
    if failed:
        kinds = sorted({q.error_kind or "error" for q in failed})
        reasons = {
            "quota": "quota gratuit atteint",
            "auth": "clé refusée",
            "rate_limited": "trop de requêtes",
            "error": "service indisponible",
        }
        notes.append(
            f"{len(failed)} recherche(s) n'ont pas abouti ("
            + ", ".join(reasons.get(k, k) for k in kinds)
            + ")."
        )
    blocked = sum(q.blocked_count for q in report.queries)
    if blocked:
        notes.append(
            f"{blocked} résultat(s) écarté(s) : sites non autorisés (Reddit, plateformes d'avis "
            "aux conditions restrictives)."
        )
    if report.not_run:
        notes.append(
            f"{report.not_run} recherche(s) prévue(s) non lancée(s) : quota gratuit du mois ou "
            "budget de la mission atteint. Aucun dépassement payant n'a été tenté."
        )
    if report.hypotheses:
        notes.append("Hypothèses à vérifier : " + md_escape(" ; ".join(report.hypotheses)) + ".")
    parts = [head, *blocks, *notes, NEXT_STEPS]
    return "\n\n".join(parts)


def _claim_line(claim, domains: dict[str, str]) -> str:
    cited = sorted({domains[s] for s in claim.source_ids if s in domains})
    label = KIND_LABELS[claim.kind]
    if cited:
        label += f", source : {', '.join(cited)}"
    shown = ("contradictoire", "autre marché", "date inconnue", "simulé",
             "prestation non comparable")  # fmt: skip
    warn = [f for f in claim.flags if f in shown]
    if warn:
        label += f" ; {', '.join(warn)}"
    return f"{md_escape(claim.text)} ({md_escape(label)})"


def _voice_lines(idea: IdeaAnalysis) -> list[str]:
    """R5 : ce que disent les clients. Le statut (temoignage individuel, signal d'un seul
    site, tendance corroboree) est calcule par le code, jamais par le modele."""
    voice: VoiceReport | None = idea.voice
    if voice is None:
        return []
    lines = []
    themes = voice.themes[:MAX_THEMES]
    if themes:
        items = []
        for theme in themes:
            # Finalisation : sites non commerciaux et vendeurs comptes a part ; l'origine de
            # la citation affichee est toujours dite.
            mention = theme.mentions[0] if theme.mentions else None
            quote = mention.sentence if mention else ""
            where = []
            if theme.domains:
                where.append(f"{len(theme.domains)} site(s) non commercial(aux) : "
                             + ", ".join(theme.domains))  # fmt: skip
            if theme.vendor_domains:
                where.append(f"{len(theme.vendor_domains)} site(s) de vendeur : "
                             + ", ".join(theme.vendor_domains))  # fmt: skip
            origin = f", {ORIGIN_LABELS[mention.origin]}" if mention else ""
            warning = f" ; attention : {theme.contradiction}" if theme.contradiction else ""
            items.append(
                f"{md_escape(theme.label)} ({SENTIMENT_LABELS[theme.sentiment]}) : "
                f"{STATUS_LABELS[theme.status]} ({md_escape(' ; '.join(where))}) ; "
                f"« {md_escape(quote)} »{origin}{md_escape(warning)}"
            )
        lines.append("- Ce que disent les clients : " + " ; ".join(items))
    if idea.pain_points:
        items = [
            f"{md_escape(p.statement)} ({SCOPE_LABELS[p.scope]}"
            f", source : {md_escape(', '.join(p.domains))})"
            for p in idea.pain_points[:3]
        ]
        lines.append("- Frustrations et attentes (lecture du coach) : " + " ; ".join(items))
    if voice.notes:
        lines.append("- Limites des avis : " + md_escape(" ".join(voice.notes)))
    return lines


EVIDENCE_LABELS = {
    "suffisant": "suffisant pour recommander",
    "partiel": "partiel (des éléments manquent : voir les inconnues)",
    "insuffisant": "insuffisant pour recommander un choix précis",
}


def _idea_block(number: int, idea: IdeaAnalysis, domains: dict[str, str]) -> str:
    head = [f"**{number}. {md_escape(idea.idea)}**"]
    if not idea.available:
        head.append(f"- {md_escape(' '.join(idea.unknowns) or 'Analyse indisponible.')}")
        return "\n\n".join(head)
    if idea.summary:
        head.append(md_escape(idea.summary))
    if idea.evidence != "inconnu":
        head.append(f"**Niveau de preuve : {EVIDENCE_LABELS[idea.evidence]}**")
    lines: list[str] = []
    for section in SECTIONS:
        claims = idea.sections.get(section, [])[:MAX_PER_SECTION]
        if claims:
            items = " ; ".join(_claim_line(c, domains) for c in claims)
            lines.append(f"- {SECTION_LABELS[section]} : {items}")
    if idea.competitors:

        def competitor(c) -> str:
            cited = ", ".join(sorted({domains.get(s, "?") for s in c.source_ids}))
            positioning = f" ({md_escape(c.positioning)})" if c.positioning else ""
            return f"{md_escape(c.name)}{positioning} (source : {md_escape(cited)})"

        items = " ; ".join(competitor(c) for c in idea.competitors[:MAX_PER_SECTION])
        lines.append(f"- Concurrents : {items}")
    lines += _voice_lines(idea)
    if idea.unknowns:
        lines.append("- Inconnues : " + md_escape(" ; ".join(idea.unknowns[:4])))
    fit = " ; ".join(
        f"{CRITERION_LABELS[f.criterion]} : {RATING_LABELS[f.rating]}"
        + (f" ({md_escape(f.reason)})" if f.reason and f.rating != "inconnu" else "")
        for f in idea.fit
    )
    if fit:
        lines.append(f"- Adéquation à votre situation : {fit}")
    # Lignes vides : en Markdown, un paragraphe colle a une liste s'y fond.
    return "\n\n".join([*head, "\n".join(lines)] if lines else head)


def format_analysis(
    analysis: ResearchAnalysis, sources: list[SourceRecord], *, log: bool = True
) -> str:
    """Analyse validee, rendue sans modele : natures, sources, inconnues, retraits.

    ``log=False`` (detail affiche dans la conversation, D-84) : sans le journal d'execution
    (nombre de resultats, affirmations retirees, suggestion de recherche) ; une recherche
    simulee reste signalee."""
    domains = {s.id: s.domain for s in sources}
    mode = " ; résultats simulés, fictifs" if analysis.simulated else ""
    # D-80 : le nombre de sources ne dit rien de la qualite : on montre combien sont
    # pertinentes, combien ont ete ecartees, et le niveau de preuve qui en resulte.
    off = sum(i.off_topic_count for i in analysis.ideas)
    head = (
        f"Voici mon analyse critique : {len(sources)} résultat(s) reçu(s)"
        + (f", dont {off} écarté(s) comme hors sujet" if off else "")
        + f"{mode}."
    )
    if log:
        parts = [head, ANALYSIS_LEGEND]
    elif analysis.simulated:
        parts = [
            "Résultats simulés, fictifs : ils ne prouvent rien sur le marché.",
            ANALYSIS_LEGEND,
        ]
    else:
        parts = [ANALYSIS_LEGEND]
    parts += [_idea_block(n, idea, domains) for n, idea in enumerate(analysis.ideas, 1)]
    comparison = analysis.comparison
    if comparison is not None:
        lines = ["**Comparaison**"] if len(analysis.ideas) > 1 else ["**Synthèse**"]
        if comparison.ranking:
            lines.append(
                "\n".join(
                    f"{item.rank}. {md_escape(item.idea)} : {md_escape(item.rationale)}"
                    for item in comparison.ranking
                )
            )
        if comparison.trade_offs:
            lines.append("Arbitrages : " + md_escape(" ; ".join(comparison.trade_offs)))
        confidence = CONFIDENCE_LABELS[comparison.confidence]
        if comparison.recommended:
            lines.append(
                f"**Recommandation** (confiance {confidence}) : {md_escape(comparison.recommended)}"
            )
        else:
            lines.append(
                f"**Recommandation** (confiance {confidence}) : les données ne permettent pas "
                "de trancher."
            )
        if comparison.reasoning:
            lines.append(md_escape(comparison.reasoning))
        checks = []
        if comparison.conditions:
            checks.append(
                "- Ce qui me ferait changer d'avis : "
                + md_escape(" ; ".join(comparison.conditions))
            )
        if comparison.next_checks:
            checks.append(
                "- Vérifications à faire : " + md_escape(" ; ".join(comparison.next_checks))
            )
        if checks:
            lines.append("\n".join(checks))
        parts.append("\n\n".join(lines))
    else:
        parts.append("Comparaison indisponible : pas assez d'éléments analysés.")
    if not log:
        return "\n\n".join(parts)
    if analysis.removed_count:
        parts.append(
            f"{analysis.removed_count} affirmation(s) retirée(s) ou requalifiée(s) faute de "
            "source suffisante (détail dans l'onglet Recherche)."
        )
    problems = select_problems(analysis)
    parts.append(
        SOLVE_HINT.format(problems=" ; ".join(md_escape(p.label) for p in problems))
        if problems
        else NO_PROBLEM_HINT
    )
    return "\n\n".join(parts)


def analysis_facts(analysis: ResearchAnalysis, sources: list[SourceRecord]) -> dict:
    """Version compacte pour la conversation (R4) : elements valides seulement."""
    domains = {s.id: s.domain for s in sources}
    comparison = analysis.comparison
    return {
        "idees": [
            {
                "idee": idea.idea,
                "niveau_de_preuve": idea.evidence,
                "sources_ecartees_hors_sujet": idea.off_topic_count,
                "elements": [
                    {
                        "rubrique": SECTION_LABELS[section],
                        "texte": c.text[:200],
                        "nature": c.kind,
                        "comparable": c.comparable,
                        "signalements": c.flags,
                        "references": c.source_ids,
                        "sources": sorted({domains[s] for s in c.source_ids if s in domains}),
                    }
                    for section in SECTIONS
                    for c in idea.sections.get(section, [])[:2]
                ],
                "concurrents": [c.name for c in idea.competitors],
                "inconnues": idea.unknowns[:4],
                "adequation": {f.criterion: f.rating for f in idea.fit},
                "voix_clients": [
                    {
                        "theme": t.label,
                        "sentiment": t.sentiment,
                        "statut": STATUS_LABELS[t.status],
                        "sites": t.domains,
                        "sites_vendeurs": t.vendor_domains,
                        "exemple": t.mentions[0].sentence[:200] if t.mentions else None,
                        "origine_exemple": t.mentions[0].origin if t.mentions else None,
                    }
                    for t in (idea.voice.themes[:MAX_THEMES] if idea.voice else [])
                ],
                "frustrations": [
                    {"texte": p.statement[:200], "portee": p.scope, "sites": p.domains}
                    for p in idea.pain_points[:3]
                ],
            }
            for idea in analysis.ideas
        ],
        "recommandation": None
        if comparison is None
        else {
            "idee": comparison.recommended,
            "confiance": comparison.confidence,
            "raisonnement": comparison.reasoning[:400],
            "conditions": comparison.conditions,
            "verifications": comparison.next_checks,
        },
        "simule": analysis.simulated,
    }


def _problem_block(number: int, item: ProblemSolutions, domains: dict[str, str]) -> str:
    problem = item.problem
    head = [
        f"**{number}. {md_escape(problem.label)}**",
        f"Pourquoi : {md_escape(problem.evidence)} ({md_escape(problem.origin)})",
    ]
    if not item.available or not item.options:
        head.append("- " + md_escape(" ; ".join(item.unknowns) or "Aucune solution sourcée."))
        return "\n\n".join(head)
    lines = []
    # Solutions existantes d'abord (R6 : privilegier l'existant), puis sur mesure et hybride.
    ordered = sorted(item.options, key=lambda o: o.kind not in NAMED_KINDS | {"methode"})
    for option in ordered:
        cited = ", ".join(sorted({domains[s] for s in option.source_ids if s in domains}))
        cost = COST_LABELS[option.cost.kind]
        if option.cost.kind != "inconnu":
            cost = f"{md_escape(option.cost.text)} ({cost})"
        detail = [
            f"{md_escape(option.name)} ({OPTION_LABELS[option.kind]}"
            + (f", source : {md_escape(cited)}" if cited else ", approche non sourcée")
            + f") : {md_escape(option.how)}",
            "avantages : " + md_escape(" ; ".join(option.pros) or "non précisés"),
            "limites : " + md_escape(" ; ".join(option.cons) or "non précisées"),
            f"coût : {cost}",
        ]
        if option.fit:
            detail.append("pour vous : " + md_escape(option.fit))
        lines.append("- " + " — ".join(detail))
    blocks = [*head, "\n".join(lines)]
    if item.ready_vs_custom:
        blocks.append("Existant, sur mesure ou hybride : " + md_escape(item.ready_vs_custom))
    if item.recommended:
        blocks.append(
            f"**Recommandation** (confiance {item.confidence}) : {md_escape(item.recommended)}. "
            + md_escape(item.reasoning)
        )
    else:
        blocks.append(
            f"**Recommandation** (confiance {item.confidence}) : les sources ne permettent pas "
            "de trancher. " + md_escape(item.reasoning)
        )
    if item.actions:
        blocks.append(
            "Prochaines actions :\n"
            + "\n".join(
                f"- {md_escape(a.title)} ({a.estimate_minutes} min ; fini quand : "
                f"{md_escape(a.done_when)})"
                for a in item.actions
            )
        )
    if item.unknowns:
        blocks.append("À vérifier : " + md_escape(" ; ".join(item.unknowns[:4])))
    return "\n\n".join(blocks)


def format_solutions(plan: SolutionPlan, sources: list[SourceRecord]) -> str:
    """Solutions validees, rendues sans modele : sources, couts verifies, recommandation."""
    domains = {s.id: s.domain for s in sources}
    mode = " ; résultats simulés, fictifs" if plan.simulated else ""
    parts = [
        f"Voici les solutions trouvées, à partir de {len(sources)} source(s){mode}.",
        "Un outil ou un logiciel n'est cité que s'il figure dans les sources ; un coût n'est "
        "donné que s'il y est vérifiable.",
    ]
    parts += [_problem_block(n, item, domains) for n, item in enumerate(plan.problems, 1)]
    if plan.removed_count:
        parts.append(
            f"{plan.removed_count} élément(s) retiré(s) ou requalifié(s) faute de source "
            "(solution, coût, chiffre ou nom non vérifiés)."
        )
    if plan.all_actions():
        parts.append(TASKS_HINT)
    return "\n\n".join(parts)


def solutions_facts(plan: SolutionPlan, sources: list[SourceRecord]) -> dict:
    """Version compacte pour la conversation (R6) : options validees seulement."""
    domains = {s.id: s.domain for s in sources}
    return {
        "problemes": [
            {
                "probleme": item.problem.label,
                "options": [
                    {
                        "nom": o.name,
                        "type": o.kind,
                        "cout": o.cost.text if o.cost.kind != "inconnu" else "non vérifié",
                        "sources": sorted({domains[s] for s in o.source_ids if s in domains}),
                    }
                    for o in item.options
                ],
                "recommandation": item.recommended,
                "confiance": item.confidence,
                "actions": [a.title for a in item.actions],
            }
            for item in plan.problems
        ],
        "simule": plan.simulated,
    }
