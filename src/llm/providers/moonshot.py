"""Moonshot (Kimi) provider.

Subclass of OpenAICompatProvider that handles Moonshot-specific quirks:

  - kimi-k2.6 in thinking-disabled mode hard-locks temperature=0.6 and
    top_p=0.95 server-side. Sending other values returns HTTP 400, so
    we deliberately drop them from the payload.
  - Requires a `thinking: {"type": "disabled"}` field — without it the
    model may emit reasoning preambles.

If you hit Moonshot's "thinking enabled" mode in future, this is the
file to extend.
"""

from __future__ import annotations

from llm.providers.openai_compat import OpenAICompatProvider


class MoonshotProvider(OpenAICompatProvider):
    def _build_payload(
        self,
        *,
        messages: list[dict],
        model: str,
        temperature: float | None,
        top_p: float | None,
        max_tokens: int | None,
    ) -> dict:
        # Deliberately ignore temperature / top_p — Moonshot rejects them
        # in thinking-disabled mode. The fixed server-side values
        # (temperature=0.6, top_p=0.95) match what the original direct
        # HTTP code was effectively using.
        payload: dict = {
            "model": model,
            "messages": messages,
            "thinking": {"type": "disabled"},
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        return payload
