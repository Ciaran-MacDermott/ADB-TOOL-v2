"""Placeholder for the internally-hosted Circana model.

This is the seam where a downstream team plugs in an internally-hosted
model endpoint. Two scenarios:

1. Your endpoint speaks the OpenAI Chat Completions protocol
   (vLLM, TGI, Ollama, FastChat, LM Studio, Anyscale, Together, etc).
   Replace the body of `make_internal_provider()` below with a one-line
   instantiation of OpenAICompatProvider — that's it.

2. Your endpoint has a bespoke shape (custom auth, non-OpenAI payload).
   Subclass OpenAICompatProvider and override `_build_payload` and/or
   `_parse_response` and/or the auth header construction. See
   `moonshot.py` for the canonical "subclass and override one method"
   pattern.

After implementing, edit `llm/profiles.py` to point each profile's
`provider` field at "internal" — no other files need changing.

──────────────────────────────────────────────────────────────────────────
INTERNAL-LLM MIGRATION CHECKLIST
──────────────────────────────────────────────────────────────────────────
Wiring this file + repointing profiles.py is what eliminates the three
external LLM domains (api.groq.com, api.moonshot.ai, openrouter.ai)
from the runtime egress allowlist. Until then, those domains must stay
reachable from the deployment environment.

  Step 1 (here):              base_url = "https://<your-internal-host>/v1/chat/completions"
                              env_var  = "INTERNAL_LLM_API_KEY"
  Step 2 (profiles.py):       change every profile's provider="internal"
  Step 3 (firewall):          drop api.groq.com / api.moonshot.ai / openrouter.ai
                              from runtime allowlist
  Step 4 (env):               INTERNAL_LLM_API_KEY=... in the prod env
"""

from __future__ import annotations

from llm.errors import ProviderUnavailable
from llm.providers.base import Provider
from llm.providers.openai_compat import OpenAICompatProvider


def make_internal_provider() -> Provider:
    """Build the internal provider singleton.

    EDIT THIS WHEN MIGRATING:
      base_url: full URL to your internal /v1/chat/completions endpoint
      env_var:  env var that holds the auth token

    Example replacement (uncomment + customise):

        return OpenAICompatProvider(
            name="internal",
            base_url="https://llm.internal.circana.com/v1/chat/completions",
            env_var="INTERNAL_LLM_API_KEY",
        )
    """
    return _UnconfiguredInternalProvider()


class _UnconfiguredInternalProvider:
    """Until make_internal_provider() is configured, every call fails
    loudly so misrouted profiles surface immediately rather than
    silently fall through to the wrong provider."""

    name = "internal"

    def complete(self, **_kwargs) -> str:  # type: ignore[override]
        raise ProviderUnavailable(
            "Internal LLM provider not configured. Edit "
            "src/llm/providers/internal_stub.py:make_internal_provider() "
            "to point at your hosted endpoint, then update profiles.py "
            "to route the relevant profiles to provider='internal'."
        )
