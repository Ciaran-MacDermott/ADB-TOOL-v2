from __future__ import annotations
import warnings
warnings.filterwarnings("ignore")
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd


def prepend_sampled_insights_to_prompt(
    base_prompt: str,
    csv_path: str,
    sample_size: int = 5,
    *,
    insight_columns: Optional[List[str]] = None,
    seed: Optional[int] = None,
    section_title: str = "ADDITIONAL STYLE EXAMPLES",
) -> str:
    """Append N sampled example insights from a CSV to the END of a prompt.

    Despite the legacy name, examples land at the END so they don't crowd the
    primary task instructions. Returns base_prompt unchanged when the CSV is
    empty / missing the expected column / yields zero usable rows.
    """
    base_prompt = (base_prompt or "").strip()

    path = Path(csv_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")

    df = pd.read_csv(path)
    if df.empty:
        return base_prompt

    insight_columns = insight_columns or [
        "Refined Insight", "refined_insight", "insight", "Insight", "meta_insight",
    ]
    insight_col = next((c for c in insight_columns if c in df.columns), None)
    if insight_col is None:
        return base_prompt

    n = min(sample_size, len(df))
    sampled = df.sample(n=n, random_state=seed) if seed is not None else df.sample(n=n)

    bullets = []
    for _, r in sampled.iterrows():
        insight = str(r.get(insight_col, "")).strip()
        if not insight or insight.lower() in {"nan", "none"}:
            continue
        bullets.append(f"• {insight}")
    if not bullets:
        return base_prompt

    examples_block = (
        f"\n\n=== {section_title} ===\n"
        "Reference these approved examples for tone and structure (do not copy verbatim):\n"
        + "\n".join(bullets)
    )

    # Idempotency: if the same section was previously appended, replace it.
    marker = f"=== {section_title} ==="
    if marker in base_prompt:
        base_prompt = base_prompt.split(marker, 1)[0].strip()

    return base_prompt + examples_block


def append_sampled_insights_to_prompt(
    base_prompt: str,
    csv_path: str,
    sample_size: int = 5,
    *,
    insight_columns: Optional[List[str]] = None,
    score_columns: Optional[List[str]] = None,   # legacy — ignored
    reason_columns: Optional[List[str]] = None,  # legacy — ignored
    seed: Optional[int] = None,
    section_title: str = "DIRECTOR-APPROVED STYLE EXAMPLES",
    context_description: str = "Use these for style and quality. Do not copy verbatim.",
) -> str:
    """Legacy wrapper kept for callers — score/reason columns are ignored."""
    return prepend_sampled_insights_to_prompt(
        base_prompt=base_prompt,
        csv_path=csv_path,
        sample_size=sample_size,
        insight_columns=insight_columns,
        seed=seed,
        section_title=section_title,
    )


# ------------------------------------------------------------------------------
# Prompt loading
# ------------------------------------------------------------------------------
def _read_text(path: Path) -> str:
    """Read text file with UTF-8 encoding."""
    return path.read_text(encoding="utf-8")


def _load_prompts_from_config(cfg: dict) -> tuple[str, str, str, str]:
    """
    Load prompts from external .md files referenced in cfg["prompts"].
    Paths are resolved relative to cfg["_config_dir"].
    Returns: (system_prompt, meta_prompt, total_prompt, row_prompt_template)
    """
    prompts_cfg = cfg.get("prompts", {})
    base_dir = Path(cfg.get("_config_dir", str(Path.cwd())))

    def resolve_and_read(key: str) -> str:
        rel = prompts_cfg.get(key)
        if not rel:
            raise KeyError(f"Missing prompts.{key} in config.json")
        abs_path = (base_dir / rel).resolve()
        if not abs_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {abs_path}")
        return _read_text(abs_path)

    system_prompt = resolve_and_read("system_prompt_file")
    meta_prompt = resolve_and_read("user_meta_prompt_file")
    total_prompt = resolve_and_read("total_slide_prompt_file")
    row_prompt = resolve_and_read("row_prompt_template_file")

    return system_prompt, meta_prompt, total_prompt, row_prompt


# ------------------------------------------------------------------------------
# Config helpers
# ------------------------------------------------------------------------------
def _get_api_model_and_timeout(cfg: dict) -> tuple[str, int]:
    """
    Read default model + timeout from cfg["api"] (json).
    Fallbacks kept intentionally defensive.
    """
    api = cfg.get("api", {}) if isinstance(cfg.get("api", {}), dict) else {}
    model = api.get("default_model") or api.get("model") or cfg.get("model") or "claude-sonnet-4-20250514"
    timeout = api.get("timeout") or cfg.get("timeout") or 60
    try:
        timeout = int(timeout)
    except Exception:
        timeout = 60
    return model, timeout


def _get_model_for_task(cfg: dict, task: str) -> str:
    """
    Get the model for a specific task (category_insights, meta_insights, total_slide, grammar_refine).
    Falls back to default_model if task-specific model not configured.

    Args:
        cfg: Configuration dictionary
        task: One of 'category_insights', 'meta_insights', 'total_slide', 'grammar_refine'

    Returns:
        Model identifier string
    """
    # Priority 1: Check model_params for task-specific model
    model_params = cfg.get("model_params", {})
    if task in model_params:
        task_model = model_params[task].get("model")
        if task_model:
            return task_model

    # Priority 2: Check api.models for task-specific model (legacy)
    api = cfg.get("api", {}) if isinstance(cfg.get("api", {}), dict) else {}
    models = api.get("models", {})
    if task in models and models[task]:
        return models[task]

    # Fall back to default
    return api.get("default_model") or api.get("model") or "claude-sonnet-4-20250514"


def _resolve_examples_csv(cfg: dict) -> Path | None:
    """
    NEW: Resolve sample insights CSV from config.

    Priority:
    1. cfg["prompts"]["sample_insights_csv"] (relative to config dir)
    2. cfg["prompt_data_dir"] / "placeholder14_results2025.csv" (GUI fallback)
    3. <config_dir>/prompt_data/placeholder14_results2025.csv (legacy fallback)

    Returns Path or None.
    """
    base_dir = Path(cfg.get("_config_dir", str(Path.cwd())))

    # Priority 1: Configured sample insights CSV
    prompts_cfg = cfg.get("prompts", {})
    if "sample_insights_csv" in prompts_cfg:
        csv_rel = prompts_cfg["sample_insights_csv"]
        csv_path = (base_dir / csv_rel).resolve()
        if csv_path.exists():
            print(f"Using configured sample insights: {csv_path.name}")
            return csv_path
        else:
            print(f"Warning: Configured sample insights not found: {csv_path}")
            print(f"          Falling back to default locations...")

    # Priority 2: GUI passes prompt_data_dir when folder exists
    if cfg.get("prompt_data_dir"):
        p = Path(cfg["prompt_data_dir"]) / "placeholder14_results2025.csv"
        if p.exists():
            print(f"Using GUI prompt_data_dir: {p.name}")
            return p.resolve()

    # Priority 3: Legacy fallback relative to config folder
    p = (base_dir / "prompt_data" / "placeholder14_results2025.csv").resolve()
    if p.exists():
        print(f"Using legacy fallback: {p.name}")
        return p

    print("Warning: No sample insights CSV found - prompts will not include examples")
    return None

from pathlib import Path


def _append_examples_if_available(cfg: dict, meta_prompt: str, total_prompt: str) -> tuple:
    # Check if prompt_data directory exists - skip entirely if not present
    base_dir = Path(cfg.get("_config_dir", str(Path.cwd())))
    prompt_data_dir = base_dir / "prompt_data"

    if not prompt_data_dir.exists() or not prompt_data_dir.is_dir():
        print("No prompt_data directory found - skipping example sampling")
        return meta_prompt, total_prompt

    sampling_cfg = cfg.get("prompt_sampling", {})
    if not sampling_cfg.get("enabled", True):
        print("Prompt sampling disabled in config")
        return meta_prompt, total_prompt


    max_samples_meta = max(0, min(int(sampling_cfg.get("max_samples_meta", 5)), 5))
    max_samples_total = max(0, min(int(sampling_cfg.get("max_samples_total", 3)), 5))


    print(f"Appending examples: {max_samples_meta} to meta, {max_samples_total} to total (random selection)")


    def resolve_csv(rel_or_abs: str | None) -> str | None:
        if not rel_or_abs:
            return None
        p = Path(rel_or_abs)
        if p.is_absolute():
            return str(p)
        return str((base_dir / rel_or_abs).resolve())


    meta_csv = resolve_csv(cfg.get("prompts", {}).get("sample_insights_meta_csv"))
    total_csv = resolve_csv(cfg.get("prompts", {}).get("sample_insights_total_csv"))


    if meta_csv and max_samples_meta > 0:
        try:
            meta_prompt = append_sampled_insights_to_prompt(
                base_prompt=meta_prompt,
                csv_path=meta_csv,
                sample_size=max_samples_meta,
                seed=None,
                section_title="EXAMPLE INSIGHTS (PAST DECKS - META SLIDES)",
                context_description="Study these for style and quality. Do not copy verbatim."
            )
        except Exception as e:
            print(f"Warning: Failed to append meta examples: {e}")


    if total_csv and max_samples_total > 0:
        try:
            total_prompt = append_sampled_insights_to_prompt(
                base_prompt=total_prompt,
                csv_path=total_csv,
                sample_size=max_samples_total,
                seed=None,
                section_title="EXAMPLE INSIGHTS (PAST DECKS - TOTAL SLIDES)",
                context_description="Study these for style and quality. Do not copy verbatim."
            )
        except Exception as e:
            print(f"Warning: Failed to append total examples: {e}")


    return meta_prompt, total_prompt




