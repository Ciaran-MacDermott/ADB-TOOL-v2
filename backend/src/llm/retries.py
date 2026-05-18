"""Shared exponential-backoff helper for provider retries.

The original codebase reimplemented this loop inside every `_call_*`
function in `llm_insights_free.py` and `acc_deck_fs_pkg/llm_insights.py`
— five copies, three subtly different. Centralised here so the next
provider implementation gets it for free and tweaks land in one place.
"""

from __future__ import annotations

import time
from typing import Callable, TypeVar

from llm.errors import ProviderRateLimited, ProviderUnavailable

T = TypeVar("T")

# Default backoff schedule: 10s, 20s, 40s, 80s — matches the prior
# `wait = 10 * (2 ** attempt)` pattern used by the Groq + Moonshot calls.
DEFAULT_RETRIES = 4
DEFAULT_BASE_DELAY = 10.0


def with_retries(
    fn: Callable[[], T],
    *,
    retries: int = DEFAULT_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    is_retryable: Callable[[Exception], bool] | None = None,
    tag: str = "provider",
) -> T:
    """Call fn() with exponential backoff on retryable failures.

    Raises ProviderRateLimited / ProviderUnavailable after the final
    attempt; the original exception is chained as __cause__.
    """
    last: Exception | None = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — central translation
            last = exc
            if is_retryable is not None and not is_retryable(exc):
                raise
            if attempt == retries - 1:
                break
            wait = base_delay * (2 ** attempt)
            print(f"  [{tag}] retry {attempt + 1}/{retries} after {wait:.0f}s — {exc.__class__.__name__}")
            time.sleep(wait)

    # Fall-through: last attempt failed.
    msg = f"[{tag}] failed after {retries} attempts: {last.__class__.__name__}: {last}"
    if isinstance(last, ProviderRateLimited):
        raise ProviderRateLimited(msg) from last
    raise ProviderUnavailable(msg) from last
