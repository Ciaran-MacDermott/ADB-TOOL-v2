"""
llm_insights_free.py
====================
Per-slide insight generation for the ADB pipeline.

Architecture per meta slide (direct path only — see commit history for
the old "traditional" branch removed May 2026):
  brief    (Groq, openai/gpt-oss-120b)        → structured analytical brief
  writer   (Moonshot, kimi-k2.6)              → writes meta insight from brief
  cleanup  (Moonshot, kimi-k2.6)              → light proofreader pass
  regex    → strips rhetorical colons / fixes case

Total slide subheader: total_subheader profile (Groq Llama).

Pass-through stubs (kept for back-compat with main_meta_modes.py imports):
  generate_llm_insights_remote()   — returns df unchanged
  generate_meta_slide_insights()   — returns empty DataFrame

All HTTP calls go through `llm.complete(profile=..., messages=...)`. To
swap providers (e.g. internally-hosted models), edit src/llm/profiles.py
— no changes needed in this file.

Provider API keys are resolved by the providers themselves from env
vars (GROQ_API_KEY, MOONSHOT_API_KEY); per-call overrides are still
supported via the `*_api_key` kwargs that main_meta_modes.py forwards.
"""

from __future__ import annotations

import re
import time
from typing import Dict, List, Optional

import pandas as pd

from llm import complete as llm_complete

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
_RHETORICAL_COLON = re.compile(r'\b(\w[\w\s,]{2,40}):\s+(?=[A-Z])')
_THINK_BLOCK      = re.compile(r'<think>.*?</think>', re.DOTALL | re.IGNORECASE)


def _strip_think(text: str) -> str:
    """Remove DeepSeek R1 <think>...</think> reasoning blocks."""
    if not text:
        return ""
    return _THINK_BLOCK.sub('', text).strip()


def _strip_rhetorical_colons(text: str) -> str:
    """
    Remove colons used as rhetorical labels (e.g. 'Key takeaway: Xyz...').
    Targets the pattern: word-phrase colon space CapitalLetter.
    """
    return _RHETORICAL_COLON.sub(r'\1 — ', text).strip()


def _to_sentence_case(text: str) -> str:
    """
    Apply sentence case: capitalise only the first word of each sentence.
    Preserves all-caps acronyms (ASP, NPD) and mixed-case words (YoY).
    """
    def _process(sentence: str) -> str:
        words = sentence.split(' ')
        out = []
        for i, word in enumerate(words):
            if not word:
                out.append(word)
                continue
            letters = re.sub(r'[^a-zA-Z]', '', word)
            is_acronym = letters.isupper() and len(letters) > 1
            has_internal_upper = any(c.isupper() for c in letters[1:]) if len(letters) > 1 else False
            if i == 0:
                out.append(word[0].upper() + word[1:])
            elif is_acronym or has_internal_upper:
                out.append(word)
            else:
                out.append(word.lower())
        return ' '.join(out)

    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    return ' '.join(_process(p) for p in parts)


def _post_clean(text: str) -> str:
    text = _strip_rhetorical_colons(text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = _to_sentence_case(text)
    return text


def _substitute_categories(text: str, categories: list) -> str:
    """
    Replace {{category_a}}, {{category_b}}, {{category_c}} placeholders with
    actual category names from the current slide.
    Falls back to a generic label if fewer categories than placeholders.
    """
    labels = ['a', 'b', 'c']
    for i, label in enumerate(labels):
        name = categories[i] if i < len(categories) else f"[category {label}]"
        text = text.replace(f"{{{{category_{label}}}}}", name)
    return text


# NOTE: provider-specific HTTP calls used to live here as `_call_openrouter`,
# `_call_groq`, and `_call_moonshot`. They were removed when src/llm/ was
# introduced — every model invocation now goes through `llm_complete(profile=...)`.
# To swap providers (e.g. internal hosting), edit src/llm/profiles.py.


# ---------------------------------------------------------------------------
# Data formatting helpers
# ---------------------------------------------------------------------------
def _fmt_pct(v, decimals: int = 1) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "NA"
    try:
        return f"{float(v):+.{decimals}f}%"
    except Exception:
        return "NA"


def _build_slide_fact_block(category_metrics: list) -> str:
    """
    Build a plain-text structured data block summarising ALL categories on a
    slide for R1 holistic analysis.
    """
    lines = []
    for m in category_metrics:
        cat  = m.get('category', 'Unknown')
        dd   = _fmt_pct(m.get('dollar_diff'))
        du   = _fmt_pct(m.get('units_diff'))
        da   = _fmt_pct(m.get('asp_diff'))
        fd   = _fmt_pct(m.get('forecast_dollars'))
        ad   = _fmt_pct(m.get('actual_dollars'))
        fu   = _fmt_pct(m.get('forecast_units'))
        au   = _fmt_pct(m.get('actual_units'))
        fa   = _fmt_pct(m.get('forecast_asp'))
        aa   = _fmt_pct(m.get('actual_asp'))
        lines.append(
            f"• {cat}\n"
            f"  Forecast YoY: Dollars={fd}, Units={fu}, ASP={fa}\n"
            f"  Actual   YoY: Dollars={ad}, Units={au}, ASP={aa}\n"
            f"  Variance (F-A): Dollars={dd}, Units={du}, ASP={da}"
        )
    return "\n\n".join(lines)


def _build_total_fact_block(df_tot: pd.DataFrame) -> str:
    """Summarise total-slide metrics for the Llama call."""
    try:
        from acc_deck_pkg.analysis import pivot_total_table  # type: ignore
        pv = pivot_total_table(df_tot)
        if pv is None or pv.empty:
            return "(no total metrics available)"
        lines = []
        for metric in ["ASP", "Units", "Dollars"]:
            if metric not in pv.index:
                continue
            row = pv.loc[metric]
            f  = _fmt_pct(row.get("Forecast"))
            a  = _fmt_pct(row.get("Actual"))
            d  = _fmt_pct(row.get("Diff (%)"))
            lines.append(f"- {metric}: Forecast {f} | Actual {a} | Diff {d}")
        return "TOTAL metrics:\n" + "\n".join(lines)
    except Exception as exc:
        return f"(total metric error: {exc})"


# ---------------------------------------------------------------------------
# R1 → Llama A → Llama B pipeline (per slide)
# ---------------------------------------------------------------------------

# R1 system preamble — the loaded style guide is appended at call time
_R1_BRIEF_PREAMBLE = """\
You are an analytical strategist for a global retail and consumer goods intelligence firm. \
Your role is to reason over forecast accuracy data AND the company style guide provided, \
then produce a structured brief that a presentation writer will execute verbatim.

Your output is NOT the final insight — it is a structured decision document. \
The writer will follow your brief exactly, so be precise and opinionated. \
Reason carefully about which framing best serves the data AND the constructive \
framing goals described in the style guide before committing to a choice.

Before selecting a framing, identify which reference example in the style guide most \
closely matches the current data pattern (accuracy level, driver type, contrast dynamic). \
Use that example as your structural and tonal anchor when completing the brief fields.

FRAMING OPTIONS AND SELECTION THRESHOLDS:
- ACCURACY-LED: maximum dollar variance across all categories ≤ 3 percentage points. \
Default to this when results are generally tight — these decks exist to demonstrate \
forecasting strength. When in doubt between ACCURACY-LED and CONTRAST-LED, prefer ACCURACY-LED.
- DRIVER-LED: a single driver (ASP or units) dominates the story and explains the dollar \
outcome; the mechanism is more interesting than the accuracy number.
- CONTRAST-LED: only use when one category is genuinely tight (< 3pp) AND another has a \
material gap (> 5pp). Small differences between categories are NOT a contrast story.
- CONTEXT-LED: all or most categories have significant misses (> 8pp) and market conditions \
explain why. Use this instead of leading with the miss. Never frame a miss as the headline.

Output your brief using EXACTLY these labelled lines (no markdown, no extra text):

FRAMING: [ACCURACY-LED | DRIVER-LED | CONTRAST-LED | CONTEXT-LED]
REASON: [one sentence: why this framing fits this data and the constructive goals]
REFERENCE MATCH: [which style guide example most closely matches this data, and why]
SPOTLIGHT: [1-2 category names to feature, or "all" if the pattern is uniform]
KEY FIGURES: [specific pp values to quote, e.g. cookware +1.1pp, tabletop -10.6pp]
PRIMARY DRIVER: [units / ASP / mix — what drove the result and in which direction]
NARRATIVE ARC: [one sentence: the story itself — write the narrative arc directly, not as an instruction to a writer]
TONE: [specific tone instruction, e.g. "constructive — lead cookware accuracy, contextualise tabletop gap"]
AVOID: [phrases already used in previous insights, or NONE]
"""

# Llama A fallback: analyse + write in one pass when R1 is unavailable
_KIMI_A_DIRECT_SYSTEM = """\
You are a senior analyst and presentation writer for a global retail and consumer goods intelligence firm. \
R1 analysis is unavailable — you must analyse the data and write the insight yourself.

Review the slide data and write ONE polished insight (35–45 words) suitable for a slide subheader. \
Choose the most appropriate framing (ACCURACY-LED, DRIVER-LED, CONTRAST-LED, or CONTEXT-LED) \
based on the data pattern. Use only the ALLOWED CATEGORIES listed — never invent others. \
Spell out "percentage points" in full. No superlatives, no forward-looking speculation. \
Output only the insight text.\
"""

# Llama A: focused executor — no style guide dump, just executes the brief
_KIMI_A_SYSTEM = """\
You are a presentation writer for a global retail and consumer goods intelligence firm. \
You will receive a structured analytical brief and an ALLOWED CATEGORIES list. \
Your sole job is to execute the brief precisely.

Write ONE polished insight (35–45 words) following the brief's FRAMING, NARRATIVE ARC, \
KEY FIGURES, and TONE instructions exactly. Use only the SPOTLIGHT categories. \
CRITICAL: Only use category names from the ALLOWED CATEGORIES list — never invent, \
substitute, or use names from examples you have seen elsewhere. \
Do not reference figures not listed in KEY FIGURES. Do not start with "The". \
Spell out "percentage points" in full — never abbreviate. \
No exclamation marks. No rhetorical colon labels. Output only the insight text.\
"""

# Llama B: light-touch proofreader — minimal edits only, preserve Llama A's voice
_KIMI_B_SYSTEM = """\
You are a light-touch proofreader. Your default is to return the draft unchanged. \
Only intervene if one of these specific issues is present:

1. A banned word appears — replace with the mildest accurate alternative:
   Positive: "perfect", "exceptional", "outstanding", "remarkable", "extraordinary"
   Negative: "dramatically", "severely", "drastically", "collapsed", "tumbled", "catastrophic", "disastrous", "fell well short", "massive miss", "shocking"
2. "percentage points" is abbreviated (pp, ppts) — spell it out in full
3. A phrase from the AVOID list in the brief appears — substitute one word only
4. An obvious grammar error (missing word, broken syntax)
5. A model or tool name appears (Llama, Kimi, GPT, Claude, DeepSeek, R1) — remove it and rephrase the surrounding clause naturally so no model name remains
6. The draft exceeds 45 words — trim by removing the least essential clause or qualifier. \
   Preserve KEY FIGURES and the core framing; drop explanatory asides first.

Do NOT rewrite for style. Do NOT change sentence structure. Do NOT add facts. \
If the draft is clean, return it exactly as received. \
Output only the final sentence.\
"""


# Structured output format instruction appended to R1's user message
_R1_OUTPUT_FORMAT = """\

---
After your analysis, output ONLY the structured brief using the exact labels above. \
No preamble, no explanation, no markdown. Just the 9 labelled lines.\
"""


def _run_r1_brief(
    slide_id: str,
    fact_block: str,
    style_guide: str,
    user_meta_prompt: str,
    prev_insights: list,
    category_names: list,
    groq_key: str,
    timeout: int,
) -> str:
    """
    Analytical brief stage — now uses Groq (gpt-oss-120b).
    System = role preamble + style guide with category placeholders substituted.
    User   = raw data + allowed categories + previous insights + output format.
    """
    rendered_guide = _substitute_categories(style_guide or "", category_names)
    system = _R1_BRIEF_PREAMBLE + "\n\n---\nCIRCANA STYLE GUIDE\n---\n" + rendered_guide

    allowed_block = (
        "ALLOWED CATEGORIES (use only these exact names — never substitute or invent others):\n"
        + "\n".join(f"- {c}" for c in category_names)
    )

    prev_block = ""
    if prev_insights:
        prev_block = (
            "\n\nPREVIOUS SLIDE INSIGHTS (avoid repeating these phrases or framings):\n"
            + "\n".join(f"- {t}" for t in prev_insights[-2:])
        )

    user_msg = (
        f"SLIDE: {slide_id}\n\n"
        f"{allowed_block}\n\n"
        f"SLIDE DATA:\n{fact_block}"
        f"{prev_block}\n\n"
        f"{_R1_OUTPUT_FORMAT}"
    )

    return llm_complete(
        "brief",
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user_msg},
        ],
        api_key=groq_key,
        timeout=max(timeout, 60),
    )


def _run_kimi_direct(
    fact_block: str,
    category_names: list,
    user_meta_prompt: str,
    groq_key: str,
    timeout: int,
) -> str:
    """
    Fallback: Llama analyses + writes directly from raw data when R1 brief is unavailable.
    """
    allowed = (
        "ALLOWED CATEGORIES — use only these exact names:\n"
        + "\n".join(f"- {c}" for c in category_names)
    )
    user_msg = (
        f"{allowed}\n\n"
        f"SLIDE DATA:\n{fact_block}\n\n"
        f"ANALYST CONTEXT:\n{user_meta_prompt or ''}"
    )
    return llm_complete(
        "fast_writer",
        messages=[
            {"role": "system", "content": _KIMI_A_DIRECT_SYSTEM},
            {"role": "user",   "content": user_msg},
        ],
        api_key=groq_key,
        timeout=timeout,
    )


def _run_kimi_write(brief: str, category_names: list, moonshot_key: str, timeout: int) -> str:
    """Kimi A stage: executes the GPT structured brief via Moonshot."""
    allowed = (
        "ALLOWED CATEGORIES — use only these exact names, no others:\n"
        + "\n".join(f"- {c}" for c in category_names)
    )
    return llm_complete(
        "writer",
        messages=[
            {"role": "system", "content": _KIMI_A_SYSTEM},
            {"role": "user",   "content": f"{allowed}\n\nANALYTICAL BRIEF:\n\n{brief}"},
        ],
        api_key=moonshot_key,
        timeout=timeout,
    )


def _run_kimi_cleanup(brief: str, draft: str, category_names: list, moonshot_key: str, timeout: int) -> str:
    """Kimi B stage: light proofreader via Moonshot."""
    allowed = (
        "ALLOWED CATEGORIES — if any other category name appears in the draft, replace it "
        "with the most contextually appropriate name from this list:\n"
        + "\n".join(f"- {c}" for c in category_names)
    )
    brief_block = f"BRIEF CONSTRAINTS:\n{brief}\n\n" if brief else ""
    user_msg = (
        f"{allowed}\n\n"
        f"{brief_block}"
        f"DRAFT:\n{draft}"
    )
    return llm_complete(
        "cleanup",
        messages=[
            {"role": "system", "content": _KIMI_B_SYSTEM},
            {"role": "user",   "content": user_msg},
        ],
        api_key=moonshot_key,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Public API — stable signatures for the pipeline (do not change without
# updating main_meta_modes.py callers)
# ---------------------------------------------------------------------------

def generate_meta_slide_insights_from_data(
    slide_mapping: dict,
    collapsed_df: pd.DataFrame,
    system_prompt: str,
    user_meta_prompt: str,
    api_key: str = "",              # ignored — providers resolve keys themselves
    model: str = "",                # ignored — models are picked by llm/profiles.py
    temperature: float = 0.65,      # ignored — temperatures are baked into profiles
    top_p: float = 0.92,            # ignored
    max_tokens: int = 300,          # ignored
    timeout: int = 60,
    sampled_examples: list = None,  # ignored — examples embedded in style guide
    narrative_config: dict = None,  # ignored — brief stage handles narrative holistically
    **kwargs
) -> pd.DataFrame:
    """
    Generate meta-insights using brief → writer → cleanup → regex, one pass per slide.

    Flow:
      brief    (Groq)     — receives style guide + raw data + previous insights → structured brief
      writer   (Moonshot) — executes the brief → draft insight (40–50 words)
      cleanup  (Moonshot) — verifies brief compliance + cleanup → final sentence
      regex    — post-pass strip of rhetorical colons / whitespace

    Returns DataFrame with columns: slide_id, meta_insight.

    To swap any of the three model calls to internally-hosted endpoints,
    edit src/llm/profiles.py — no changes needed in this function.
    """
    # Per-call API key overrides (pass None → providers fall back to env).
    groq_key     = kwargs.get("groq_api_key")
    moonshot_key = kwargs.get("moonshot_api_key")

    # Build per-slide category metrics
    rows = []
    for slide_id, categories in slide_mapping.items():
        cat_data = collapsed_df[collapsed_df["category"].isin(categories)]
        if cat_data.empty:
            continue

        category_metrics = []
        for _, row in cat_data.iterrows():
            category_metrics.append({
                "category":         row["category"],
                "dollar_diff":      row.get("Diff (%)_Dollars", 0),
                "units_diff":       row.get("Diff (%)_Units",   0),
                "asp_diff":         row.get("Diff (%)_ASP",     0),
                "forecast_dollars": row.get("Forecast_Dollars", 0),
                "forecast_units":   row.get("Forecast_Units",   0),
                "forecast_asp":     row.get("Forecast_ASP",     0),
                "actual_dollars":   row.get("Actual_Dollars",   0),
                "actual_units":     row.get("Actual_Units",     0),
                "actual_asp":       row.get("Actual_ASP",       0),
            })

        category_metrics.sort(key=lambda x: abs(x.get("dollar_diff") or 0))
        rows.append({"slide_id": slide_id, "category_metrics": category_metrics})

    if not rows:
        return pd.DataFrame(columns=["slide_id", "meta_insight"])

    total_slides = len(rows)
    print(f"\n{'─' * 60}")
    print(f"GENERATING META INSIGHTS — brief → writer → cleanup")
    print(f"{total_slides} slides | profiles: brief, writer, cleanup (see llm/profiles.py)")
    print(f"{'─' * 60}")

    meta_insights = []      # accumulates as we go — passed to R1 for variety
    start = time.time()

    for idx, row in enumerate(rows):
        slide_id         = row["slide_id"]
        category_metrics = row["category_metrics"]
        fact_block       = _build_slide_fact_block(category_metrics)

        # Previous insights so far this deck (last 4 max)
        prev_insight_texts = [r["meta_insight"] for r in meta_insights[-4:]]
        category_names = [m["category"] for m in category_metrics]

        cats_str = " · ".join(category_names)
        print(f"\n[{idx + 1}/{total_slides}] Generating insight ({slide_id}): {cats_str}")

        try:
            # Stage 1: GPT (Groq) — analytical + strategic brief
            brief = _run_r1_brief(
                slide_id=slide_id,
                fact_block=fact_block,
                style_guide=system_prompt or "",
                user_meta_prompt=user_meta_prompt or "",
                prev_insights=prev_insight_texts,
                category_names=category_names,
                groq_key=groq_key,
                timeout=timeout,
            )
            r1_ok = len(brief.strip()) > 20
            print(f"  GPT brief ({len(brief.split())} words):\n{brief}")
        except Exception as exc:
            print(f"  GPT brief error ({type(exc).__name__}): {exc}")
            brief, r1_ok = "", False

        try:
            # Stage 2: Kimi A (Moonshot) — execute brief, or direct Groq fallback if brief empty
            print()
            if r1_ok:
                draft = _run_kimi_write(brief, category_names=category_names, moonshot_key=moonshot_key, timeout=timeout)
            else:
                print("  GPT brief empty — falling back to Groq direct")
                draft = _run_kimi_direct(fact_block, category_names, user_meta_prompt or "", groq_key=groq_key, timeout=timeout)
            print(f"  Kimi A draft: \"{draft}\"")

            # Stage 3: Kimi B (Moonshot) — light proofread
            print()
            cleaned = _run_kimi_cleanup(brief if r1_ok else "", draft, category_names=category_names, moonshot_key=moonshot_key, timeout=timeout)
            print(f"  Kimi B clean: \"{cleaned}\"")

            text = _post_clean(cleaned)

        except Exception as exc:
            # Moonshot unavailable — use Groq direct as full fallback
            print(f"  Kimi write error ({type(exc).__name__}): {exc} — falling back to Groq direct")
            try:
                draft = _run_kimi_direct(fact_block, category_names, user_meta_prompt or "", groq_key=groq_key, timeout=timeout)
                text = _post_clean(draft)
                print(f"  Groq fallback draft: \"{text}\"")
            except Exception as groq_exc:
                text = f"(Insight unavailable: {groq_exc})"
                print(f"  Groq fallback also failed: {groq_exc}")

        word_count = len(text.split())
        print()
        print(f"  Final ({word_count} words): \"{text}\"")
        meta_insights.append({"slide_id": slide_id, "meta_insight": text})

        if idx < total_slides - 1:
            time.sleep(2)

    elapsed = time.time() - start
    print(f"\n{'─' * 60}")
    print(f"Complete: {total_slides} insights in {elapsed:.1f}s ({elapsed / max(1, total_slides):.1f}s/slide)")
    print(f"{'─' * 60}")

    return pd.DataFrame(meta_insights)


def generate_total_slide_subheader(
    df_tot,
    *,
    system_prompt: str,
    user_total_prompt: str,
    api_key: str = "",      # ignored
    model: str = "",        # ignored — profile picks the model
    temperature: float = 0.65,
    top_p: float = 0.85,
    max_tokens: int = 120,
    timeout: int = 60,
    **kwargs
) -> str:
    """Generate a 20–25 word topline subheader for the TOTAL slide.

    Uses the `total_subheader` profile — see llm/profiles.py.
    """
    groq_key   = kwargs.get("groq_api_key")  # None → provider reads env
    fact_block = _build_total_fact_block(df_tot)

    system = (
        (system_prompt or "").strip()
        + "\n\n20-25 words maximum, professional, insight-led. "
        "Do NOT invent numbers. Emphasise forecast vs actual and the main driver briefly."
    )
    user_msg = fact_block + "\n\n" + (user_total_prompt or "").strip()

    try:
        text = llm_complete(
            "total_subheader",
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user_msg},
            ],
            max_tokens=max_tokens,
            api_key=groq_key,
            timeout=timeout,
        )
        return _post_clean(text) or "Topline: no subheader produced."
    except Exception as exc:
        return f"(LLM error: {exc})"


def generate_llm_insights_remote(
    df: pd.DataFrame,
    system_prompt: str,
    row_prompt_template: str,
    *,
    col_map: Dict[str, str],
    model: str = "",
    api_key: str = "",
    temperature: float = 0.65,
    top_p: float = 0.90,
    max_tokens: int = 300,
    timeout: int = 60,
    **kwargs
) -> pd.DataFrame:
    """Pass-through stub — per-category LLM calls are not used in the direct path.

    Returns df with an empty 'insight' column added if missing. Kept for
    back-compat with main_meta_modes.py imports; remove once confirmed
    unused.
    """
    out = df.copy()
    if "insight" not in out.columns:
        out["insight"] = ""
    return out


def generate_meta_slide_insights(
    slide_mapping: dict,
    insights_df: pd.DataFrame,
    system_prompt: str,
    user_meta_prompt: str,
    api_key: str = "",
    model: str = "",
    temperature: float = 0.65,
    top_p: float = 0.90,
    max_tokens: int = 300,
    timeout: int = 60,
    **kwargs
) -> pd.DataFrame:
    """Pass-through stub — the traditional (synthesise-from-categories) path
    was removed May 2026 alongside the UI mode toggle. Kept for back-compat
    with main_meta_modes.py imports; returns empty DataFrame with the
    correct schema."""
    return pd.DataFrame(columns=["slide_id", "meta_insight"])
