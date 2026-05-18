"""Grammar-refinement shims.

The original implementation called Anthropic Claude to grammar-polish
generated insights. With the Claude path scrapped (May 2026), the active
free-model pipeline already polishes its output via the Kimi B cleanup
pass inside `llm_insights_free._run_kimi_cleanup`, so this module is now
a deliberate set of pass-through no-ops.

We keep the public function names so existing callers in
`main_meta_modes.py` continue to import without change. If a future
provider needs a real grammar-refine pass, replace the bodies here —
the call sites already handle empty/unchanged returns gracefully.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def refine_insight_optional(text: str, *_args: Any, **_kwargs: Any) -> str:
    """No-op: returns text unchanged."""
    return text or ""


def refine_meta_df(df: pd.DataFrame, *_args: Any, **_kwargs: Any) -> pd.DataFrame:
    """No-op: returns df unchanged."""
    return df


def refine_meta_df_with_validation(
    df: pd.DataFrame,
    *_args: Any,
    **_kwargs: Any,
) -> pd.DataFrame:
    """No-op: returns df unchanged. Validation now lives upstream in
    `llm_insights_free._run_kimi_cleanup`, which trims/cleans within the
    same retry budget instead of via a separate refine pass."""
    return df


def refine_category_insights_df(
    df: pd.DataFrame,
    *_args: Any,
    **_kwargs: Any,
) -> pd.DataFrame:
    """No-op: returns df unchanged."""
    return df


def needs_refine(text: str, *, kind: str = "meta") -> bool:
    """No-op heuristic: never flags refinement as needed in the no-op shim."""
    return False
