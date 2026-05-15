"""Provider-agnostic exception hierarchy.

Pipeline code catches these instead of `requests.HTTPError` so a swap to
a different provider doesn't ripple through `try/except` blocks. Each
provider raises the most specific subclass it can identify; the base
`ProviderError` is the fall-through.
"""

from __future__ import annotations


class ProviderError(Exception):
    """Base class for any LLM provider failure surfaced through llm.complete."""


class ProviderAuthFailed(ProviderError):
    """The provider rejected the credentials (401/403)."""


class ProviderRateLimited(ProviderError):
    """Hit a 429 / quota error after exhausting retries."""


class ProviderUnavailable(ProviderError):
    """5xx, network failure, or timeout after exhausting retries."""


class ProviderBadRequest(ProviderError):
    """4xx (other than auth/rate-limit) — usually a malformed payload."""
