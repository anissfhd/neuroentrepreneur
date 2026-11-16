"""D-83 : plafond de depense de session (registre partage, refus avant envoi)."""

from __future__ import annotations

import json

import pytest

from neurocoach.agent.llm import FakeLLM
from neurocoach.agent.schemas import IntentResult
from neurocoach.agent.spending import SpendingCap, capped
from neurocoach.domain.errors import DomainError, ErrorCode

MESSAGES = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]


def test_no_cap_unless_asked():
    llm = FakeLLM()
    assert capped(llm, {}) is llm


def test_sol_is_reserved_at_its_own_rate(tmp_path):
    ledger = tmp_path / "depenses.jsonl"
    cap = capped(
        FakeLLM(),
        {"NEUROCOACH_SPENDING_CAP_USD": "0.07", "NEUROCOACH_SPENDING_LEDGER": str(ledger)},
        models=("gpt-6.1-sol",),
    )
    with pytest.raises(DomainError):
        cap.generate_structured("classify_intent", MESSAGES, IntentResult)
    assert not ledger.exists()


def test_calls_are_recorded_and_refused_before_exceeding_the_cap(tmp_path):
    ledger = tmp_path / "depenses.jsonl"
    cap = capped(FakeLLM(), {"NEUROCOACH_SPENDING_CAP_USD": "0.04",
                             "NEUROCOACH_SPENDING_LEDGER": str(ledger)})  # fmt: skip
    assert isinstance(cap, SpendingCap)
    # Le faux modele ne rapporte aucun jeton : le pire cas (environ 0,016 $) est compte.
    cap.generate_structured("classify_intent", MESSAGES, IntentResult)
    cap.generate_structured("classify_intent", MESSAGES, IntentResult)
    with pytest.raises(DomainError) as error:
        cap.generate_structured("classify_intent", MESSAGES, IntentResult)
    assert error.value.code is ErrorCode.LLM_UNAVAILABLE
    entries = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert len(entries) == 2 and all(e["task"] == "classify_intent" for e in entries)
    # Le registre est partage : un autre processus repart du meme total.
    again = SpendingCap(FakeLLM(), 0.04, ledger)
    assert again.spent() == pytest.approx(sum(e["cost_usd"] for e in entries))
