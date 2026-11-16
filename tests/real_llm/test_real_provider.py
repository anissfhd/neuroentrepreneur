"""Dialogues avec un vrai fournisseur LLM : ignores sauf demande explicite.

Activation : NEUROCOACH_RUN_REAL_LLM=1, plus NEUROCOACH_LLM_PROVIDER, NEUROCOACH_LLM_MODEL et
la cle dans .env. Ces tests consomment des jetons payants et ne tournent jamais en CI.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

from neurocoach.config import Settings

ROOT = Path(__file__).resolve().parents[2]
ENABLED = os.environ.get("NEUROCOACH_RUN_REAL_LLM") == "1"

pytestmark = [
    pytest.mark.real_llm,
    pytest.mark.skipif(not ENABLED, reason="NEUROCOACH_RUN_REAL_LLM=1 non défini"),
]


def _evaluator():
    spec = importlib.util.spec_from_file_location(
        "evaluate_llm", ROOT / "scripts" / "evaluate_llm.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def runtime(tmp_path_factory):
    from neurocoach.bootstrap import build_coach_runtime

    settings = Settings.from_env()
    if settings.llm_provider == "fake":
        pytest.skip("aucun fournisseur réel configuré")
    configured = settings.model_copy(update={"data_dir": tmp_path_factory.mktemp("real")})
    built = build_coach_runtime(configured)
    built.app.coach.ensure_user(_evaluator().USER, "Évaluation")
    yield built
    built.checkpointer.conn.close()


@pytest.mark.parametrize("index", range(16))
def test_real_dialogue_respects_invariants(runtime, index):
    evaluator = _evaluator()
    name, setup, steps = evaluator.SCENARIOS[index]
    result = evaluator.run_scenario(runtime, name, setup, steps)
    failures = {
        turn.step: [check for check, ok in turn.checks.items() if not ok]
        for turn in result.turns
        if not all(turn.checks.values())
    }
    assert failures == {}, f"{name} : {failures}"
