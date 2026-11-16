"""Fournisseur reel : selection par configuration et conversion des erreurs (sans reseau)."""

from __future__ import annotations

import importlib.util
from types import SimpleNamespace

import pytest
from langchain_core.exceptions import OutputParserException

from neurocoach.agent.llm import FakeLLM, LangChainProvider, build_llm_provider
from neurocoach.agent.schemas import IntentResult
from neurocoach.config import ConfigurationError, Settings
from neurocoach.domain.errors import DomainError, ErrorCode

MESSAGES = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]


class StubModel:
    """Double d'un modele de chat LangChain : renvoie ou leve ce qu'on lui donne."""

    def __init__(self, structured=None, text=None) -> None:
        self.structured = structured
        self.text = text
        self.received = None

    def with_structured_output(self, schema, **options):
        self.options = options
        return SimpleNamespace(invoke=self._structured)

    def _structured(self, messages):
        self.received = messages
        if isinstance(self.structured, BaseException):
            raise self.structured
        return self.structured

    def invoke(self, messages):
        if isinstance(self.text, BaseException):
            raise self.text
        return SimpleNamespace(content=self.text)


def test_fake_is_the_default_provider():
    assert isinstance(build_llm_provider(Settings()), FakeLLM)


def test_real_provider_requires_a_model():
    with pytest.raises(ConfigurationError):
        build_llm_provider(Settings(llm_provider="anthropic"))


@pytest.mark.skipif(
    importlib.util.find_spec("langchain_anthropic") is not None,
    reason="l'extra anthropic est installe",
)
def test_missing_extra_is_reported():
    with pytest.raises(ConfigurationError) as error:
        build_llm_provider(Settings(llm_provider="anthropic", llm_model="modele"))
    assert 'pip install -e ".[anthropic]"' in str(error.value)


def test_construction_errors_become_configuration_errors(monkeypatch):
    """Constate en phase 3 : ChatOpenAI leve une erreur brute sans cle des la construction."""
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_LLM")  # construction seule, aucun appel
    import langchain_openai

    def refuse(**kwargs):
        raise RuntimeError("Missing credentials")

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", refuse)
    with pytest.raises(ConfigurationError) as error:
        build_llm_provider(Settings(llm_provider="openai", llm_model="modele"))
    assert "vérifiez la clé API" in str(error.value)


@pytest.mark.skipif(
    importlib.util.find_spec("langchain_anthropic") is None, reason="extra anthropic absent"
)
def test_anthropic_provider_is_built_without_any_network_call(monkeypatch):
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_LLM")  # construction seule, aucun appel
    provider = build_llm_provider(Settings(llm_provider="anthropic", llm_model="claude-sonnet-5-5"))
    assert isinstance(provider, LangChainProvider)
    assert type(provider.model).__name__ == "ChatAnthropic"


def test_structured_output_success_and_conversion():
    model = StubModel(structured=IntentResult(intent="aide"))
    provider = LangChainProvider(model)
    assert provider.generate_structured("t", MESSAGES, IntentResult).intent == "aide"
    assert model.received == [("system", "s"), ("human", "u")]
    assert model.options == {"method": "json_schema"}
    LangChainProvider(model, structured_method=None).generate_structured(
        "t", MESSAGES, IntentResult
    )
    assert model.options == {}
    as_dict = LangChainProvider(StubModel(structured={"intent": "etat_projet"}))
    assert as_dict.generate_structured("t", MESSAGES, IntentResult).intent == "etat_projet"


@pytest.mark.parametrize(
    ("raised", "code"),
    [
        (TimeoutError("délai"), ErrorCode.LLM_UNAVAILABLE),
        (ConnectionError("réseau"), ErrorCode.LLM_UNAVAILABLE),
        (OutputParserException("json"), ErrorCode.LLM_OUTPUT_INVALID),
    ],
)
def test_errors_are_mapped(raised, code):
    with pytest.raises(DomainError) as error:
        LangChainProvider(StubModel(structured=raised)).generate_structured(
            "t", MESSAGES, IntentResult
        )
    assert error.value.code is code


def test_invalid_structured_payload():
    with pytest.raises(DomainError) as error:
        LangChainProvider(StubModel(structured={"intent": "inconnue"})).generate_structured(
            "t", MESSAGES, IntentResult
        )
    assert error.value.code is ErrorCode.LLM_OUTPUT_INVALID


def test_text_generation():
    parts = [{"type": "text", "text": "Bonjour "}, "à vous"]
    assert LangChainProvider(StubModel(text=parts)).generate_text("t", MESSAGES) == "Bonjour à vous"
    with pytest.raises(DomainError) as error:
        LangChainProvider(StubModel(text="  ")).generate_text("t", MESSAGES)
    assert error.value.code is ErrorCode.LLM_OUTPUT_INVALID
    with pytest.raises(DomainError) as error:
        LangChainProvider(StubModel(text=TimeoutError())).generate_text("t", MESSAGES)
    assert error.value.code is ErrorCode.LLM_UNAVAILABLE


@pytest.mark.skipif(importlib.util.find_spec("langchain_openai") is None, reason="extra absent")
def test_analysis_tasks_get_a_longer_timeout_without_changing_the_coach(monkeypatch):
    """Recette du 10/11/2026 : 30 s coupait 3 analyses sur 9 (gpt-5-mini, environ 45 s)."""
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_LLM")  # construction seule, aucun appel
    settings = Settings(llm_provider="openai", llm_model="gpt-5-mini", llm_timeout_seconds=30)
    provider = build_llm_provider(settings, {"OPENAI_API_KEY": "sk-test-construction"})
    assert provider.model.request_timeout == 30
    assert provider.long_model.request_timeout == 120
    assert provider._model_for("research_analysis") is provider.long_model
    assert provider._model_for("research_solutions") is provider.long_model
    # Mesure reelle du 11/11/2026 : plan a l'effort « low », delai des analyses (120 s).
    plan = provider._model_for("draft_plan")
    assert plan.reasoning_effort == "low" and plan.request_timeout == 120
    # D-86 (campagne reelle V1) : l'adaptation d'un plan echouait au delai de 30 s (2 x 30 s).
    change = provider._model_for("draft_change")
    assert change.reasoning_effort == "low" and change.request_timeout == 120
    # D-78 : conversation a l'effort « low » (aucun effort configure), meme delai de 30 s.
    for task in ("classify_intent", "clarify", "coach_reply"):
        assert provider._model_for(task).reasoning_effort == "low"
        assert provider._model_for(task).request_timeout == 30
    assert provider.model.reasoning_effort is None


def test_long_tasks_are_routed_to_the_long_model():
    short, long = StubModel(text="court"), StubModel(text="long")
    provider = LangChainProvider(short, long_model=long)
    assert provider.generate_text("research_comparison", MESSAGES) == "long"
    assert provider.generate_text("classify_intent", MESSAGES) == "court"


@pytest.mark.skipif(importlib.util.find_spec("langchain_openai") is None, reason="extra absent")
def test_analysis_tasks_get_a_higher_output_cap(monkeypatch):
    """Recette du 10/11/2026 : une analyse sur 12 sources reelles depassait 4 000 jetons."""
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_LLM")  # construction seule, aucun appel
    settings = Settings(llm_provider="openai", llm_model="gpt-5-mini")
    provider = build_llm_provider(settings, {"OPENAI_API_KEY": "sk-test-construction"})
    assert provider.model.max_tokens == 4000
    assert provider.long_model.max_tokens == 8000


def test_truncated_output_is_reported_as_invalid_not_unavailable():
    class LengthFinishReasonError(Exception):
        pass

    class Truncating(StubModel):
        def _structured(self, messages):
            raise LengthFinishReasonError("troncature")

    with pytest.raises(DomainError) as error:
        LangChainProvider(Truncating()).generate_structured("t", MESSAGES, IntentResult)
    assert error.value.code is ErrorCode.LLM_OUTPUT_INVALID


# --- D-79 : sortie structuree diffusee ---------------------------------------------------------


def test_partial_json_strings_are_read_while_being_written():
    from neurocoach.agent.streaming import partial_string

    buffer = (
        r'{"intent":"information_projet","reply":"Bonjour \"Camille\", voici\nune piste '
        r"é"
    )
    assert partial_string(buffer, "intent") == ("information_projet", True)
    assert partial_string(buffer, "reply") == ('Bonjour "Camille", voici\nune piste é', False)
    assert partial_string(r'{"reply":"coupé \\', "reply")[1] is False
    assert partial_string('{"reply":"coupé \\', "reply") == ("coupé ", False)  # echappement coupe
    assert partial_string(r'{"reply":"a \ud83d', "reply") == ("a ", False)  # paire attendue
    assert partial_string(r'{"reply":"a 😀"', "reply") == ("a \U0001f600", True)
    assert partial_string('{"intent":"au', "reply") == (None, False)


class StreamingStub:
    """Double d'un modele OpenAI diffusant une sortie structuree, fragment par fragment."""

    def __init__(self, pieces, fail_at=None):
        self.pieces, self.fail_at = pieces, fail_at
        self.bound = None
        self.closed = False
        self.sent = 0

    def bind(self, **kwargs):
        self.bound = kwargs
        return self

    def stream(self, messages):
        try:
            for index, piece in enumerate(self.pieces):
                if index == self.fail_at:
                    raise TimeoutError("coupure")
                self.sent += 1
                yield SimpleNamespace(content=piece)
        finally:
            self.closed = True


def test_structured_output_is_streamed_and_validated():
    from neurocoach.agent.schemas import CoachTurn

    payload = CoachTurn(intent="aide", reply="Voici une première piste.").model_dump_json()
    stub = StreamingStub([payload[i : i + 7] for i in range(0, len(payload), 7)])
    seen = []
    result = LangChainProvider(stub, stream_json=True).stream_structured(
        "coach_turn", MESSAGES, CoachTurn, seen.append
    )
    assert result.reply == "Voici une première piste."
    assert stub.bound == {"response_format": CoachTurn} and seen[-1] == payload
    assert stub.closed


def test_a_stop_signal_closes_the_stream_early():
    from neurocoach.agent.schemas import CoachTurn
    from neurocoach.agent.streaming import StopStreaming

    pieces = ['{"intent":"hors_perimetre",', '"reply":"', "texte", " jamais lu", '"}']
    stub = StreamingStub(pieces)

    def stop(buffer):
        if '"intent":"hors_perimetre"' in buffer:
            raise StopStreaming

    provider = LangChainProvider(stub, stream_json=True)
    assert provider.stream_structured("coach_turn", MESSAGES, CoachTurn, stop) is None
    assert stub.sent == 1 and stub.closed  # generation interrompue, connexion fermee


def test_stream_failures_are_mapped_and_invalid_output_is_reported():
    from neurocoach.agent.schemas import CoachTurn

    failing = StreamingStub(['{"intent":"aide",', '"reply":"x"}'], fail_at=1)
    provider = LangChainProvider(failing, stream_json=True)
    with pytest.raises(DomainError) as error:
        provider.stream_structured("coach_turn", MESSAGES, CoachTurn, lambda _: None)
    assert error.value.code is ErrorCode.LLM_UNAVAILABLE
    broken = LangChainProvider(StreamingStub(['{"intent":"inconnue"}']), stream_json=True)
    with pytest.raises(DomainError) as error:
        broken.stream_structured("coach_turn", MESSAGES, CoachTurn, lambda _: None)
    assert error.value.code is ErrorCode.LLM_OUTPUT_INVALID


@pytest.mark.skipif(importlib.util.find_spec("langchain_openai") is None, reason="extra absent")
def test_the_openai_provider_streams_the_coach_turn_at_low_effort(monkeypatch):
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_LLM")  # construction seule, aucun appel
    settings = Settings(llm_provider="openai", llm_model="gpt-5-mini")
    provider = build_llm_provider(settings, {"OPENAI_API_KEY": "sk-test-construction"})
    assert provider.stream_json is True
    model = provider._model_for("coach_turn")
    assert model.reasoning_effort == "low" and model.request_timeout == 30
