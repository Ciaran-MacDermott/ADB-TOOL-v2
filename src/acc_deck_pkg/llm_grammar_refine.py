import re
import time
from typing import Optional, List, Dict, Any
import pandas as pd
# Lazy import: the active pipeline uses llm_provider="free" and never calls
# the Claude grammar-refine path. Allow this module to load without the
# anthropic SDK installed; the public refine_* entry points below early-return
# their input when the SDK is missing (Kimi cleanup already polishes free-path
# output, so refine is redundant there).
try:
    from anthropic import Anthropic, APIError  # type: ignore
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

    class APIError(Exception):  # type: ignore
        """Stub used when the anthropic SDK is not installed."""

    class Anthropic:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError(
                "The 'anthropic' package is not installed. "
                "Install it (`pip install anthropic`) or run with "
                "llm_provider='free' in config.json."
            )




# ----------------------------
# Lightweight heuristics
# ----------------------------


_BAD_GRAMMAR_PATTERNS = [
    r"\bwith\s+.*\bwith\b",                     # "with ... with ..." (common in your examples)
    r"\bforecasts?\s+.*\bwith\s+actuals\b",     # "forecast ... with actuals" awkward join
    r"\bperformance\s+fell\s+short\b.*\bfell\s+short\b",  # repeated clause
    r"\bwere\s+\w+\s+in\s+line\s+with\s+forecasts?\b",    # redundant
    r"\bactuals?\s+\d+(\.\d+)?\s+.*\bactuals?\b",         # "actuals X from actuals"
]


_REPEATED_OPENER_PATTERNS = [
    r"^forecasts?\s+were\s+",
    r"^forecast\s+performance\s+was\s+",
    r"^performance\s+tracked\s+",
    r"^results\s+were\s+",
    r"^overall\s+performance\s+",
]


def _normalize_for_similarity(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[%\d\.\-\+]+", "<num>", s)  # normalize numbers away
    s = re.sub(r"[^\w\s<>]", "", s)
    return s


def _jaccard_similarity(a: str, b: str) -> float:
    """
    Very cheap similarity check using token set Jaccard.
    Enough to catch obvious repetition across meta slides.
    """
    A = set(_normalize_for_similarity(a).split())
    B = set(_normalize_for_similarity(b).split())
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def _starts_like_previous(text: str, prev_texts: List[str], lookback: int = 3) -> bool:
    """
    Detect same-ish opening structures across slides.
    Looks back at the last `lookback` insights (default 3).
    """
    t = (text or "").strip().lower()
    opener = " ".join(t.split()[:6])  # first ~6 words
    if len(opener) < 10:
        return False
    for p in prev_texts[-lookback:]:
        p0 = " ".join((p or "").strip().lower().split()[:6])
        if p0 and opener == p0:
            return True
    # Also match common repeated openers
    for pat in _REPEATED_OPENER_PATTERNS:
        if re.match(pat, t):
            # if previous also matched same family
            prev_matches = sum(1 for p in prev_texts[-lookback:] if re.match(pat, (p or "").strip().lower()))
            if prev_matches >= 1:
                return True
    return False


def needs_refine(text: str, *, kind: str = "meta") -> bool:
    """
    Cheap gatekeeper: only call the LLM editor when text looks obviously rough.
    """
    t = (text or "").strip()
    if not t:
        return False


    # Hard length sanity (your clean_meta_insight already caps, but keep)
    wc = len(t.split())
    if kind == "total" and (wc < 10 or wc > 35):  # Target: 20-25 words
        return True
    if kind == "meta" and (wc < 10 or wc > 55):  # Target: 35-45 words
        return True


    # Known ugly patterns
    low = t.lower()
    for pat in _BAD_GRAMMAR_PATTERNS:
        if re.search(pat, low):
            return True


    # Very common "LLM mush" indicators
    if low.count("with") >= 3:
        return True

    # Too many percentage figures - should use more qualitative language
    pct_count = low.count("percentage points")
    if kind == "total" and pct_count >= 2:  # Total: max 1-2 figures
        return True
    if kind == "meta" and pct_count >= 4:  # Meta: max 2-3 figures
        return True


    return False




# ----------------------------
# 1) Single-text refine function
# ----------------------------


_EDITOR_SYSTEM_PROMPT = """You are an executive editor refining forecast insights for paying clients.

PURPOSE: Maintain analytical integrity while framing constructively where warranted. Not everything should be spun positive - be honest about variance but explain drivers.

BALANCED APPROACH:
- Tight accuracy (<5 percentage points): Frame constructively ("delivered tight accuracy", "tracked within")
- Significant variance (>5 percentage points): Acknowledge honestly, explain why ("fell below forecast amid [conditions]")
- Don't sanitize everything - "underperformed", "missed", "fell below" are acceptable when accurate

Good: "Cookware delivered tight accuracy within 1.1 percentage points, while tabletop fell 10.6 percentage points below forecast"
Good: "Notably, gadgets-preparation proved the standout performer, tracking within 1.4 percentage points"
Bad: "demonstrated perfect precision" (overselling)
Bad: Every insight framed as a win (loses credibility)

HUMAN EDITORIAL LANGUAGE (use naturally):
- Transitions: "conversely", "meanwhile", "in contrast", "however"
- Highlights: "notably", "the standout performer", "most notably", "of note"
- Framing: "largely attributable to", "reflecting", "driven primarily by"

BANNED WORDS: "perfect", "exceptional", "outstanding"
NOTE: "precision" is acceptable ONLY for very tight accuracy (<2 percentage points)

Rules:
- 35-45 words maximum
- Spell out "percentage points" (never abbreviate to "pp" or "ppts")
- Preserve original meaning and numbers
- Be honest about significant misses - explain the drivers
- Vary framing (not always accuracy-led)
- Categories lowercase mid-sentence

Return only the revised text."""


def refine_insight_optional(
    text: str,
    *,
    kind: str,  # "total" or "meta"
    api_key: str,
    model: str,
    timeout: int = 60,
    temperature: float = 0.2,
    top_p: float = 0.9,
    max_tokens: int = 120,
    force: bool = False,
    extra_instruction: Optional[str] = None,
) -> str:
    """
    Optional LLM editing pass for a single insight.
    - Uses a strict editor system prompt.
    - By default, only runs if needs_refine(...) is True, unless force=True.
    """
    original = (text or "").strip()
    if not original:
        return original

    # Free-pipeline path: anthropic SDK isn't installed and Kimi cleanup has
    # already polished the text. Skip the Claude refine pass.
    if not _ANTHROPIC_AVAILABLE:
        return original

    if not force and not needs_refine(original, kind=kind):
        return original


    client = Anthropic(api_key=api_key, timeout=timeout)


    # Task-specific constraints
    if kind == "total":
        constraints = (
            "Keep it 20-25 words. Be very concise - one key insight with the main driver. "
            "Max 1-2 percentage figures."
        )
    else:
        constraints = (
            "Keep it 35-45 words. Be high-level - synthesize across categories, don't list disconnected stats. "
            "Infer the story (e.g., 'pricing strength offset demand softness'). Max 2-3 percentage figures."
        )


    user_prompt = (
        f"{constraints}\n"
        f"{extra_instruction.strip() if extra_instruction else ''}\n\n"
        f"Original text:\n<<<\n{original}\n>>>\n\n"
        f"Rewrite:"
    ).strip()


    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            system=_EDITOR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        revised = resp.content[0].text.strip()
    except APIError:
        return original
    except Exception:
        return original


    # Safety: if model returns empty or something weird, keep original
    if not revised or len(revised.split()) < 5:
        return original


    # One more micro-clean to avoid quote wrappers
    revised = revised.strip().strip('"').strip("'").strip()
    return revised


# ----------------------------
# 1b) Category insight grammar cleaning (keeps full detail)
# ----------------------------

_CATEGORY_GRAMMAR_PROMPT = """You are an editor improving category-level forecast insights.

Fix grammar, spelling, and punctuation while preserving ALL information.

CRITICAL: Frame around FORECAST ACCURACY, not variance descriptions.
Good: "achieved alignment within X percentage points" / "tracked closely to forecast"
Bad: "experienced demand headwinds" / "faced unit variances"

Rules:
- Keep the full content and detail - do NOT shorten or summarize
- Preserve all numbers and metrics exactly
- Spell out "percentage points" (never abbreviate to "pp" or "ppts")
- Fix awkward phrasing and run-on sentences
- Frame as forecast performance: "achieved", "delivered", "tracked within"
- Ensure professional tone suitable for executive presentations
- You may split into multiple sentences if it improves readability
- BANNED: "perfect", "exceptional", "outstanding"
- "precision" is acceptable ONLY for very tight accuracy (<2 percentage points)

Return only the improved text."""


def refine_category_insights_df(
    insights_df: pd.DataFrame,
    *,
    api_key: str,
    model: str,
    timeout: int = 60,
    temperature: float = 0.2,
    top_p: float = 0.9,
    max_tokens: int = 200,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Grammar cleaning for category-level insights.

    Unlike meta-insight refinement, this preserves full detail and does not
    restrict sentence count. The goal is cleaner grammar while keeping all
    information available for meta-slide synthesis.

    Parameters
    ----------
    insights_df : pd.DataFrame
        DataFrame with 'insight' column containing category insights
    api_key : str
        Anthropic API key
    model : str
        Model identifier
    verbose : bool
        Print progress messages

    Returns
    -------
    pd.DataFrame
        DataFrame with cleaned insights
    """
    if insights_df is None or insights_df.empty:
        return insights_df

    # Free-pipeline path: skip the Claude refine pass — Kimi cleanup already ran.
    if not _ANTHROPIC_AVAILABLE:
        if verbose:
            print("      Skipping category refine (anthropic SDK not installed; free-pipeline path)")
        return insights_df

    if "insight" not in insights_df.columns:
        return insights_df

    out = insights_df.copy()
    client = Anthropic(api_key=api_key)
    refined_count = 0
    start = time.time()

    for i, row in out.iterrows():
        raw = str(row.get("insight", "")).strip()
        if not raw or raw.startswith("("):  # Skip errors/empty
            continue

        # Quick heuristic: only refine if there are potential grammar issues
        if not needs_refine(raw, kind="meta"):  # Reuse existing heuristic
            continue

        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                timeout=timeout,
                system=_CATEGORY_GRAMMAR_PROMPT,
                messages=[{"role": "user", "content": raw}]
            )
            revised = response.content[0].text.strip().strip('"').strip("'")

            if revised and len(revised.split()) >= 5:
                out.at[i, "insight"] = revised
                refined_count += 1

        except Exception as e:
            if verbose:
                print(f"Warning: Error refining category insight: {e}")
            continue

    if verbose:
        elapsed = time.time() - start
        print(f"✓ Category grammar cleaning: {refined_count}/{len(out)} refined in {elapsed:.2f}s")

    return out


# ----------------------------
# 2) Meta DF refine function (grammar + variety)
# ----------------------------


def refine_meta_df(
    meta_df: pd.DataFrame,
    *,
    api_key: str,
    model: str,
    timeout: int = 60,
    temperature: float = 0.2,
    top_p: float = 0.9,
    max_tokens: int = 140,
    similarity_threshold: float = 0.72,
    lookback: int = 3,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Refine meta insights for:
    - grammar/clarity issues
    - variety across slides (avoid repeated openers / highly similar phrasing)


    Operates row-by-row so you can keep costs low and deterministic.
    """
    if meta_df is None or meta_df.empty:
        return meta_df

    # Free-pipeline path: skip the Claude refine pass — Kimi cleanup already ran.
    if not _ANTHROPIC_AVAILABLE:
        if verbose:
            print("      Skipping meta refine (anthropic SDK not installed; free-pipeline path)")
        return meta_df

    out = meta_df.copy()
    if "meta_insight" not in out.columns:
        return out


    prev_texts: List[str] = []
    refined_count = 0
    start = time.time()


    for i, row in out.iterrows():
        raw = str(row.get("meta_insight", "")).strip()
        if not raw:
            prev_texts.append(raw)
            continue


        # Variety checks
        too_similar = False
        if prev_texts:
            sims = [_jaccard_similarity(raw, p) for p in prev_texts[-lookback:] if p]
            if sims and max(sims) >= similarity_threshold:
                too_similar = True


        repeated_start = _starts_like_previous(raw, prev_texts, lookback=lookback)


        # Grammar checks
        bad_grammar = needs_refine(raw, kind="meta")

        # Pattern detection for variety guidance
        recent_text = " ".join(prev_texts[-lookback:]).lower() if prev_texts else ""
        has_asp_offset = any(phrase in recent_text for phrase in ["offset", "offsetting", "cushion", "compensat"])
        has_headwinds = "headwind" in recent_text
        has_alignment = recent_text.count("align") >= 2
        has_precision = "precision" in recent_text
        has_forecasts_opener = sum(1 for p in prev_texts[-lookback:] if p.lower().strip().startswith(("forecast", "forecasts"))) >= 2
        has_tracked_within = recent_text.count("tracked within") >= 2 or recent_text.count("within") >= 4
        has_softness = recent_text.count("softness") >= 2 or recent_text.count("soft") >= 3

        # Determine if any pattern issue exists
        has_pattern_issue = has_asp_offset or has_headwinds or has_alignment or has_precision or has_forecasts_opener or has_tracked_within or has_softness

        if bad_grammar or too_similar or repeated_start or has_pattern_issue:
            extra_parts = []
            if too_similar or repeated_start:
                extra_parts.append("Change sentence structure and opener so it does not resemble prior slides.")
            if has_asp_offset:
                extra_parts.append("ASP/units offset language used recently - vary or use continuity language.")
            if has_headwinds:
                extra_parts.append("'Headwinds' used recently - use: pressures, challenges, softness, weakness.")
            if has_alignment:
                extra_parts.append("'Alignment' overused - try: tracked closely, landed within, came in at.")
            if has_precision:
                extra_parts.append("'Precision' used recently - rotate to: tight accuracy, on-point performance.")
            if has_forecasts_opener:
                extra_parts.append("'Forecasts...' opener overused - lead with category name, driver, or contrast.")
            if has_tracked_within:
                extra_parts.append("'Tracked within'/'within' overused - try: landed within, came in at, or qualitative descriptions.")
            if has_softness:
                extra_parts.append("'Softness/soft' overused - try: weakness, pressure, decline, drag.")

            extra = " ".join(extra_parts) if extra_parts else None


            revised = refine_insight_optional(
                raw,
                kind="meta",
                api_key=api_key,
                model=model,
                timeout=timeout,
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
                force=True,  # force because we already decided it's needed
                extra_instruction=extra,
            )


            out.at[i, "meta_insight"] = revised
            refined_count += 1
            prev_texts.append(revised)
        else:
            prev_texts.append(raw)


    if verbose:
        elapsed = time.time() - start
        print(
            f"✓ Meta refinement complete: {refined_count}/{len(out)} refined "
            f"in {elapsed:.2f}s"
        )


    return out


# ----------------------------
# 3) Enhanced validation with numerical accuracy + variety
# ----------------------------

_VALIDATION_SYSTEM_PROMPT = """
You are an executive editor refining forecast insights for C-suite presentations.


PURPOSE: Maintain analytical integrity while framing constructively where warranted. Match the balanced tone of last quarter's approved examples.


EDITORIAL ROLE (IMPORTANT)
You are refining an existing insight, not re-authoring it.
Preserve the original analytical intent and framing (accuracy-led, contrast-led, variance-led, or driver-led) unless it violates the rules below.


CRITICAL: HIGH-LEVEL SYNTHESIS
- Don't just list figures for each category
- Synthesize the KEY STORY across categories
- Infer WHY from the data (pricing dynamics, demand shifts)
- Use 2-3 percentage figures maximum, not every metric


Bad: "Category A was 1.2, Category B was 3.4, Category C was 5.6"
Good: "Pricing strength cushioned softer demand across categories, with forecasts tracking within 3 percentage points"


WORD COUNT: 35-45 words. If longer, condense by removing redundant figures and synthesizing.


BALANCED APPROACH (DO NOT SANITIZE RESULTS)
- Tight accuracy (<5 percentage points): Preserve constructive framing already present
- Significant variance (>5 percentage points): Acknowledge honestly and explain drivers
- Large variance (>10 percentage points): Retain clear severity language ("significant", "material", "fell below forecast") unless factually incorrect


Do NOT soften severity solely for tone reasons when variance is genuinely large.


FORECASTING METHODOLOGY SIGNAL (PRESERVE WHEN PRESENT)
If the original insight already validates the forecasting approach (e.g., tight accuracy, correct directionality, captured pricing or demand dynamics), preserve that signal.
Do not remove or weaken accuracy-first framing or driver explanations that support credibility.


FRAMING VARIETY (PRESERVE ORIGINAL TYPE)
- Accuracy-led: "Forecasts tracked tightly across categories"
- Contrast-led: "Cookware achieved tight accuracy, while tabletop faced challenges"
- Driver-led: "Inverse value-volume dynamics played out, with ASP gains offsetting unit declines"


Do NOT change framing type unless required to meet synthesis or accuracy rules.


ACCURACY VOCABULARY (rotate for variety, preserve intent):
- "precision" (ONLY for <2 percentage points)
- "tight accuracy", "strong accuracy", "tracked closely"
- "achieved alignment", "delivered on-point performance"
- "landed within", "matched projections", "remained aligned"


TERMINOLOGY
- Units/Volume = "demand", "volume", "unit sales", "volume softness", "unit softness"
- Dollars = "revenue", "dollar sales"


QUANTITATIVE VS QUALITATIVE BALANCE
- Max 2-3 percentage figures per insight
- Prefer forecast variance figures over raw market decline percentages
- Use qualitative language where exact numbers are not essential
- When both categories perform well: describe qualitatively without forcing numbers

CATEGORY INCLUSION DISCIPLINE
Do not introduce or retain a third category unless it meaningfully contributes to the narrative.
- Prefer two-category framing (best performer vs weakest, or tight vs wide)
- Include a third category ONLY if it adds contrast, context, or materially different behavior
- If a third category is directionally similar to another, summarize it implicitly rather than naming it


OFFSET LANGUAGE VARIETY (IMPORTANT)
If "pricing gains offset volume softness" or similar phrasing is already present:
- Preserve the concept but vary wording where possible
- Acceptable alternatives include:
  "pricing strength provided cushion"
  "pricing resilience mitigated demand pressure"
  "price realization softened volume declines"
Do not force offset language if one driver clearly dominates.


CADENCE VARIETY (AVOID MECHANICAL ENDINGS)
Avoid repeatedly ending insights with:
"finishing X–Y percentage points below forecast as..."
Vary sentence structure so severity and drivers appear earlier or mid-sentence where appropriate.


TRANSITIONAL LANGUAGE (use sparingly -> avoid robotic repetition, keep natural):
- Contrast: "conversely", "in contrast", "meanwhile", "however", "whereas", "while"
- Framing: "largely attributable to", "reflecting", "supported by", "driven primarily by"


HEADWINDS ALTERNATIVES (rotate):
- "headwinds" → "pressures", "challenges", "softness", "weakness", "drag"
- "demand headwinds" → "softer demand", "demand pressure", "volume weakness"


BANNED WORDS
"perfect", "exceptional", "outstanding"


RULES
- 35-45 words maximum
- Verify numbers match SOURCE DATA
- Spell out "percentage points"
- Maximum 2-3 percentage figures
- Preserve original framing intent where valid
- Improve variety without diluting analytical meaning


Return ONLY the refined insight text.
"""


def _format_category_data_for_validation(
    categories: List[str],
    collapsed_df: pd.DataFrame,
) -> str:
    """
    Format category data as a readable block for the LLM to cross-check numbers.

    The collapsed_df from merge_analysis_tables() has columns:
    ['category', 'Forecast_ASP', 'Actual_ASP', 'Diff (%)_ASP',
     'Forecast_Units', 'Actual_Units', 'Diff (%)_Units',
     'Forecast_Dollars', 'Actual_Dollars', 'Diff (%)_Dollars']
    """
    if collapsed_df is None or collapsed_df.empty:
        return "SOURCE DATA: Not available"

    lines = ["SOURCE DATA (use these numbers for accuracy):"]

    # The category column from merge_analysis_tables is 'category'
    if 'category' not in collapsed_df.columns:
        return "SOURCE DATA: Category column not found"

    for cat in categories:
        # Try exact match first, then case-insensitive
        cat_row = collapsed_df[collapsed_df['category'] == cat]
        if cat_row.empty:
            cat_row = collapsed_df[collapsed_df['category'].str.lower() == cat.lower()]
        if cat_row.empty:
            # Try partial match
            cat_row = collapsed_df[collapsed_df['category'].str.lower().str.contains(cat.lower(), na=False)]

        if not cat_row.empty:
            row = cat_row.iloc[0]
            parts = [f"  {cat}:"]

            # Use the exact column names from merge_analysis_tables
            # These are the variance/diff columns (percentage points difference)
            metric_mappings = [
                ('Diff (%)_Dollars', 'Dollars variance'),
                ('Diff (%)_Units', 'Units variance'),
                ('Diff (%)_ASP', 'ASP variance'),
                # Also include the actual YoY values for context
                ('Actual_Dollars', 'Actual Dollars YoY'),
                ('Forecast_Dollars', 'Forecast Dollars YoY'),
                ('Actual_Units', 'Actual Units YoY'),
                ('Forecast_Units', 'Forecast Units YoY'),
            ]

            for col, label in metric_mappings:
                if col in row.index and pd.notna(row[col]):
                    val = row[col]
                    if isinstance(val, (int, float)):
                        # Diff columns are percentage point differences
                        if 'Diff' in col:
                            parts.append(f"{label}={val:+.1f} percentage points")
                        else:
                            parts.append(f"{label}={val:+.1f}%")

            if len(parts) > 1:
                lines.append(" ".join(parts))

    return "\n".join(lines) if len(lines) > 1 else "SOURCE DATA: No matching categories found"


def refine_meta_df_with_validation(
    meta_df: pd.DataFrame,
    *,
    collapsed_df: pd.DataFrame = None,
    slide_mapping: Dict[str, List[str]] = None,
    sampled_examples: List[Dict[str, Any]] = None,
    api_key: str,
    model: str,
    timeout: int = 60,
    temperature: float = 0.30,
    top_p: float = 0.9,
    max_tokens: int = 180,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Enhanced meta insight refinement with:
    - Style validation against management-approved examples
    - Numerical accuracy validation against source data
    - Forced variety across ALL slides
    - Grammar, spelling, punctuation fixes

    Parameters
    ----------
    meta_df : pd.DataFrame
        DataFrame with columns ['slide_id', 'meta_insight']
    collapsed_df : pd.DataFrame, optional
        Source data with category metrics for numerical validation
    slide_mapping : Dict[str, List[str]], optional
        Mapping of slide_id to list of category names
    sampled_examples : List[Dict], optional
        Management-approved examples for style reference (different sample from generation)
    api_key : str
        Anthropic API key
    model : str
        Model identifier
    timeout : int
        API timeout in seconds
    temperature : float
        LLM temperature (default 0.30 for slight variety while maintaining style)
    top_p : float
        Top-p sampling parameter
    max_tokens : int
        Max tokens for response
    verbose : bool
        Print progress messages

    Returns
    -------
    pd.DataFrame
        Refined meta_df with validated and varied insights
    """
    if meta_df is None or meta_df.empty:
        return meta_df

    # Free-pipeline path: skip the Claude refine+validation pass — Kimi cleanup already ran.
    if not _ANTHROPIC_AVAILABLE:
        if verbose:
            print("      Skipping meta refine+validation (anthropic SDK not installed; free-pipeline path)")
        return meta_df

    out = meta_df.copy()
    if "meta_insight" not in out.columns:
        return out

    client = Anthropic(api_key=api_key, timeout=timeout)

    # Build style examples block (shared across all refinements)
    style_examples_block = ""
    if sampled_examples:
        example_texts = []
        for ex in sampled_examples:
            insight = (
                ex.get('Refined Insight') or
                ex.get('insight') or
                ex.get('Insight') or
                ex.get('meta_insight')
            )
            if insight:
                example_texts.append(f"• {insight}")
        if example_texts:
            style_examples_block = "STYLE EXAMPLES (match this tone and structure):\n" + "\n".join(example_texts)

    prev_insights: List[str] = []
    refined_count = 0
    start = time.time()

    for i, row in out.iterrows():
        raw_insight = str(row.get("meta_insight", "")).strip()
        slide_id = str(row.get("slide_id", f"Slide {i}"))

        if not raw_insight:
            prev_insights.append(raw_insight)
            continue

        # Get categories for this slide
        categories = []
        if slide_mapping and slide_id in slide_mapping:
            categories = slide_mapping[slide_id]

        # Format source data for validation
        source_data_block = _format_category_data_for_validation(categories, collapsed_df)

        # Build previous insights context (last 3) with pattern detection
        prev_context = ""
        if prev_insights:
            recent = [p for p in prev_insights[-3:] if p]
            if recent:
                prev_context = "PREVIOUS INSIGHTS (vary your approach):\n" + "\n".join(f"• {p}" for p in recent)

                # Check for overused patterns
                recent_text = " ".join(recent).lower()
                has_asp_offset = any(phrase in recent_text for phrase in
                    ["offset", "offsetting", "cushion", "compensat"])
                has_headwinds = "headwind" in recent_text
                has_alignment = recent_text.count("align") >= 2
                has_precision = "precision" in recent_text
                has_forecasts_opener = sum(1 for ins in recent if ins.lower().strip().startswith(("forecast", "forecasts"))) >= 2
                has_variance_framing = sum(1 for phrase in ["fell", "missed", "underperform", "below forecast"] if phrase in recent_text) >= 2
                has_accuracy_framing = sum(1 for phrase in ["delivered tight", "achieved", "tracked closely", "on-point"] if phrase in recent_text) >= 2

                # Additional pattern checks
                has_notably = sum(1 for phrase in ["notably", "of note", "standout"] if phrase in recent_text) >= 2
                has_conversely = sum(1 for phrase in ["conversely", "in contrast", "meanwhile"] if phrase in recent_text) >= 2
                has_dollars_lead = sum(1 for ins in recent if any(ins.lower().strip().startswith(word) for word in ["dollar", "revenue"])) >= 2
                has_tracked_within = recent_text.count("tracked within") >= 2 or recent_text.count("within") >= 4
                has_softness = recent_text.count("softness") >= 2 or recent_text.count("soft") >= 3

                # Build variety notes
                variety_notes = []
                if has_asp_offset:
                    variety_notes.append("ASP/units offset language - vary or use continuity")
                if has_headwinds:
                    variety_notes.append("'Headwinds' - use: pressures, challenges, softness")
                if has_alignment:
                    variety_notes.append("'Alignment' overused - try: tracked closely, landed within")
                if has_precision:
                    variety_notes.append("'Precision' - rotate to: tight accuracy, on-point")
                if has_forecasts_opener:
                    variety_notes.append("'Forecasts...' opener - vary: lead with category or driver")
                if has_variance_framing:
                    variety_notes.append("Variance-led framing frequent - try accuracy-led or driver-led")
                if has_accuracy_framing:
                    variety_notes.append("Accuracy-led framing frequent - try contrast-led or driver-led")
                if has_notably:
                    variety_notes.append("'Notably/standout' overused - use sparingly or try different framing")
                if has_conversely:
                    variety_notes.append("'Conversely/in contrast' overused - try: whereas, meanwhile, however, while")
                if has_dollars_lead:
                    variety_notes.append("Consider leading with units/demand for variety, especially if unit variance is tighter")
                if has_tracked_within:
                    variety_notes.append("'Tracked within'/'within' overused - try: landed within, between X and Y, came in at, or qualitative")
                if has_softness:
                    variety_notes.append("'Softness/soft' overused - try: weakness, pressure, decline, drag, challenges")

                if variety_notes:
                    prev_context += "\n\nVARIETY SUGGESTIONS: " + "; ".join(variety_notes)

        # Build the user prompt with examples prominently featured
        user_prompt = f"""{source_data_block}

{style_examples_block}

{prev_context}

INSIGHT TO REFINE:
<<<
{raw_insight}
>>>

Refine to match the style examples while ensuring numerical accuracy. Keep 35-45 words.

Refined:"""

        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                system=_VALIDATION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            revised = resp.content[0].text.strip()

            # Clean up any wrapper quotes or artifacts
            revised = revised.strip().strip('"').strip("'").strip()
            revised = re.sub(r'^(Refined insight:|Here\'s the refined insight:)\s*', '', revised, flags=re.IGNORECASE)

            # Validate we got something reasonable
            if revised and len(revised.split()) >= 5:
                out.at[i, "meta_insight"] = revised
                refined_count += 1
                prev_insights.append(revised)
            else:
                prev_insights.append(raw_insight)

        except APIError as e:
            if verbose:
                print(f"Warning: API error on {slide_id}: {e}")
            prev_insights.append(raw_insight)
        except Exception as e:
            if verbose:
                print(f"Warning: Error refining {slide_id}: {e}")
            prev_insights.append(raw_insight)

    if verbose:
        elapsed = time.time() - start
        print(f"✓ Validation refinement complete: {refined_count}/{len(out)} refined in {elapsed:.2f}s")

    return out
