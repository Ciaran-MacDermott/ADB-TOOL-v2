"""Named profiles — the swap-one-file seam between the pipeline and the
provider layer.

Each profile is a (provider, model, sampling_defaults) bundle that the
pipeline asks for by name (e.g. `llm.complete("writer", messages=...)`).
Pipeline code never names a model or provider directly; it only asks for
"the writer" or "the brief generator" and lets this file decide where
that maps to today.

When migrating to internally-hosted models:
  1. Make sure providers/internal_stub.py is wired (see its docstring).
  2. Repoint each profile below: change `provider="moonshot"` to
     `provider="internal"`, and update `model` to whatever the internal
     endpoint expects.
  3. Done — no callers need changing.

Profile names are stable strings — pipeline code references them
literally (e.g. llm.complete("writer", ...)). Keep names backward-
compatible if you rename.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    name: str
    provider: str
    model: str
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    timeout: int = 60


# ── Profile registry ──────────────────────────────────────────────────
# Each entry replaces a hardcoded model/provider choice that previously
# lived inside llm_insights_free.py or fs/llm_insights.py. To migrate
# any/all of these to internal hosting, just change the `provider` and
# `model` fields below.

_PROFILES: dict[str, Profile] = {
    # ── ADB pipeline (acc_deck_pkg) ────────────────────────────────
    # Stage 1: structured analytical brief over slide data.
    "brief": Profile(
        name="brief",
        provider="groq",
        model="openai/gpt-oss-120b",
        temperature=0.10,
        top_p=0.95,
        max_tokens=1800,
        timeout=90,
    ),
    # Stage 2 (primary): writes the meta insight from the brief.
    "writer": Profile(
        name="writer",
        provider="moonshot",
        model="kimi-k2.6",
        max_tokens=100,
    ),
    # Stage 3: light proofreader / cleanup pass on the writer's draft.
    "cleanup": Profile(
        name="cleanup",
        provider="moonshot",
        model="kimi-k2.6",
        max_tokens=85,
    ),
    # Fallback writer when the brief stage is unavailable — analyses +
    # writes in one pass on Llama (Groq).
    "fast_writer": Profile(
        name="fast_writer",
        provider="groq",
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        temperature=0.65,
        top_p=0.92,
        max_tokens=180,
    ),
    # Total-slide subheader writer.
    "total_subheader": Profile(
        name="total_subheader",
        provider="groq",
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        temperature=0.5,
        top_p=0.9,
        max_tokens=120,
    ),

    # ── Foodservice pipeline (acc_deck_fs_pkg) ─────────────────────
    # Single-call template-anchored rewrite per slide.
    "fs_insight": Profile(
        name="fs_insight",
        provider="moonshot",
        model="kimi-k2.6",
        max_tokens=150,
    ),
}


def get_profile(name: str) -> Profile:
    if name not in _PROFILES:
        raise KeyError(
            f"Unknown LLM profile: {name!r}. "
            f"Registered: {sorted(_PROFILES)}"
        )
    return _PROFILES[name]


def list_profiles() -> list[str]:
    return sorted(_PROFILES)


def register_profile(profile: Profile) -> None:
    """Override or add a profile at runtime. Useful for tests + the
    internal-team handover path."""
    _PROFILES[profile.name] = profile
