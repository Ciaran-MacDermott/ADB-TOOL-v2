"""
llm_insights.py — Foodservice Forecast Accuracy LLM Insight Generation
======================================================================

Replicates the proven ca_home survey-project pattern (template-anchored
single-call rewrite), adapted for the Foodservice 5-slide deck:

    total / segments / dayparts / service_modes / food_bev

Per slide:
    TEMPLATE  = previous-quarter insight from previous_wave_insights.json
                (keyed by industry_id_key — food-service, food-service-canada,
                food-service-australia).
    NEW DATA  = the current-quarter chart_df values formatted as bullets.

A single direct-HTTP Moonshot call rewrites TEMPLATE for the new figures.
Light cleanup follows: banned-word swap, dash→comma, fluff-prefix strip,
markdown-marker removal, word truncation.

PUBLIC ENTRY POINTS (called by pipeline.main()):
    generate_all_insights(api_key, *chart_dfs..., industry_id_key, update_reference)
        → returns {slide_name: insight_text}
    apply_insights_to_slides(prs, insights, slide_map)
        → writes insights into placeholder 14 of each mapped slide
    save_insights_as_reference(insights, industry_id_key)
        → optionally persist this wave's insights as next quarter's templates
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from acc_deck_pkg.yoy_transformers import excel_round
from llm import complete as llm_complete
from llm.errors import ProviderError


# =============================================================================
# CONFIG
# =============================================================================

_MODULE_DIR  = Path(__file__).parent
PROMPTS_DIR  = _MODULE_DIR / "prompts"

SYSTEM_PROMPT        = (PROMPTS_DIR / "system_prompt.md").read_text(encoding="utf-8")
USER_PROMPT_TEMPLATE = (PROMPTS_DIR / "user_prompt.md").read_text(encoding="utf-8")

_CONFIG_PATH = _MODULE_DIR / "config.json"
_CFG  = json.loads(_CONFIG_PATH.read_text(encoding="utf-8")) if _CONFIG_PATH.exists() else {}
_GEN  = _CFG.get("models", {}).get("generation", {})
_PIPE = _CFG.get("pipeline", {})

_PREV_INSIGHTS_PATH = _MODULE_DIR / "previous_wave_insights.json"

# kimi-k2.6 in thinking-disabled mode hard-locks temperature=0.6 / top_p=0.95
# server-side; sending other values returns HTTP 400. The only creativity
# lever we control is max_tokens — lower values force tighter outputs.
GENERATION_MODEL      = _GEN.get("model",      "kimi-k2.6")
GENERATION_MAX_TOKENS = _GEN.get("max_tokens", 150)

MAX_RETRIES = _PIPE.get("max_retries", 3)
BASE_DELAY  = _PIPE.get("base_delay",  2.0)
WORD_LIMIT  = _PIPE.get("word_limit",  55)

# Provider URL + API key are owned by src/llm/. To swap to internally-hosted
# models edit src/llm/profiles.py — the `fs_insight` profile points at the
# Moonshot provider today; repointing it to "internal" needs no edits here.


# =============================================================================
# POST-PROCESSING (modelled on ca_home/llm_insights.py)
# =============================================================================

# Banned-word substitutions: superlatives the C-suite audience finds insincere,
# plus "percentage points" abbreviations the prompt forbids.
_BANNED_WORD_REPLACEMENTS = [
    (re.compile(r"\bperfect(?:ly)?\b",          re.I), "very tight"),
    (re.compile(r"\bexceptional(?:ly)?\b",      re.I), "strong"),
    (re.compile(r"\boutstanding(?:ly)?\b",      re.I), "solid"),
    (re.compile(r"\bremarkable(?:ly)?\b",       re.I), "notable"),
    (re.compile(r"\bunderscor(?:ing|es?|ed)\b", re.I), "reflecting"),
    # Spell out percentage points
    (re.compile(r"\b(\d+(?:\.\d+)?)\s*pp(?:ts?)?\b",  re.I), r"\1 percentage points"),
    (re.compile(r"\b(\d+(?:\.\d+)?)\s*pts?\b",        re.I), r"\1 percentage points"),
    (re.compile(r"\b(\d+(?:\.\d+)?)\s*bps?\b",        re.I), r"\1 percentage points"),
    (re.compile(r"\bbasis\s+points?\b",                re.I), "percentage points"),
]

# Filler prefixes the model occasionally adds despite system-prompt rules.
# Stripped only when the remaining text is still substantive.
_FLUFF_PREFIX_PATTERNS = [
    r"^slide\s*\d*\s*[:\-–—]?\s*",
    r"^summary\s*:\s*",
    r"^insight\s*:\s*",
    r"^takeaway\s*:\s*",
    r"^observation\s*:\s*",
    r"^note\s*:\s*",
    r"^overall[:,]?\s*",
    r"^in\s+summary[:,]?\s*",
]


def _replace_dashes_with_commas(text: str) -> str:
    """Convert em / en / spaced-hyphen dashes to commas (deck style preference)."""
    if not text:
        return text
    text = re.sub(r"\s*—\s*",  ", ", text)   # em dash
    text = re.sub(r"\s*–\s*",  ", ", text)   # en dash
    text = re.sub(r"\s+[-‒]\s+", ", ", text) # spaced hyphen / figure dash
    text = re.sub(r",\s*,",         ", ", text)
    return text


def _sanitize_banned_words(text: str) -> str:
    if not text:
        return text
    text = _replace_dashes_with_commas(text)
    for pattern, replacement in _BANNED_WORD_REPLACEMENTS:
        text = pattern.sub(replacement, text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_wrappers(text: str) -> str:
    """Remove surrounding straight/curly quotes or backticks."""
    text = (text or "").strip()
    if not text:
        return ""
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        text = text[1:-1].strip()
    for left, right in (("“", "”"), ("‘", "’"), ("`", "`")):
        if text.startswith(left) and text.endswith(right):
            text = text[len(left):-len(right)].strip()
    return " ".join(text.split())


def _strip_markdown_markers(text: str) -> str:
    """
    Remove markdown bold / italic markers and leading bullet glyphs that the
    model sometimes uses to wrap figures (e.g. **0.8**) — these don't render
    as styled text in PowerPoint, they appear as literal characters.
    """
    if not text:
        return text
    # Drop a leading bullet/dash/asterisk if the model opened with one
    text = re.sub(r"^\s*[-•*]+\s*", "", text)
    # Strip ** and __ pairs (and any orphaned ones)
    text = re.sub(r"\*\*", "", text)
    text = re.sub(r"__", "", text)
    # Strip bare * around words but keep words intact (start-of-string and mid-text)
    text = re.sub(r"(?:^|(?<=\s))\*(?=\S)", "", text)
    text = re.sub(r"(?<=\S)\*(?=\s|[.,;:!?]|$)", "", text)
    # Remove inline code backticks
    text = re.sub(r"`+", "", text)
    # Tidy "., " or ".," artifacts → ", "
    text = re.sub(r"\.\s*,", ",", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _strip_fluff_prefixes_safe(text: str) -> str:
    """
    Remove a single recognised fluff prefix (e.g. "Insight:", "Slide 4 -").

    Safety rails (matches ca_home pattern):
      - matched prefix must sit in the first 60 chars
      - remainder must be ≥ 10 chars or original is kept (avoids eating
        legitimate sentence-starting "Lunch:" / "QSR:" / "Total:" labels)
    """
    text = (text or "").lstrip()
    if not text:
        return ""
    original = text
    for pattern in _FLUFF_PREFIX_PATTERNS:
        match = re.match(pattern, text, flags=re.I)
        if not match or match.end() > 60:
            continue
        candidate = text[match.end():].lstrip()
        if len(candidate) < 10:
            continue
        return candidate
    return original


def _truncate_words(text: str, limit: int) -> str:
    words = (text or "").split()
    if len(words) <= limit:
        return text or ""
    out = " ".join(words[:limit]).rstrip(",;:")
    if out and out[-1] not in ".!?":
        out += "."
    return out


def clean_insight(raw_text: str) -> str:
    """
    Light-touch post-processing applied to every model response.

    Order:
        1. _strip_wrappers          → drop surrounding quotes
        2. _strip_markdown_markers  → drop **bold** / *italic* / leading bullets
        3. _strip_fluff_prefixes_safe → drop "Insight:" / "Slide N:" etc.
        4. _strip_wrappers          → again, in case removing prefix exposed quotes
        5. _sanitize_banned_words   → swap superlatives, dashes → commas, spell out pp
        6. _truncate_words          → enforce WORD_LIMIT
        7. ensure trailing punctuation

    Returns "" if cleaning leaves fewer than 8 words (caller treats as skip).
    """
    raw = (raw_text or "").strip()
    if not raw:
        return ""

    cleaned = _strip_wrappers(raw)
    cleaned = _strip_markdown_markers(cleaned)
    cleaned = _strip_fluff_prefixes_safe(cleaned)
    cleaned = _strip_wrappers(cleaned)
    cleaned = _sanitize_banned_words(cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    cleaned = _truncate_words(cleaned, limit=WORD_LIMIT)

    if cleaned and cleaned[-1] not in ".!?":
        cleaned += "."

    return cleaned.strip() if len(cleaned.split()) >= 8 else ""


# =============================================================================
# MODEL CALL — routed through src/llm/ (single seam to swap providers)
# =============================================================================

def _call_moonshot(system: str, user: str) -> str:
    """Route a (system, user) pair through the `fs_insight` profile.

    The profile lives in src/llm/profiles.py and currently points at
    Moonshot Kimi K2.6 in thinking-disabled mode. To swap to internally-
    hosted models, edit profiles.py — this function does not need to
    change.

    Returns "" on final failure (caller treats empty as "skip the slide");
    the underlying provider already exhausts its own retry budget before
    raising, so we don't retry again here.

    Function name kept for back-compat with existing call sites.
    """
    try:
        text = llm_complete(
            "fs_insight",
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            model=GENERATION_MODEL,        # config.json override wins over profile default
            max_tokens=GENERATION_MAX_TOKENS,
            timeout=60,
        )
        return (text or "").strip()
    except ProviderError as exc:
        print(f"      [fs_insight] failed: {exc.__class__.__name__}: {exc}")
        return ""


# =============================================================================
# DATA FORMATTERS — emit one bullet per metric / category
# =============================================================================

def _format_single_chart_data(chart_df: pd.DataFrame) -> str:
    pv = chart_df.pivot(index="metric", columns="f_or_a", values="YoY").copy()
    for col in ("Forecast", "Actual"):
        if col not in pv.columns:
            pv[col] = 0.0
    pv = pv.fillna(0.0)
    pv["Forecast"] = excel_round(pv["Forecast"], decimals=1)
    pv["Actual"]   = excel_round(pv["Actual"],   decimals=1)
    pv["Variance (percentage points)"] = excel_round(pv["Actual"] - pv["Forecast"], decimals=1)

    lines = []
    for metric_name, row in pv.iterrows():
        lines.append(
            f"- {metric_name}: Forecast YoY {row['Forecast']:+.1f}%, "
            f"Actual YoY {row['Actual']:+.1f}%, "
            f"Gap {row['Variance (percentage points)']:+.1f} percentage points"
        )
    return "\n".join(lines)


def _format_dual_chart_data(chart_dfs: List[pd.DataFrame]) -> str:
    parts = []
    for df in chart_dfs:
        label = df.columns.name or "Chart"
        parts.append(f"\n{label}:")
        parts.append(_format_single_chart_data(df))
    return "\n".join(parts)


def _format_slide_data(slide_name: str, *args) -> str:
    """Dispatch to the right formatter based on slide and arg shape."""
    if slide_name in ("dayparts", "service_modes"):
        chart_dfs = args[0]
        if isinstance(chart_dfs, list) and len(chart_dfs) > 1:
            return _format_dual_chart_data(chart_dfs)
        # Single combined chart (e.g. Australia which doesn't split QSR/FSR)
        df = chart_dfs[0] if isinstance(chart_dfs, list) else chart_dfs
        return _format_single_chart_data(df)
    return _format_single_chart_data(args[0])


# =============================================================================
# REFERENCE INSIGHTS (previous-quarter templates per market)
# =============================================================================

def _load_prev_wave_insights(industry_id_key: str) -> Dict[str, Optional[str]]:
    """
    Load previous-quarter approved insights for a market.

    File layout (previous_wave_insights.json):
        {
          "food-service":           {"total": "...", "segments": "...", ...},
          "food-service-canada":    {...},
          "food-service-australia": {...}
        }
    """
    if not _PREV_INSIGHTS_PATH.exists():
        return {}
    try:
        data   = json.loads(_PREV_INSIGHTS_PATH.read_text(encoding="utf-8"))
        market = data.get(industry_id_key, {})
        return {k: v for k, v in market.items() if not k.startswith("_")}
    except Exception as e:
        print(f"      Warning: Could not load reference insights: {e}")
        return {}


def save_insights_as_reference(insights: Dict[str, str], industry_id_key: str) -> None:
    """
    Write this wave's insights back to previous_wave_insights.json so they
    become the rewrite anchors for next quarter's run. Only updates slides
    that produced ≥ 10-word output. Other markets and slides are preserved.
    """
    if not industry_id_key or not insights:
        return
    try:
        data: Dict = {}
        if _PREV_INSIGHTS_PATH.exists():
            data = json.loads(_PREV_INSIGHTS_PATH.read_text(encoding="utf-8"))
        market = data.get(industry_id_key, {})
        for slide, text in insights.items():
            if text and len(text.split()) >= 10:
                market[slide] = text
        data[industry_id_key] = market
        _PREV_INSIGHTS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"      Reference insights updated for '{industry_id_key}' ({len(insights)} slides)")
    except Exception as e:
        print(f"      Warning: Could not save reference insights: {e}")


# =============================================================================
# PUBLIC API
# =============================================================================

def _build_user_prompt(slide_data_text: str, prev_wave_insight: Optional[str]) -> str:
    """
    Assemble the user message: STYLE REFERENCE (if any) + NEW DATA + trailing instruction.
    The previous-quarter insight is offered as a style/tone/length anchor only —
    the prompt explicitly instructs the model not to paraphrase or echo it.
    """
    parts: List[str] = []
    if prev_wave_insight:
        parts.append("STYLE REFERENCE (previous-quarter insight — for tone, "
                     "register, framing approach, and approximate length only; "
                     "do NOT paraphrase, mimic, or echo this text):")
        parts.append(prev_wave_insight.strip())
        parts.append("")
    parts.append("NEW DATA:")
    parts.append(slide_data_text.strip())
    parts.append("")
    parts.append(USER_PROMPT_TEMPLATE.strip())
    return "\n".join(parts)


def generate_all_insights(
    api_key: str,                                       # kept for backward compat
    total_chart_df: pd.DataFrame,
    segment_chart_df: pd.DataFrame,
    daypart_dfs: List[pd.DataFrame],
    service_mode_dfs: List[pd.DataFrame],
    food_bev_df: pd.DataFrame,
    food_bev_map: Dict[str, str] = None,                # accepted, not currently used
    *,
    industry_id_key: Optional[str] = None,
    update_reference: bool = False,
) -> Dict[str, str]:
    """
    Generate one insight per slide (5 slides) using the template-anchored
    single-call pattern. Returns {slide_name: insight_text}.

    slide_name keys (consumed by apply_insights_to_slides):
        total, segments, dayparts, service_modes, food_bev
    """
    print(f"      Model: {GENERATION_MODEL} (Moonshot, thinking-disabled, "
          f"max_tokens={GENERATION_MAX_TOKENS}, word_limit={WORD_LIMIT})")

    prev_wave: Dict[str, Optional[str]] = (
        _load_prev_wave_insights(industry_id_key) if industry_id_key else {}
    )
    loaded = sum(1 for v in prev_wave.values() if v)
    print(f"      Reference templates: {loaded}/5 loaded for '{industry_id_key or 'unknown'}'")

    slide_inputs: Dict[str, str] = {
        "total":         _format_single_chart_data(total_chart_df),
        "segments":      _format_single_chart_data(segment_chart_df),
        "dayparts":      _format_slide_data("dayparts",      daypart_dfs),
        "service_modes": _format_slide_data("service_modes", service_mode_dfs),
        "food_bev":      _format_single_chart_data(food_bev_df),
    }

    insights: Dict[str, str] = {}
    for slide_name, data_text in slide_inputs.items():
        prev        = prev_wave.get(slide_name)
        prev_status = "yes" if prev else "no (cold start)"
        print(f"      [{slide_name}] template={prev_status}, generating...")

        user_prompt = _build_user_prompt(data_text, prev)
        raw         = _call_moonshot(SYSTEM_PROMPT, user_prompt)
        cleaned     = clean_insight(raw)

        insights[slide_name] = cleaned
        if cleaned:
            word_count = len(cleaned.split())
            print(f"        ({word_count} words) {cleaned}")
        else:
            print(f"        (no insight produced)")

    if update_reference and industry_id_key:
        save_insights_as_reference(insights, industry_id_key)

    return insights


def apply_insights_to_slides(
    prs,
    insights: Dict[str, str],
    slide_map: Dict[str, object],
    placeholder_idx: int = 14,
) -> int:
    """Write each insight into placeholder 14 of its mapped slide."""
    from pptx.util import Pt

    applied = 0
    for slide_name, slide in slide_map.items():
        text = insights.get(slide_name, "")
        if not text:
            continue
        try:
            ph = slide.placeholders[placeholder_idx]
            tf = ph.text_frame
            tf.clear()
            p = tf.paragraphs[0]
            p.text = text
            for run in p.runs:
                run.font.size = Pt(20)
                run.font.name = "Roboto Condensed"
            applied += 1
        except (KeyError, AttributeError) as e:
            print(f"      Warning: Could not apply insight to {slide_name}: {e}")
    return applied
