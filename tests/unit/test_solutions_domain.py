"""R6 (D-73) : priorite des problemes et regles de preuve des solutions."""

from __future__ import annotations

from datetime import UTC, date, datetime

from neurocoach.domain.analysis import Claim, IdeaAnalysis, ResearchAnalysis
from neurocoach.domain.research import ProblemTarget, ResearchCategory, SourceRecord
from neurocoach.domain.solutions import (
    SolutionsDraft,
    select_problems,
    solution_queries,
    validate_solutions,
)
from neurocoach.domain.voice import VoiceMention, VoiceReport, VoiceTheme

NOW = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
PROBLEM = ProblemTarget(idea="Galettes à Lyon", label="Délais de livraison",
                        evidence="Les clients regrettent des délais trop longs.",
                        origin="avis clients : corrobore")  # fmt: skip


def source(sid, title, excerpt=""):
    return SourceRecord(
        id=sid, query_id="q", category=ResearchCategory.SOLUTIONS, provider="tavily",
        url=f"https://{sid}.example/x", domain=f"{sid}.example", title=title, excerpt=excerpt,
        published_date=date(2025, 1, 1), retrieved_at=NOW, content_hash=sid, simulated=False,
    )  # fmt: skip


SOURCES = {
    "a": source("a", "Planifix : suivi des livraisons",
                "Planifix prévient les clients ; abonnement à 12 € par mois."),
    "b": source("b", "TourneeLibre, logiciel libre de tournées", ""),
    "c": source("c", "Guide des livraisons", "Regrouper les commandes réduit les délais."),
}  # fmt: skip
ALIASES = {"S1": "a", "S2": "b", "S3": "c"}


def validate(draft: dict, simulated=False):
    return validate_solutions(
        SolutionsDraft.model_validate(draft), problem=PROBLEM, aliases=ALIASES, sources=SOURCES,
        markets=["France"], simulated=simulated,
    )  # fmt: skip


def option(name, kind="saas", sources=("S1",), **extra):
    values = {"name": name, "kind": kind, "how": "Fonctionnement décrit.", "sources": list(sources)}
    values.update(extra)
    return values


# --- priorite des problemes ------------------------------------------------------------------


def test_corroborated_customer_problems_come_first_and_are_deduplicated():
    voice = VoiceReport(themes=[
        VoiceTheme(theme="prix", label="Prix", sentiment="negatif", status="isole",
                   domains=["a.example"], mentions=[VoiceMention(
                       source_id="s1", domain="a.example", sentence="Trop cher.",
                       sentiment="negatif")]),
        VoiceTheme(theme="delais", label="Délais et livraison", sentiment="negatif",
                   status="corrobore", domains=["a.example", "b.example"], mentions=[
                       VoiceMention(source_id="s2", domain="a.example",
                                    sentence="Livraison trop longue.", sentiment="negatif")]),
    ])  # fmt: skip
    idea = IdeaAnalysis(idea="Galettes", voice=voice, sections={
        "weaknesses": [Claim(text="Une activité saisonnière.", kind="fait", proposed_kind="fait",
                             source_ids=["s3"])],
        "risks": [Claim(text="Délais et livraison", kind="avis", proposed_kind="avis")],
    })  # fmt: skip
    analysis = ResearchAnalysis(id="x", mission_id="m", user_id="u", created_at=NOW,
                                ideas=[idea], sources_hash="h")  # fmt: skip
    problems = select_problems(analysis)
    assert [p.label for p in problems] == [
        "Délais et livraison", "Une activité saisonnière.", "Prix",
    ]  # fmt: skip
    assert problems[0].origin == "avis clients : corrobore"


def test_unavailable_analysis_yields_no_problem():
    analysis = ResearchAnalysis(id="x", mission_id="m", user_id="u", created_at=NOW,
                                ideas=[IdeaAnalysis(idea="x", available=False)],
                                sources_hash="h")  # fmt: skip
    assert select_problems(analysis) == []


def test_solution_queries_cover_tools_open_source_and_methods_without_personal_data():
    problem = PROBLEM.model_copy(update={"evidence": "alice@exemple.fr se plaint"})
    queries = solution_queries(problem, forbidden=["Alice"])
    assert [angle for angle, _ in queries] == ["outils", "libre", "methodes"]
    assert all("@" not in q and len(q.split()) <= 25 for _, q in queries)
    assert "open source GitHub API" in queries[1][1]


# --- regles de preuve ------------------------------------------------------------------------


def test_named_solution_absent_from_sources_is_removed():
    result = validate({"options": [option("Planifix"), option("OutilImaginaire")]})
    assert [o.name for o in result.options] == ["Planifix"]
    assert any("OutilImaginaire" in r for r in result.removed)


def test_existing_tool_cited_with_the_wrong_source_is_reattached_not_dropped():
    """Recette du 11/11/2026 : MyTDB, present dans les sources, citait une source qui ne le
    nommait pas ; il disparaissait des options mais restait dans les actions."""
    result = validate({"options": [option("Planifix", sources=["S3"])],
                       "actions": [{"title": "Essayer Planifix", "done_when": "Compte créé",
                                    "estimate_minutes": 20}]})  # fmt: skip
    assert [o.name for o in result.options] == ["Planifix"]
    assert result.options[0].source_ids == ["a"]
    assert any("corrigées" in f for f in result.flags)
    assert [a.title for a in result.actions] == ["Essayer Planifix"]


def test_reattachment_needs_the_whole_name_in_a_found_source():
    result = validate({"options": [option("Plan", sources=["S3"]),
                                   option("Planifixe", sources=["S3"])]})  # fmt: skip
    assert result.options == []


def test_reference_only_open_source_is_accepted_by_its_title():
    result = validate({"options": [option("TourneeLibre", kind="open_source", sources=["S2"])]})
    assert result.options[0].name == "TourneeLibre"


def test_methods_and_custom_approaches_need_no_product_name():
    result = validate({"options": [
        option("Regrouper les commandes", kind="methode", sources=["S3"]),
        option("Développement sur mesure", kind="sur_mesure", sources=[]),
    ]})  # fmt: skip
    assert [o.kind for o in result.options] == ["methode", "sur_mesure"]


def test_costs_are_verified_or_marked_unknown():
    result = validate({"options": [
        option("Planifix", cost={"text": "12 € par mois", "kind": "fait", "sources": ["S1"],
                                 "quote": "abonnement à 12 € par mois"}),
        option("Planifix", cost={"text": "49 € par mois", "kind": "fait", "sources": ["S1"],
                                 "quote": "abonnement à 49 € par mois"}),
        option("TourneeLibre", kind="open_source", sources=["S2"],
               cost={"text": "gratuit", "kind": "estimation", "sources": []}),
    ]})  # fmt: skip
    costs = [(o.cost.kind, o.cost.text) for o in result.options]
    assert costs[0] == ("fait", "12 € par mois")
    assert costs[1] == ("inconnu", "coût non vérifié dans les sources")
    assert costs[2][0] == "inconnu"


def test_unsourced_numbers_and_names_in_pros_and_actions_are_removed():
    result = validate({
        "options": [option("Planifix", pros=["Réduit les retards de 40 %.", "Simple à prendre"
                                             " en main."], cons=["Concurrent de Zapgo."])],
        "actions": [
            {"title": "Tester Planifix une semaine", "done_when": "Essai noté.",
             "estimate_minutes": 30},
            {"title": "Appeler MegaLogistique", "done_when": "Appel fait.", "estimate_minutes": 15},
        ],
    })  # fmt: skip
    assert result.options[0].pros == ["Simple à prendre en main."]
    assert result.options[0].cons == []
    assert [a.title for a in result.actions] == ["Tester Planifix une semaine"]


def test_recommendation_and_confidence_are_controlled():
    result = validate({
        "options": [option("Planifix"), option("Développement sur mesure", kind="sur_mesure",
                                                sources=[])],
        "recommended": "Développement sur mesure",
        "reasoning": "C'est garanti de fonctionner.",
        "confidence": "elevee",
    })  # fmt: skip
    assert result.recommended == "Développement sur mesure"
    assert any("solution existante a été trouvée" in f for f in result.flags)
    assert "garanti" not in result.reasoning and result.confidence == "moyenne"
    simulated = validate({"options": [option("Planifix")], "recommended": "Inconnu",
                          "confidence": "elevee"}, simulated=True)  # fmt: skip
    assert simulated.recommended is None and simulated.confidence == "faible"
    assert any("recommandation retirée" in f for f in simulated.flags)


def test_missing_tools_and_costs_are_reported():
    result = validate({"options": [option("Regrouper", kind="methode", sources=["S3"])]})
    assert "Aucun outil existant confirmé par les sources pour ce problème." in result.unknowns
    assert "Coûts : aucun tarif vérifié dans les sources." in result.unknowns


# --- corrections issues de la recette reelle du 11/11/2026 ----------------------------------


def test_decorated_tool_names_are_matched_by_their_core_name():
    """gpt-5-mini nommait « Planifix (saas) » : compare tel quel, l'outil etait retire a tort."""
    from neurocoach.domain.solutions import core_name

    names = ["Planifix (saas)", "Planifix — suivi des colis", "Planifix: suivi", "Manus.im (API)"]
    assert [core_name(n) for n in names] == ["Planifix", "Planifix", "Planifix", "Manus.im"]
    result = validate(
        {
            "options": [
                option("Planifix (saas)"),
                option("TourneeLibre — logiciel libre", kind="open_source", sources=["S2"]),
                option("OutilImaginaire (saas)"),
            ],
            "recommended": "Planifix (saas)",
        }
    )
    assert [o.name for o in result.options] == ["Planifix", "TourneeLibre"]
    assert result.recommended == "Planifix"


def test_internal_source_ids_never_reach_the_user_in_solutions():
    result = validate(
        {
            "options": [
                option(
                    "Regrouper les commandes",
                    kind="methode",
                    sources=["S3"],
                    how="Méthode décrite par S3 et S1.",
                    pros=["Confirmé par S3."],
                    fit=("Adapté, voir S1 pour le suivi. " * 9)[:250],
                )
            ],
            "ready_vs_custom": "Les sources S1 et S3 privilégient l'existant.",
            "reasoning": "Commencer par la méthode (S3).",
            "actions": [
                {"title": "Lire le guide S3", "done_when": "Guide S3 lu.", "estimate_minutes": 20}
            ],
        }
    )
    kept = result.options[0]
    action = result.actions[0]
    text = " ".join(
        [kept.how, *kept.pros, kept.fit, result.ready_vs_custom, result.reasoning, action.title]
    )
    assert "S1" not in text and "S3" not in text and "c.example" in text
    assert kept.fit.endswith("suivi.")  # phrase coupee a la limite du schema : retiree
    assert action.title == "Lire le guide c.example"  # titre court : laisse intact


def test_solution_queries_keep_the_product_context():
    problem = ProblemTarget(
        idea="Bougies artisanales parfumées",
        label="Obligations réglementaires et assurance à prévoir (CLP + assurance)",
        evidence="x",
        origin="risque (fait)",
    )
    queries = dict(solution_queries(problem))
    assert all("Bougies" in q for q in queries.values())
    assert queries["methodes"].startswith("Obligations réglementaires")


def test_problem_labels_are_cut_at_a_word_boundary():
    from neurocoach.domain.solutions import short_label

    long = "Étude de marché et analyse de la concurrence : gammes, prix, canaux " * 3
    label = short_label(long)
    assert len(label) <= 121 and label.endswith("…") and not label[:-1].endswith(" ")
    assert short_label("Court.") == "Court."


def test_entrepreneur_tasks_are_not_problems_and_needs_come_after_risks():
    """Recette du 11/11/2026 : « Étude de marché et analyse de la concurrence » etait retenue
    comme probleme a resoudre ; un besoin decrit passait avant un risque source."""
    idea = IdeaAnalysis(
        idea="Bougies",
        sections={
            "needs": [
                Claim(text="Étude de marché et analyse de la concurrence : gammes, prix.",
                      kind="fait", proposed_kind="fait", source_ids=["s1"]),
                Claim(text="Les clients veulent des parfums naturels.", kind="fait",
                      proposed_kind="fait", source_ids=["s2"]),
            ],
            "risks": [Claim(text="Frais d'expédition élevés et casse.", kind="fait",
                            proposed_kind="fait", source_ids=["s3"])],
        },
    )  # fmt: skip
    analysis = ResearchAnalysis(id="x", mission_id="m", user_id="u", created_at=NOW,
                                ideas=[idea], sources_hash="h")  # fmt: skip
    labels = [p.label for p in select_problems(analysis)]
    assert labels == [
        "Frais d'expédition élevés et casse.",
        "Les clients veulent des parfums naturels.",
    ]
