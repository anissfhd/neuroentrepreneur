"""Estimation hors ligne d'une campagne de comparaison (etape 0) : appels, couts, plafonds.

Usage : python scripts/estimate_campaign.py [--passes 1] [--strategy-reps 1] [--simple-reps 1]

Aucun appel a un fournisseur. Les appels attendus viennent d'un essai a blanc des scenarios
(faux fournisseur) ; la borne haute est certaine (3 appels par message de coaching). Les couts
par appel sont MESURES pour l'effort low (campagnes du 10/11/2026) et des HYPOTHESES pour les
autres efforts. Une completion n'est GARANTIE que si le plafond couvre la borne haute au pire
cas de chaque appel ; sinon elle n'est que probable.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
MAX_OUTPUT_TOKENS = 4000  # comme l'application

# Cout moyen par appel (dollars) : (coaching, strategie, taches simples), et origine.
COSTS = {
    ("gpt-5-mini", "low"): ((0.0010, 0.0033, 0.0010), "mesuré (R0 ; simples : hypothèse)"),
    ("gpt-5-mini", "default"): ((0.0023, 0.0060, 0.0020), "hypothèse (jamais mesuré)"),
    ("gpt-5.6-terra", "low"): ((0.0036, 0.0142, 0.0035), "mesuré (confirmation ; simples : hyp.)"),
    ("gpt-5.6-terra", "medium"): ((0.0093, 0.0260, 0.0080), "hypothèse"),
    ("gpt-5.6-terra", "high"): ((0.0200, 0.0440, 0.0180), "hypothèse"),
    ("gpt-5.6-luna", "low"): ((0.00035, 0.0015, 0.0004), "mesuré (R0 ; simples : hyp.)"),
    ("gpt-5.6-luna", "medium"): ((0.0009, 0.0026, 0.0009), "hypothèse"),
    ("gpt-5.6-luna", "high"): ((0.0020, 0.0045, 0.0020), "hypothèse"),
}
# Plafonds du criblage proposes (docs/COMPARISON_PLAN.md §8).
CAPS = {
    ("gpt-5-mini", "default"): 0.90,
    ("gpt-5-mini", "low"): 0.30,
    ("gpt-5.6-terra", "low"): 1.00,
    ("gpt-5.6-terra", "medium"): 3.00,
    ("gpt-5.6-terra", "high"): 6.00,
    ("gpt-5.6-luna", "low"): 0.15,
    ("gpt-5.6-luna", "medium"): 0.35,
    ("gpt-5.6-luna", "high"): 0.75,
}


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module)
    spec.loader.exec_module(module)
    return module


def dry_counts() -> dict:
    """Appels et taille maximale des entrees, mesures par un essai a blanc."""
    os.environ["NEUROCOACH_FORBID_REAL_LLM"] = "1"
    ev = _load("evaluate_llm")
    from neurocoach.agent.llm import FakeLLM
    from neurocoach.bootstrap import build_coach_runtime
    from neurocoach.config import Settings

    class Counter:
        def __init__(self) -> None:
            self.inner, self.calls = FakeLLM(), []

        def generate_structured(self, task, messages, schema):
            self.calls.append(ev._input_chars(messages, schema))
            return self.inner.generate_structured(task, messages, schema)

        def generate_text(self, task, messages):
            self.calls.append(ev._input_chars(messages))
            return self.inner.generate_text(task, messages)

    counter = Counter()
    with tempfile.TemporaryDirectory() as tmp:
        runtime = build_coach_runtime(Settings(data_dir=Path(tmp)), llm=counter)
        runtime.app.coach.ensure_user(ev.USER, "Estimation")
        for scenario in ev.SCENARIOS:
            ev.run_scenario(runtime, *scenario)
        runtime.checkpointer.conn.close()
    strategy = _load("evaluate_strategy_r0")
    simple = _load("evaluate_simple_tasks")
    bound = sum(
        3 * sum(1 for s in steps if s[0] in ("say", "ensure_pending"))
        for _, _, steps in ev.SCENARIOS
    )
    return {
        "coaching_expected": len(counter.calls),
        "coaching_max": bound,
        "coaching_input": max(counter.calls),
        "strategy_input": max(
            ev._input_chars(strategy.messages_for(s), strategy.StrategicAdvice)
            for s in strategy.SCENARIOS
        ),
        "simple_input": max(ev._input_chars(c["messages"], c["schema"]) for c in simple.cases()),
        "strategy_cases": len(strategy.SCENARIOS),
        "simple_cases": len(simple.cases()),
    }


def worst_call(model: str, input_chars: int) -> float:
    from neurocoach.llm_catalog import default_catalog

    spec = default_catalog().get(model)
    return ((input_chars // 2 + 1) * spec.price_input + MAX_OUTPUT_TOKENS * spec.price_output) / 1e6


def estimate(passes: int, strategy_reps: int, simple_reps: int) -> list[str]:
    c = dry_counts()
    calls = (
        c["coaching_expected"] * passes,
        c["strategy_cases"] * strategy_reps,
        c["simple_cases"] * simple_reps,
    )
    maxima = (c["coaching_max"] * passes, calls[1], calls[2])
    lines = [
        f"Coaching : {c['coaching_expected']} appels attendus par passage (essai à blanc), "
        f"{c['coaching_max']} au maximum (certain) ; stratégie : {c['strategy_cases']} par essai ; "
        f"simples : {c['simple_cases']} par essai.",
        "",
        "| Configuration | Coûts par appel | Appels attendus | Appels max. | Coût attendu | "
        "Plafond proposé | Plafond qui GARANTIT la complétion | Complétion |",
        "|---|---|---|---|---|---|---|---|",
    ]
    total_expected = total_cap = total_guarantee = 0.0
    for (model, effort), ((cc, cs, cx), origin) in COSTS.items():
        expected = calls[0] * cc + calls[1] * cs + calls[2] * cx
        guarantee = (
            maxima[0] * worst_call(model, c["coaching_input"])
            + maxima[1] * worst_call(model, c["strategy_input"])
            + maxima[2] * worst_call(model, c["simple_input"])
        )
        cap = CAPS[(model, effort)] * passes
        # Probable : le plafond couvre la borne haute d'appels au cout moyen suppose.
        probable = cap >= maxima[0] * cc + maxima[1] * cs + maxima[2] * cx
        verdict = (
            "garantie"
            if cap >= guarantee
            else ("probable (hypothèses)" if probable else "à risque")
        )
        total_expected += expected
        total_cap += cap
        total_guarantee += guarantee
        lines.append(
            f"| {model} · {effort} | {origin} | {sum(calls)} | {sum(maxima)} | {expected:.2f} $ | "
            f"{cap:.2f} $ | {guarantee:.2f} $ | {verdict} |"
        )
    lines += [
        f"| **Total** | | | | **{total_expected:.2f} $** | **{total_cap:.2f} $** | "
        f"**{total_guarantee:.2f} $** | |",
    ]
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--passes", type=int, default=1)
    parser.add_argument("--strategy-reps", type=int, default=1)
    parser.add_argument("--simple-reps", type=int, default=1)
    args = parser.parse_args(argv)
    for line in estimate(args.passes, args.strategy_reps, args.simple_reps):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
