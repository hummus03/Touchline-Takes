"""LLM clients behind one small interface, plus caching and a per-run call budget.

Providers are chosen with ``LLM_PROVIDER``:

* ``offline`` (default): no LLM; agents use deterministic templates/lexicons.
* ``anthropic``: Claude via the official ``anthropic`` SDK.
* ``openai``: any OpenAI-compatible chat API (OpenAI, Ollama, vLLM, ...).

Tests and the evaluation use :class:`FakeLLM`, :class:`RecordedLLM` and
:class:`ScriptedWriterLLM`, which never touch the network.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import requests

# USD per million tokens (input, output). Unknown models are costed at zero.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "gpt-4o-mini": (0.15, 0.60),
}
DEFAULT_MODELS = {"anthropic": "claude-opus-5-5", "openai": "gpt-4o-mini"}


class LLMError(RuntimeError):
    """The provider failed or returned something unusable."""


class BudgetExceeded(LLMError):
    """The per-run LLM call budget is spent."""


@dataclass
class LLMResponse:
    """Text plus accounting for one completion."""

    text: str
    provider: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    cached: bool = False


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Dollar cost of a call from the price table."""
    price_in, price_out = PRICES.get(model, (0.0, 0.0))
    return (tokens_in * price_in + tokens_out * price_out) / 1_000_000


def rough_tokens(text: str) -> int:
    """Cheap token estimate (~4 characters per token) for offline accounting."""
    return max(1, len(text) // 4)


class LLMClient(ABC):
    """Interface every provider implements."""

    provider = "base"

    def __init__(self, model: str = "") -> None:
        self.model = model

    @abstractmethod
    def complete(self, prompt: str, system: str = "", max_tokens: int = 1500) -> LLMResponse:
        """Return a completion for ``prompt``."""


class FakeLLM(LLMClient):
    """Deterministic test double.

    ``responder`` may be a list of strings (returned in order, last one repeats),
    a dict mapping prompt substrings to responses, or a callable ``(prompt, system) -> str``.
    """

    provider = "fake"

    def __init__(self, responder: list[str] | dict[str, str] | Callable[[str, str], str],
                 model: str = "fake-model") -> None:
        super().__init__(model)
        self.responder = responder
        self.calls: list[dict[str, str]] = []

    def complete(self, prompt: str, system: str = "", max_tokens: int = 1500) -> LLMResponse:
        self.calls.append({"prompt": prompt, "system": system})
        if callable(self.responder):
            text = self.responder(prompt, system)
        elif isinstance(self.responder, dict):
            text = next((v for k, v in self.responder.items() if k in prompt), "")
            if not text:
                raise LLMError("FakeLLM has no response for this prompt")
        else:
            index = min(len(self.calls) - 1, len(self.responder) - 1)
            text = self.responder[index]
        return LLMResponse(text=text, provider=self.provider, model=self.model,
                           tokens_in=rough_tokens(system + prompt), tokens_out=rough_tokens(text))


class RecordedLLM(FakeLLM):
    """Replays responses recorded in a JSON fixture: ``[{"match": str, "response": str}]``."""

    provider = "recorded"

    def __init__(self, path: str | Path) -> None:
        records = json.loads(Path(path).read_text(encoding="utf-8"))
        super().__init__({r["match"]: r["response"] for r in records}, model="recorded")


class ScriptedWriterLLM(FakeLLM):
    """An offline stand-in for a generative writer, used by tests and the evaluation.

    It rewrites the grounded fact list from the Writer's prompt in a house voice.
    For prompts mentioning any phrase in ``hallucinate_on`` it also invents
    unsupported claims on the *first* attempt (not on revisions); for phrases in
    ``contradict_on`` it flips match winners and swaps team stats, keeping every
    word so only relation-level checks can catch it. Both let the evaluation
    exercise the fact-check -> revise loop deterministically.
    """

    provider = "scripted"
    INVENTED = [
        "Insiders claim the club will spend 200 million in January [S1].",
        "Rival scouts from Juventus were reportedly in the stands [S1].",
        "The squad trained twice on Sunday at Wembley [S1].",
    ]

    def __init__(self, hallucinate_on: tuple[str, ...] = (),
                 contradict_on: tuple[str, ...] = ()) -> None:
        self.hallucinate_on = tuple(hallucinate_on)
        self.contradict_on = tuple(contradict_on)
        super().__init__(self._write, model="scripted-writer")

    @staticmethod
    def contradict(facts: list[str]) -> list[str]:
        """Garble relations while keeping every word: flip the winner, swap team stats."""
        out = [re.sub(r"^(.+?) beat (.+?) (\d+-\d+)", r"\2 beat \1 \3", f) for f in facts]
        form = [i for i, f in enumerate(out) if re.search(r", (.+?) have \d+ wins?", f)]
        if len(form) >= 2:
            first, second = (re.search(r", (.+?) have", out[i]).group(1) for i in form[:2])
            out[form[0]] = out[form[0]].replace(f", {first} have", f", {second} have")
            out[form[1]] = out[form[1]].replace(f", {second} have", f", {first} have")
            out[form[0]] = re.sub(r"\[ST\d\]", "[ST1][ST2]", out[form[0]])
            out[form[1]] = re.sub(r"\[ST\d\]", "[ST1][ST2]", out[form[1]])
        return out

    def _write(self, prompt: str, _system: str) -> str:
        title = re.search(r"^WORKING TITLE: (.+)$", prompt, re.M)
        facts = re.findall(r"^- FACT: (.+)$", prompt, re.M)
        takes = re.findall(r"^- TAKE: (.+)$", prompt, re.M)
        lines = list(facts)
        revising = "REVISION REQUEST" in prompt
        if not revising and any(p in prompt for p in self.contradict_on):
            lines = self.contradict(lines)
        if not revising and any(p in prompt for p in self.hallucinate_on):
            lines[1:1] = self.INVENTED
        body = [" ".join(lines[:3]), " ".join(lines[3:])] + [" ".join(takes)]
        return f"TITLE: {title.group(1) if title else 'Touchline Take'}\n\n" + "\n\n".join(
            p for p in body if p)


class AnthropicLLM(LLMClient):
    """Claude via the official Anthropic Python SDK."""

    provider = "anthropic"

    def __init__(self, model: str = "", api_key: str = "", effort: str = "medium",
                 client=None) -> None:
        super().__init__(model or DEFAULT_MODELS["anthropic"])
        self.effort = effort
        import anthropic  # pylint: disable=import-outside-toplevel
        self._api_error = anthropic.APIError
        self.client = client or anthropic.Anthropic(api_key=api_key or None)

    def complete(self, prompt: str, system: str = "", max_tokens: int = 1500) -> LLMResponse:
        start = time.perf_counter()
        kwargs = {
            "model": self.model, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "output_config": {"effort": self.effort},
            # Server-side fallback on refusals (see Anthropic docs).
            "betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default",
        }
        if system:
            kwargs["system"] = system
        try:
            response = self.client.beta.messages.create(**kwargs)
        except self._api_error as exc:
            raise LLMError(f"anthropic call failed: {exc}") from exc
        if response.stop_reason == "refusal":
            raise LLMError("anthropic declined the request (refusal)")
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        usage = response.usage
        return LLMResponse(
            text=text, provider=self.provider, model=self.model,
            tokens_in=usage.input_tokens, tokens_out=usage.output_tokens,
            cost_usd=estimate_cost(self.model, usage.input_tokens, usage.output_tokens),
            latency_s=time.perf_counter() - start)


class OpenAICompatibleLLM(LLMClient):
    """Any OpenAI-compatible ``/chat/completions`` endpoint (OpenAI, Ollama, vLLM, ...)."""

    provider = "openai"

    def __init__(self, model: str = "", api_key: str = "", base_url: str = "",
                 timeout: float = 60.0, session: requests.Session | None = None) -> None:
        super().__init__(model or DEFAULT_MODELS["openai"])
        self.api_key = api_key
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

    def complete(self, prompt: str, system: str = "", max_tokens: int = 1500) -> LLMResponse:
        start = time.perf_counter()
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}]
        try:
            resp = self.session.post(
                f"{self.base_url}/chat/completions", timeout=self.timeout,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "messages": messages, "max_tokens": max_tokens})
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"].strip()
        except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"openai-compatible call failed: {exc}") from exc
        usage = data.get("usage", {})
        tin, tout = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        return LLMResponse(text=text, provider=self.provider, model=self.model, tokens_in=tin,
                           tokens_out=tout, cost_usd=estimate_cost(self.model, tin, tout),
                           latency_s=time.perf_counter() - start)


@dataclass
class Usage:
    """Running totals for one pipeline run."""

    calls: int = 0
    cache_hits: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    errors: list[str] = field(default_factory=list)


class GuardedLLM(LLMClient):
    """Wraps a provider with a response cache (SQLite) and a per-run call budget.

    Cache hits are free and do not count against the budget.
    """

    def __init__(self, inner: LLMClient, max_calls: int, cache=None) -> None:
        super().__init__(inner.model)
        self.inner = inner
        self.provider = inner.provider
        self.max_calls = max_calls
        self.cache = cache
        self.usage = Usage()

    def reset_budget(self) -> None:
        """Start a new run's budget."""
        self.usage = Usage()

    def cache_key(self, prompt: str, system: str, max_tokens: int) -> str:
        """Deterministic key for a request."""
        raw = json.dumps([self.inner.provider, self.inner.model, system, prompt, max_tokens])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def complete(self, prompt: str, system: str = "", max_tokens: int = 1500) -> LLMResponse:
        key = self.cache_key(prompt, system, max_tokens)
        if self.cache is not None:
            hit = self.cache.cache_get(key)
            if hit:
                self.usage.cache_hits += 1
                return LLMResponse(text=hit["response"], provider=self.provider,
                                   model=self.model, tokens_in=hit["tokens_in"],
                                   tokens_out=hit["tokens_out"], cached=True)
        if self.usage.calls >= self.max_calls:
            raise BudgetExceeded(f"LLM budget of {self.max_calls} calls exhausted")
        self.usage.calls += 1
        try:
            response = self.inner.complete(prompt, system=system, max_tokens=max_tokens)
        except LLMError as exc:
            self.usage.errors.append(str(exc))
            raise
        self.usage.tokens_in += response.tokens_in
        self.usage.tokens_out += response.tokens_out
        self.usage.cost_usd += response.cost_usd
        if self.cache is not None:
            self.cache.cache_put(key, self.provider, self.model, response.text,
                                 response.tokens_in, response.tokens_out)
        return response


def build_llm(settings, cache=None) -> GuardedLLM | None:
    """Create the configured provider wrapped in cache + budget, or ``None`` if offline."""
    provider = settings.llm_provider
    inner: LLMClient | None = None
    if provider == "anthropic":
        inner = AnthropicLLM(settings.llm_model, settings.anthropic_api_key, settings.llm_effort)
    elif provider == "openai":
        inner = OpenAICompatibleLLM(settings.llm_model, settings.openai_api_key,
                                    settings.openai_base_url, settings.request_timeout * 6)
    if inner is None:
        return None
    return GuardedLLM(inner, settings.llm_max_calls_per_run,
                      cache if settings.llm_cache else None)


def parse_json_object(text: str) -> dict:
    """Extract the first JSON object from an LLM reply."""
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise LLMError("no JSON object in reply")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise LLMError(f"invalid JSON: {exc}") from exc
