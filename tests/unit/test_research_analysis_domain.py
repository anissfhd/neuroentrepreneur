"""R4 (D-71) : regles de preuve appliquees a l'analyse du modele de strategie."""

from __future__ import annotations

from datetime import UTC, date, datetime

from neurocoach.domain.analysis import (
    ComparisonDraft,
    IdeaAnalysis,
    IdeaAnalysisDraft,
    build_profile,
    confidence_cap,
    validate_comparison,
    validate_idea_analysis,
)
from neurocoach.domain.research import ResearchCategory, SourceRecord

NOW = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
PROFILE = {
    "budget": ["Mon budget est de 500 €"],
    "temps": ["J'ai 1 heure le soir"],
    "competences": [],
    "objectifs": ["Je veux un revenu complémentaire"],
}


NO_PRICE = "Prix observés : insuffisant (aucun tarif chiffré vérifiable dans les sources retenues)."


def source(sid, excerpt, title="Titre", category=ResearchCategory.PRICES, **extra):
    values = dict(
        id=sid, query_id="q", category=category, provider="tavily",
        url=f"https://{sid}.example/x", domain=f"{sid}.example", title=title, excerpt=excerpt,
        published_date=date(2025, 1, 1), retrieved_at=NOW, market="France", content_hash=sid,
        simulated=False,
    )  # fmt: skip
    values.update(extra)
    return SourceRecord(**values)


SOURCES = {
    "a": source("a", "Une galette se vend 4 € sur les marchés de Lyon."),
    "b": source("b", "Une galette coûte 9 € dans les crêperies du centre."),
    "c": source("c", "Exemple Crêpes Lyon propose des galettes à emporter.",
                category=ResearchCategory.COMPETITION),
    "d": source("d", "", title="Maison Galette, food truck à Lyon",
                category=ResearchCategory.COMPETITION),  # reference seule (Exa)
}  # fmt: skip
ALIASES = {"S1": "a", "S2": "b", "S3": "c", "S4": "d"}


def analyse(draft: dict, profile=PROFILE) -> IdeaAnalysis:
    return validate_idea_analysis(
        IdeaAnalysisDraft.model_validate({"summary": "Résumé.", **draft}),
        idea="Galettes",
        aliases=ALIASES,
        sources=SOURCES,
        profile=profile,
        markets=["France"],
    )


def test_quoted_fact_stays_fact_and_unquoted_becomes_hypothesis():
    result = analyse({"needs": [
        {"text": "Une galette se vend 4 € sur les marchés de Lyon.", "kind": "fait",
         "sources": ["S1"], "quote": "Une galette se vend 4 € sur les marchés de Lyon."},
        {"text": "Les clients veulent des galettes bio.", "kind": "fait", "sources": ["S1"],
         "quote": "Les clients veulent des galettes bio."},
    ]})  # fmt: skip
    kinds = [c.kind for c in result.sections["needs"]]
    assert kinds == ["fait", "hypothese"]
    assert result.sections["needs"][0].source_ids == ["a"]
    assert any("requalifié en Hypothèse à vérifier" in r for r in result.removed)


def test_unknown_source_alias_is_ignored():
    result = analyse({"needs": [{"text": "Les clients veulent du local.", "kind": "fait",
                                 "sources": ["S9"], "quote": "x"}]})  # fmt: skip
    assert result.sections["needs"][0].kind == "hypothese"
    assert result.sections["needs"][0].source_ids == []


def test_invented_competitor_is_removed_and_reference_title_is_accepted():
    result = analyse({"competitors": [
        {"name": "Exemple Crêpes Lyon", "positioning": "à emporter", "sources": ["S3"]},
        {"name": "Maison Galette", "positioning": "food truck", "sources": ["S4"]},
        {"name": "Crêperie Imaginaire", "positioning": "haut de gamme", "sources": ["S3"]},
    ]})  # fmt: skip
    assert [c.name for c in result.competitors] == ["Exemple Crêpes Lyon", "Maison Galette"]
    assert any("Crêperie Imaginaire" in r for r in result.removed)


def test_prices_only_when_sourced_and_numbers_checked():
    result = analyse({"prices": [
        {"text": "Une galette se vend 4 € sur les marchés de Lyon.", "kind": "fait",
         "sources": ["S1"], "quote": "Une galette se vend 4 € sur les marchés de Lyon."},
        {"text": "Une galette premium se vend 15 €.", "kind": "fait", "sources": ["S1"],
         "quote": "Une galette se vend 4 € sur les marchés de Lyon."},
        {"text": "Les prix vont augmenter.", "kind": "hypothese", "sources": []},
        {"text": "Prix élevé possible.", "kind": "avis"},
    ]})  # fmt: skip
    prices = result.sections["prices"]
    assert [c.kind for c in prices] == ["fait", "estimation"]  # 15 € absent des sources
    assert sum("non étayée" in r or "avis sans source" in r for r in result.removed) == 2


def test_missing_prices_and_competitors_are_reported_not_invented():
    result = analyse({})
    assert NO_PRICE in result.unknowns
    assert "Concurrents : aucun acteur confirmé par les sources." in result.unknowns


def test_contradictory_prices_are_flagged():
    result = analyse({"prices": [
        {"text": "Une galette se vend 4 € sur les marchés de Lyon.", "kind": "fait",
         "sources": ["S1"], "quote": "Une galette se vend 4 € sur les marchés de Lyon."},
        {"text": "Une galette coûte 9 € dans les crêperies du centre.", "kind": "fait",
         "sources": ["S2"], "quote": "Une galette coûte 9 € dans les crêperies du centre."},
    ]})  # fmt: skip
    assert all("contradictoire" in c.flags for c in result.sections["prices"])


def test_prices_from_two_sources_merged_into_one_claim_are_flagged():
    """Recette du 11/11/2026 : « entre 4 et 9 € » citant deux sources echappait au signalement."""
    result = analyse({"prices": [
        {"text": "Une galette se vend entre 4 et 9 € selon le lieu.", "kind": "estimation",
         "sources": ["S1", "S2"]},
    ]})  # fmt: skip
    assert result.sections["prices"]
    assert "contradictoire" in result.sections["prices"][0].flags


def test_one_source_price_range_is_not_a_contradiction():
    result = analyse({"prices": [
        {"text": "Une galette se vend 4 € sur les marchés de Lyon.", "kind": "fait",
         "sources": ["S1"], "quote": "Une galette se vend 4 € sur les marchés de Lyon."},
    ]})  # fmt: skip
    assert "contradictoire" not in result.sections["prices"][0].flags


def test_missing_prices_are_reported_even_when_the_model_mentions_pricing():
    """Recette du 11/11/2026 : une inconnue « modèle de prix » masquait l'absence de prix."""
    result = analyse({"unknowns": ["Modèle de prix accepté par les clients."]})
    assert NO_PRICE in result.unknowns
    explicit = analyse({"unknowns": ["Prix pratiqués : inconnus."]})
    assert explicit.unknowns.count(NO_PRICE) == 0


def test_coach_opinions_are_allowed_but_never_invent():
    result = analyse({
        "strengths": [{"text": "Une offre simple à tester sur un marché.", "kind": "avis"}],
        "weaknesses": [{"text": "Il faudrait 300 clients par mois.", "kind": "avis"}],
        "risks": [{"text": "La concurrence de Maison Lumière est forte.", "kind": "avis"}],
    })  # fmt: skip
    assert [c.kind for c in result.sections["strengths"]] == ["avis"]
    assert result.sections["weaknesses"] == [] and result.sections["risks"] == []
    assert sum("chiffre ou un nom non sourcé" in r for r in result.removed) == 2


def test_fit_uses_only_what_the_user_said():
    result = analyse({"fit": [
        {"criterion": "budget", "rating": "favorable", "reason": "Budget suffisant."},
        {"criterion": "competences", "rating": "favorable", "reason": "Vous savez cuisiner."},
    ]})  # fmt: skip
    fit = {f.criterion: f for f in result.fit}
    assert fit["budget"].rating == "favorable"
    assert fit["competences"].rating == "inconnu"  # jamais dit : jamais suppose
    assert fit["temps"].rating == "inconnu" and fit["temps"].reason == "Non évalué."


def test_confidence_is_capped_by_evidence_and_certainty_is_removed():
    weak = analyse({})
    draft = ComparisonDraft(
        ranking=[{"idea": 1, "rank": 1, "rationale": "Garanti rentable."},
                 {"idea": 1, "rank": 2, "rationale": "doublon"},
                 {"idea": 4, "rank": 3, "rationale": "inexistante"}],
        recommended_idea=1,
        reasoning="C'est sans aucun doute la meilleure. Faites une liste des avantages.",
        confidence="elevee",
    )  # fmt: skip
    comparison = validate_comparison(draft, [weak], PROFILE)
    assert comparison.confidence == "faible" and comparison.proposed_confidence == "elevee"
    assert "sans aucun doute" not in comparison.reasoning
    assert "garanti" not in comparison.ranking[0].rationale.lower()
    assert len(comparison.ranking) == 1
    assert {"formule de certitude retirée", "conclusion générique"} <= set(comparison.flags)


def test_confidence_cap_levels():
    def idea(facts):
        claims = [{"text": "Une galette se vend 4 € sur les marchés de Lyon.",
                   "kind": "fait", "sources": ["S1"],
                   "quote": "Une galette se vend 4 € sur les marchés de Lyon."}
                  for i in range(facts)]  # fmt: skip
        return analyse({"needs": claims[:4], "strengths": claims[4:]})

    assert confidence_cap([idea(0)], PROFILE) == "faible"
    assert confidence_cap([idea(4)], PROFILE) == "elevee"
    unknown = {k: [] for k in PROFILE}
    assert confidence_cap([idea(4)], unknown) == "moyenne"


def test_profile_keeps_the_users_own_sentences():
    profile = build_profile(
        ["J'ai un budget de 300 €. Je travaille à côté le soir. J'ai été cuisinier dix ans.",
         "Je veux vite un revenu complémentaire."],
        minutes_per_day=45,
    )  # fmt: skip
    assert profile["budget"] == ["J'ai un budget de 300 €."]
    assert profile["temps"][0] == "45 minutes par jour (projet)"
    assert profile["competences"] == ["J'ai été cuisinier dix ans."]
    assert profile["objectifs"] == ["Je veux vite un revenu complémentaire."]
    assert build_profile([])["competences"] == []


def test_solution_targets_prepare_r6():
    result = analyse({
        "weaknesses": [{"text": "Une activité très saisonnière.", "kind": "avis"}],
        "risks": [{"text": "Une forte dépendance à la météo.", "kind": "avis"}],
    })  # fmt: skip
    assert [c.text for c in result.solution_targets()] == [
        "Une activité très saisonnière.", "Une forte dépendance à la météo.",
    ]  # fmt: skip


def test_internal_source_ids_and_cut_sentences_are_cleaned():
    """Recette du 10/11/2026 : « (S2, S1) » visible dans le resume, phrases coupees en plein mot."""
    from neurocoach.domain.analysis import finish

    cut = "Deux prix documentés (S1, S2). " + "La maîtrise de la qualité olfactive est " * 10
    result = analyse(
        {
            "summary": cut[:400],
            "fit": [{"criterion": "budget", "rating": "mitige", "reason": "Serré selon S1 et S9."}],
        }
    )
    assert "(a.example, b.example)" in result.summary and "S1" not in result.summary
    assert result.summary.endswith("…")  # coupe a la limite du schema : termine proprement
    assert result.fit[0].reason == "Serré selon a.example et S9."  # identifiant inconnu : laissé
    # Un fragment court sans point final (titre, avantage) est laisse tel quel.
    assert finish("Un arbitrage entre rapidité et compétences cibl", 47) == (
        "Un arbitrage entre rapidité et compétences…"
    )
    assert finish("Tester Planifix une semaine", 120) == "Tester Planifix une semaine"
    assert finish("Phrase complète.", 16) == "Phrase complète."
    reasoning = ("Idée solide et bien documentée par les sources. " * 15)[:691] + " etd essa"
    draft = ComparisonDraft(
        reasoning=reasoning, confidence="faible", trade_offs=["Vitesse contre revenu"]
    )
    comparison = validate_comparison(draft, [result], PROFILE)
    assert comparison.reasoning.endswith("sources.")
    assert comparison.trade_offs == ["Vitesse contre revenu"]


def test_a_price_for_a_different_service_never_counts_as_evidence():
    """D-83 : recette reelle, 60 000 EUR de deploiement presente comme prix d'un audit court
    et analyse jugee « suffisante »."""
    draft = {
        "evidence": "suffisant",
        "prices": [{"text": "Une galette se vend 4 €.", "kind": "fait", "sources": ["S1"],
                    "quote": "Une galette se vend 4 € sur les marchés de Lyon.",
                    "comparable": False}],
        "competitors": [{"name": "Exemple Crêpes Lyon", "sources": ["S3"]}],
        "strengths": [{"text": "Galettes à emporter proposées.", "kind": "fait", "sources": ["S3"],
                       "quote": "Exemple Crêpes Lyon propose des galettes à emporter."}],
    }  # fmt: skip
    idea = analyse(draft)
    assert (
        idea.sections["prices"] and "prestation non comparable" in idea.sections["prices"][0].flags
    )
    assert idea.evidence != "suffisant"
    assert any(u.startswith("Prix observés : insuffisant") for u in idea.unknowns)


def test_a_non_comparable_price_is_labelled_in_the_report():
    from neurocoach.application.research_format import _claim_line

    price = {
        "text": "Une galette se vend 4 €.",
        "kind": "fait",
        "sources": ["S1"],
        "comparable": False,
        "quote": "Une galette se vend 4 € sur les marchés de Lyon.",
    }
    idea = analyse({"prices": [price]})
    line = _claim_line(idea.sections["prices"][0], {"a": "a.example"})
    assert "prestation non comparable" in line
