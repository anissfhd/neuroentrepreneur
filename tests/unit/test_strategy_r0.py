"""R0 : la notation deterministe du conseil strategique detecte chaque defaut attendu.

Outil d'evaluation (scripts/evaluate_strategy_r0.py) ; aucune fonctionnalite de l'application.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def r0():
    spec = importlib.util.spec_from_file_location(
        "evaluate_strategy_r0", ROOT / "scripts" / "evaluate_strategy_r0.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["evaluate_strategy_r0"] = module
    spec.loader.exec_module(module)
    return module


def _scenario(r0, name):
    return next(s for s in r0.SCENARIOS if s["name"].startswith(name))


def test_hand_written_reference_answers_pass(r0):
    for scenario in r0.SCENARIOS:
        checks = r0.grade(scenario, r0.fake_advice(scenario))
        assert all(checks.values()), (scenario["name"], checks)


def _failed(r0, scenario, advice):
    return {name for name, ok in r0.grade(scenario, advice).items() if not ok}


def test_each_defect_is_detected(r0):
    candles = _scenario(r0, "Bougies")
    good = r0.fake_advice(candles)
    invented = good.model_copy(
        update={"competitors": [r0.CompetitorAdvice(name="Bougies Royales", source_ids=["S2"])]}
    )
    assert "aucun concurrent inventé" in _failed(r0, candles, invented)
    unsourced = good.model_copy(
        update={"findings": [r0.FindingAdvice(statement="Le marché croît.", nature="fait")]}
    )
    assert "faits sourcés" in _failed(r0, candles, unsourced)
    number = good.model_copy(
        update={
            "findings": [
                r0.FindingAdvice(
                    statement="75 % achètent en ligne.", nature="fait", source_ids=["S1"]
                )
            ]
        }
    )
    assert "chiffres des faits présents dans leurs sources" in _failed(r0, candles, number)
    two_questions = good.model_copy(update={"question": "Ce segment ? Ou un autre ?"})
    assert "une seule question" in _failed(r0, candles, two_questions)
    ask_target = good.model_copy(update={"question": "Quels sont vos clients cibles ?"})
    assert "pas de « quels sont vos clients »" in _failed(r0, candles, ask_target)
    tutoie = good.model_copy(update={"recommendation_rationale": "Tu devrais viser ce segment."})
    assert "vouvoiement" in _failed(r0, candles, tutoie)
    promise = good.model_copy(update={"market_summary": "Succès garanti sur ce marché."})
    assert "aucune promesse de réussite" in _failed(r0, candles, promise)
    alone = good.model_copy(update={"segments": good.segments[:1]})
    assert "2 à 4 segments" in _failed(r0, candles, alone)


def test_copied_complaints_must_stay_a_weak_signal(r0):
    tea = _scenario(r0, "Box de thé")
    good = r0.fake_advice(tea)
    inflated = good.model_copy(
        update={
            "complaints": [
                r0.ComplaintAdvice(
                    theme="Retards", level="tendance_a_confirmer", source_ids=["S1", "S2", "S3"]
                )
            ]
        }
    )
    assert "plainte copiée = signal faible" in _failed(r0, tea, inflated)


def test_insufficient_data_and_contradictions(r0):
    soap = _scenario(r0, "Savon")
    with_fact = r0.fake_advice(soap).model_copy(
        update={
            "findings": [
                r0.FindingAdvice(
                    statement="Le savon est à la mode.", nature="fait", source_ids=["S1"]
                )
            ]
        }
    )
    # Corrige apres R0 : un fait tire d'une source faible est admis si les limites sont dites.
    assert "données insuffisantes signalées" not in _failed(r0, soap, with_fact)
    silent = with_fact.model_copy(update={"uncertainties": []})
    assert "données insuffisantes signalées" in _failed(r0, soap, silent)
    cooking = _scenario(r0, "Cours de cuisine")
    one_price = r0.fake_advice(cooking).model_copy(
        update={
            "findings": [
                r0.FindingAdvice(
                    statement="Cuisine Académie coûte 12 € par mois.",
                    nature="fait",
                    source_ids=["S1"],
                )
            ]
        }
    )
    assert "contradiction de prix traitée" in _failed(r0, cooking, one_price)


def test_sources_are_fictitious_and_delimited(r0):
    for scenario in r0.SCENARIOS:
        assert all(s["domain"].endswith(".example") for s in scenario["sources"])
        user = r0.messages_for(scenario)[1]["content"]
        assert user.count("<source id=") == len(scenario["sources"])


def test_grading_false_failures_seen_in_r0_are_fixed(r0):
    """Faux echecs constates a la relecture des reponses reelles de la campagne R0."""
    candles = _scenario(r0, "Bougies")
    good = r0.fake_advice(candles)
    curly = good.model_copy(
        update={"competitors": [r0.CompetitorAdvice(name="Lueur d\u2019Atlas", source_ids=["S2"])]}
    )
    assert not {"aucun concurrent inventé", "concurrent attendu repéré"} & _failed(
        r0, candles, curly
    )
    disclaimer = good.model_copy(
        update={"uncertainties": ["La recommandation ne garantit pas la réussite."]}
    )
    assert "aucune promesse de réussite" not in _failed(r0, candles, disclaimer)
    promise = good.model_copy(update={"market_summary": "Succès garanti, réussite assurée."})
    assert "aucune promesse de réussite" in _failed(r0, candles, promise)
    refs = good.model_copy(
        update={
            "findings": [
                r0.FindingAdvice(
                    statement="S2 et S4 citent la même marque.", nature="fait", source_ids=["S2"]
                )
            ]
        }
    )
    assert "chiffres des faits présents dans leurs sources" not in _failed(r0, candles, refs)
    truncated = good.model_copy(update={"recommended_segment": "Segment A (version longue)"})
    named = truncated.model_copy(
        update={
            "segments": [
                s.model_copy(update={"name": "Segment A (version longue) à Casablanca"})
                if s.name == "Segment A"
                else s
                for s in good.segments
            ]
        }
    )
    assert "un segment recommandé parmi les segments" not in _failed(r0, candles, named)
    cooking = _scenario(r0, "Cours de cuisine")
    both = r0.fake_advice(cooking).model_copy(
        update={
            "findings": [
                r0.FindingAdvice(
                    statement="Abonnement à 12 € par mois.", nature="fait", source_ids=["S1"]
                ),
                r0.FindingAdvice(
                    statement="Comparatif : 29 € par mois.", nature="fait", source_ids=["S2"]
                ),
            ],
            "uncertainties": ["Les prix de S1 et S2 sont contradictoires."],
        }
    )
    assert "contradiction de prix traitée" not in _failed(r0, cooking, both)
