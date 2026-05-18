"""Circana LLM client — single seam between the deck pipeline and the
underlying model provider.

THE SWAP-ONE-MODULE PROMISE
----------------------------
The deck pipeline (acc_deck_pkg, acc_deck_fs_pkg) NEVER imports
`requests`, `groq`, `openai`, or `anthropic` directly. It only ever
calls `llm.complete(profile=..., messages=...)`. This means migrating to
internally-hosted models is a single-file change — see profiles.py and
providers/internal.py.

Public surface:
  complete(profile, *, messages, max_tokens=None, **overrides) -> str
  list_profiles() -> list[str]

Conventions:
  - profile is a string key declared in profiles.py
  - messages is a list of {"role": ..., "content": ...} dicts (OpenAI shape)
  - max_tokens / temperature / top_p / timeout passed via **overrides override
    the profile defaults

System prompts stay where they are (in `acc_deck_pkg/llm_insights_free.py`
and `acc_deck_fs_pkg/prompts/*.md`) — this layer is purely transport.

──────────────────────────────────────────────────────────────────────────
NETWORK POLICY — egress
──────────────────────────────────────────────────────────────────────────
Every call from `complete()` resolves a profile to a provider, and the
provider makes ONE outbound HTTPS POST. URL list lives in
`providers/__init__.py` — keep that file as the source of truth when
you draft the firewall allowlist. Today (May 2026):

  - api.groq.com:443       brief / fast_writer / total_subheader
  - api.moonshot.ai:443    writer / cleanup / fs_insight  (Kimi K2.6)
  - openrouter.ai:443      registered, no profile currently routes here

After `providers/internal_stub.py` is wired and `profiles.py` repointed,
the only outbound LLM traffic will be to the internal Circana endpoint.
"""

from __future__ import annotations

from llm.errors import (
    ProviderError,
    ProviderRateLimited,
    ProviderAuthFailed,
    ProviderUnavailable,
)
from llm.profiles import Profile, get_profile, list_profiles, register_profile
from llm.providers import get_provider, register_provider


def complete(
    profile: str,
    *,
    messages: list[dict],
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    timeout: int | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> str:
    """Run a chat completion through the provider that owns this profile.

    The profile (e.g. "writer", "brief", "cleanup") declares a default
    provider, model, and sampling params. Per-call overrides win.

    Returns the assistant's text reply (already stripped of provider quirks
    like DeepSeek <think> blocks).
    """
    p = get_profile(profile)
    provider = get_provider(p.provider)

    return provider.complete(
        messages=messages,
        model=model or p.model,
        temperature=temperature if temperature is not None else p.temperature,
        top_p=top_p if top_p is not None else p.top_p,
        max_tokens=max_tokens if max_tokens is not None else p.max_tokens,
        timeout=timeout if timeout is not None else p.timeout,
        api_key=api_key,  # None → provider falls back to its own env var
    )


__all__ = [
    "complete",
    "list_profiles",
    "Profile",
    "get_profile",
    "register_profile",
    "get_provider",
    "register_provider",
    "ProviderError",
    "ProviderRateLimited",
    "ProviderAuthFailed",
    "ProviderUnavailable",
]
