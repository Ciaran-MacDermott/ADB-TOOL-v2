"""Provider Protocol.

Every provider (OpenAI-compatible, Moonshot, internal) implements this
single method. Adding a new provider = a new file in this folder + one
line in providers/__init__.py to register it.

The interface is intentionally minimal: messages in, text out. Provider
quirks (Moonshot's locked temperature, DeepSeek's <think> blocks) are
hidden inside the implementation.
"""

from __future__ import annotations

from typing import Protocol


class Provider(Protocol):
    """Stateless transport for a chat completion."""

    name: str  # short stable id, e.g. "groq", "moonshot", "internal"

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
        """Run one completion. Returns the assistant text content.

        Args:
          messages: OpenAI-style list of {"role": ..., "content": ...} dicts.
                    Caller is responsible for putting the system message first
                    when applicable; providers do not synthesise one.
          model: Provider-side model identifier.
          temperature, top_p, max_tokens: sampling controls (None = provider default).
          timeout: per-request timeout in seconds.
          api_key: optional override; None = the provider reads its own env var.

        Raises:
          ProviderAuthFailed, ProviderRateLimited, ProviderUnavailable,
          ProviderBadRequest — see llm.errors.
        """
        ...
