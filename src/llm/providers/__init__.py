"""Provider registry.

Each provider is constructed once and stored in `_REGISTRY` keyed by
short name. `get_provider(name)` is the public accessor used by
`llm.complete()`; profiles map their `provider` field to one of these.

Adding a new provider: import its class, instantiate, register here.
"""

from __future__ import annotations

from llm.providers.base import Provider
from llm.providers.internal_stub import make_internal_provider
from llm.providers.moonshot import MoonshotProvider
from llm.providers.openai_compat import OpenAICompatProvider


_REGISTRY: dict[str, Provider] = {
    # Free-tier providers used by the current ADB pipeline. Each reads its
    # API key from the env var listed below; pipelines never hardcode keys.
    "groq": OpenAICompatProvider(
        name="groq",
        base_url="https://api.groq.com/openai/v1/chat/completions",
        env_var="GROQ_API_KEY",
    ),
    "openrouter": OpenAICompatProvider(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1/chat/completions",
        env_var="OPENROUTER_API_KEY",
    ),
    "moonshot": MoonshotProvider(
        name="moonshot",
        base_url="https://api.moonshot.ai/v1/chat/completions",
        env_var="MOONSHOT_API_KEY",
    ),

    # Placeholder for the internally-hosted endpoint. Edit
    # internal_stub.py:make_internal_provider() to wire it; nothing else
    # in the pipeline needs changing.
    "internal": make_internal_provider(),
}


def get_provider(name: str) -> Provider:
    """Return the registered provider by name."""
    if name not in _REGISTRY:
        raise KeyError(
            f"Unknown LLM provider: {name!r}. "
            f"Registered: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name]


def register_provider(name: str, provider: Provider) -> None:
    """Override or add a provider at runtime. Useful for tests + the
    internal-team handover path (set up provider once at app start)."""
    _REGISTRY[name] = provider


def list_providers() -> list[str]:
    return sorted(_REGISTRY)
