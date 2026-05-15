"""Generic OpenAI-compatible Chat Completions provider.

Covers everything that exposes `POST /v1/chat/completions` with the
standard `{model, messages, temperature, top_p, max_tokens}` payload —
which is most providers and most internal hosting stacks (vLLM, TGI,
Ollama, FastChat, LM Studio, Together, Fireworks, Anyscale).

Used as the base for:
  - GroqProvider             (api.groq.com)
  - OpenRouterProvider       (openrouter.ai)
  - InternalProvider         (your hosted endpoint — see internal_stub.py)

If a provider needs payload tweaks beyond what this class supports
(e.g. Moonshot's `thinking: {"type": "disabled"}`), subclass and override
`_build_payload()`.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import requests

from llm.errors import (
    ProviderAuthFailed,
    ProviderBadRequest,
    ProviderError,
    ProviderRateLimited,
    ProviderUnavailable,
)
from llm.retries import with_retries


# Strip DeepSeek R1 <think>...</think> reasoning blocks — emitted by some
# OpenAI-compatible models (R1, DeepSeek-V3) as part of the assistant text
# content. Cheap to apply universally; harmless on models that don't use it.
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


@dataclass
class OpenAICompatProvider:
    """Generic OpenAI-compatible provider.

    Subclass and override `_build_payload` if your provider needs
    non-standard fields. Most callers should just instantiate this
    directly with their (name, base_url, env_var_for_key)."""

    name: str
    base_url: str  # full URL to chat/completions, e.g. "https://api.groq.com/openai/v1/chat/completions"
    env_var: str   # env var that holds the API key, e.g. "GROQ_API_KEY"

    def _resolve_key(self, override: str | None) -> str:
        if override:
            return override
        key = os.environ.get(self.env_var, "")
        if not key:
            raise ProviderAuthFailed(
                f"[{self.name}] {self.env_var} not set in environment "
                f"and no api_key override passed."
            )
        return key

    def _build_payload(
        self,
        *,
        messages: list[dict],
        model: str,
        temperature: float | None,
        top_p: float | None,
        max_tokens: int | None,
    ) -> dict:
        payload: dict = {"model": model, "messages": messages}
        if temperature is not None:
            payload["temperature"] = temperature
        if top_p is not None:
            payload["top_p"] = top_p
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        return payload

    def _parse_response(self, data: dict) -> str:
        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError) as e:
            raise ProviderError(f"[{self.name}] unexpected response shape: {data}") from e
        # Some providers (R1) leave content empty and put the answer in
        # reasoning_content; fall back to that.
        content = msg.get("content") or msg.get("reasoning_content") or ""
        return _THINK_BLOCK.sub("", content).strip()

    def complete(
        self,
        *,
        messages: list[dict],
        model: str,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        timeout: int = 60,
        api_key: str | None = None,
    ) -> str:
        key = self._resolve_key(api_key)
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(
            messages=messages,
            model=model,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
        )

        def _do_request() -> str:
            resp = requests.post(self.base_url, headers=headers, json=payload, timeout=timeout)
            if resp.status_code == 401 or resp.status_code == 403:
                raise ProviderAuthFailed(
                    f"[{self.name}] {resp.status_code}: {resp.text[:300]}"
                )
            if resp.status_code == 429:
                # Tell the retry layer this is rate-limit (will exponential-backoff).
                raise ProviderRateLimited(f"[{self.name}] 429: {resp.text[:200]}")
            if 500 <= resp.status_code < 600:
                raise ProviderUnavailable(
                    f"[{self.name}] {resp.status_code}: {resp.text[:300]}"
                )
            if not resp.ok:
                raise ProviderBadRequest(
                    f"[{self.name}] {resp.status_code}: {resp.text[:500]}"
                )
            return self._parse_response(resp.json())

        return with_retries(
            _do_request,
            is_retryable=lambda e: isinstance(e, (ProviderRateLimited, ProviderUnavailable)),
            tag=self.name,
        )
