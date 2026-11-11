"""Tests for LLM clients, caching and the call budget (all offline)."""
# pylint: disable=redefined-outer-name

from types import SimpleNamespace

import pytest

from touchline_takes.config import Settings
from touchline_takes.tools.llm import (AnthropicLLM, BudgetExceeded, FakeLLM, GuardedLLM,
                                       LLMError, OpenAICompatibleLLM, ScriptedWriterLLM,
                                       build_llm, estimate_cost, parse_json_object)

from tests.conftest import FakeResponse, FakeSession


def test_guarded_llm_caches_and_budgets(db):
    """Cache hits are free; uncached calls beyond the budget raise."""
    inner = FakeLLM(["one", "two", "three"])
    llm = GuardedLLM(inner, max_calls=2, cache=db)
    assert llm.complete("a").text == "one"
    again = llm.complete("a")
    assert again.cached and again.text == "one" and len(inner.calls) == 1
    llm.complete("b")
    with pytest.raises(BudgetExceeded):
        llm.complete("c")
    assert llm.usage.calls == 2 and llm.usage.cache_hits == 1


def test_build_llm_offline_returns_none():
    """Offline mode means no LLM at all."""
    assert build_llm(Settings(llm_provider="offline")) is None


def test_openai_compatible_client_parses_reply():
    """OpenAI-compatible replies are parsed and costed."""
    session = FakeSession({"/chat/completions": FakeResponse(json_data={
        "choices": [{"message": {"content": " hi "}}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 100}})})
    llm = OpenAICompatibleLLM("gpt-4o-mini", "k", "https://llm.test/v1", session=session)
    resp = llm.complete("hello", system="be brief")
    assert resp.text == "hi" and resp.tokens_in == 1000
    assert resp.cost_usd == pytest.approx(estimate_cost("gpt-4o-mini", 1000, 100))
    broken = OpenAICompatibleLLM("m", "k", "https://llm.test/v1",
                                 session=FakeSession({"x": FakeResponse()}))
    with pytest.raises(LLMError):
        broken.complete("hello")


def test_anthropic_client_with_stubbed_sdk():
    """The Anthropic client sends the expected request and handles refusals."""
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(
            stop_reason="end_turn", content=[SimpleNamespace(type="text", text="Take!")],
            usage=SimpleNamespace(input_tokens=200, output_tokens=50))

    stub = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    llm = AnthropicLLM(client=stub)
    resp = llm.complete("write", system="house style")
    assert resp.text == "Take!" and sent["model"] == "claude-opus-5-5"
    assert sent["system"] == "house style" and sent["fallbacks"] == "default"
    assert resp.cost_usd > 0

    def refuse(**_kwargs):
        return SimpleNamespace(stop_reason="refusal", content=[], usage=None)

    llm.client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=refuse)))
    with pytest.raises(LLMError):
        llm.complete("write")


def test_anthropic_haiku_skips_fallbacks_and_flags_cut_off_replies():
    """Haiku is called without the fallback beta it doesn't accept; a reply cut off at
    max_tokens is an error, not a half-written article."""
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(
            stop_reason="end_turn", content=[SimpleNamespace(type="text", text="Take!")],
            usage=SimpleNamespace(input_tokens=2000, output_tokens=800))

    stub = SimpleNamespace(messages=SimpleNamespace(create=create))
    llm = AnthropicLLM("claude-haiku-5-5", client=stub)
    resp = llm.complete("write", max_tokens=4000)
    assert resp.text == "Take!" and "fallbacks" not in sent and "betas" not in sent
    assert resp.cost_usd == pytest.approx(estimate_cost("claude-haiku-5-5", 2000, 800))

    def cut_off(**_kwargs):
        return SimpleNamespace(stop_reason="max_tokens",
                               content=[SimpleNamespace(type="text", text="Half")],
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    llm.client = SimpleNamespace(messages=SimpleNamespace(create=cut_off))
    with pytest.raises(LLMError, match="cut off"):
        llm.complete("write")


def test_scripted_writer_hallucinates_only_first_time():
    """The scripted writer injects invented claims on first drafts of flagged stories."""
    llm = ScriptedWriterLLM(hallucinate_on=("Arsenal",))
    prompt = "WORKING TITLE: T\n- FACT: Arsenal won [S1].\n- TAKE: Big win."
    first = llm.complete(prompt).text
    assert "200 million" in first and first.startswith("TITLE: T")
    revised = llm.complete(prompt + "\nREVISION REQUEST: fix").text
    assert "200 million" not in revised


def test_scripted_writer_contradicts_relations():
    """Contradiction mode flips winners and swaps team stats without new words."""
    facts = ["Arsenal beat Chelsea 2-1, per X [S1].", "In data, Arsenal have 3 wins [ST1].",
             "In data, Chelsea have 2 wins [ST2]."]
    out = ScriptedWriterLLM.contradict(facts)
    assert out[0].startswith("Chelsea beat Arsenal 2-1")
    assert "Chelsea have 3 wins [ST1][ST2]" in out[1] and "Arsenal have 2 wins" in out[2]
    llm = ScriptedWriterLLM(contradict_on=("Arsenal",))
    prompt = "WORKING TITLE: T\n- FACT: Arsenal beat Chelsea 2-1 [S1].\n- TAKE: Big."
    assert "Chelsea beat Arsenal" in llm.complete(prompt).text
    assert "Arsenal beat Chelsea" in llm.complete(prompt + "\nREVISION REQUEST: x").text


def test_parse_json_object():
    """JSON is extracted from chatty replies."""
    assert parse_json_object('ok {"a": 1} done') == {"a": 1}
    with pytest.raises(LLMError):
        parse_json_object("nothing")
