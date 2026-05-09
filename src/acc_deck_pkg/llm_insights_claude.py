"""
llm_insights.py - REFACTORED FOR CLAUDE API
================

LLM-facing utilities for generating concise, presentation-ready insights.
Now uses Anthropic's Claude API instead of Groq.

Minimal collaborative edits (Jan 2026):
- Removed the "auto-prefix opener injection" in calibrate_tone_for_accuracy_and_synonyms()
  (this was causing repetitive/banned openers and fighting your prompt variety rules).
- Added a safe fallback for CONFIG import so the module doesn't error on import if CONFIG isn't used.
- Avoided any changes that would conflict with function calls from main().
"""

# -----------------------------------------------------------------------------
# IMPORTS -> Anthropic Claude + defaults
# -----------------------------------------------------------------------------
import time
import re
import csv
import random
from typing import Dict, List, Optional, Union
import pandas as pd
# Lazy import: the active pipeline uses llm_provider="free" (Groq + Moonshot)
# and never instantiates a Claude client. Importing this module must therefore
# not require the anthropic SDK to be installed. If someone *does* try to use
# the Claude path without the SDK, the stub class below raises a clear error.
try:
    from anthropic import Anthropic, APIError  # type: ignore
except ImportError:
    class APIError(Exception):  # type: ignore
        """Stub used when the anthropic SDK is not installed."""

    class Anthropic:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError(
                "The 'anthropic' package is not installed. "
                "Install it (`pip install anthropic`) or run with "
                "llm_provider='free' in config.json."
            )
import hashlib

# Retry configuration for transient API errors
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # seconds
RETRYABLE_STATUS_CODES = {500, 502, 503, 529}  # Server errors + overloaded


def _call_with_retry(client, model, max_tokens, temperature, top_p, system, messages):
    """
    Call Claude API with exponential backoff retry for transient errors.

    Retries on 500, 502, 503, 529 errors up to MAX_RETRIES times.
    """
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                system=system,
                messages=messages
            )
            return response
        except APIError as e:
            last_error = e
            # Check if error is retryable (5xx errors)
            status_code = getattr(e, 'status_code', None)
            if status_code in RETRYABLE_STATUS_CODES:
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)  # Exponential backoff
                    print(f"  ⚠ API error {status_code}, retrying in {delay:.1f}s (attempt {attempt + 1}/{MAX_RETRIES})")
                    time.sleep(delay)
                    continue
            # Non-retryable error or max retries exceeded
            raise

    # Should not reach here, but raise last error if we do
    raise last_error
from acc_deck_pkg.analysis import pivot_total_table
from acc_deck_pkg.yoy_transformers import excel_round

# Optional CONFIG import (kept safe to avoid NameError if not available)
try:
    from acc_deck_pkg.config_claude import CONFIG  # type: ignore
except Exception:
    CONFIG = {}  # Safe fallback; only used by sampling helpers if called.

# claude-sonnet-4-20250514
# # Claude API configuration
CLAUDE_MODEL = "claude-sonnet-4-20250514"  # Latest Claude Sonnet 4.5


#=================================================
# DATA Cleaning/ formatting helpers
#=====================================
def _fmt_pct(v, decimals=1):
   if v is None or (isinstance(v, float) and pd.isna(v)):
       return "NA"
   try:
       return f"{float(v):+.{decimals}f}%"
   except Exception:
       return "NA"


def _fmt_driver(diff_dollars, diff_units, diff_asp):
   band = compute_accuracy_band(diff_dollars)
   driver = compute_primary_driver(diff_asp, diff_units)
   return band, driver


def _build_category_fact_block(vals: dict) -> str:
   """
   Produces a clear, structured data block for per-category insight generation.
   Uses plain language the model can understand without ambiguity.
   """
   cat = vals.get("cat") or vals.get("category") or "Unknown"
   diff_d = vals.get("diff_dollars")
   diff_u = vals.get("diff_units")
   diff_a = vals.get("diff_asp")
   band, driver = _fmt_driver(diff_d, diff_u, diff_a)

   return (
       f"Category: {cat}\n"
       f"Forecast accuracy: {band}\n"
       f"Dollar variance (forecast vs actual): {_fmt_pct(diff_d)} percentage points\n"
       f"Units variance: {_fmt_pct(diff_u)} percentage points\n"
       f"ASP variance: {_fmt_pct(diff_a)} percentage points\n"
       f"Primary driver of dollar variance: {driver}\n"
   )


_CATEGORY_PATTERNS = {
   "A": "Accuracy → driver → implication",
   "B": "Driver-led: what surprised → impact → implication",
   "C": "Exception-led: where forecast broke → likely reason → takeaway",
   "D": "Risk/action: what to watch next quarter → why → action",
}


def _pattern_for_category(cat: str, salt: str = "v1") -> str:
   """
   Deterministic pattern choice so decks are reproducible.
   """
   key = (salt + "|" + (cat or "")).encode("utf-8")
   h = hashlib.md5(key).hexdigest()
   idx = int(h[:2], 16) % 4
   return ["A", "B", "C", "D"][idx]


# =============================================================================
# Per-category example templates — modular style anchors
# =============================================================================
# One example is sampled per row and {{category}} is substituted with the real
# category name. Grouped by accuracy_band so selection is structurally relevant.
# Derived from client/director-approved insights; industry-agnostic by design.

_CATEGORY_EXAMPLE_TEMPLATES: Dict[str, List[str]] = {
    "on_plan": [
        "{{category}} achieved tight dollar forecast accuracy, with ASP strength offsetting softer unit demand.",
        "{{category}} closely aligned with forecasts, tracking within a marginal percentage point of dollar projections.",
        "{{category}} maintained tight accuracy across all metrics, with ASP gains compensating for modest volume softness.",
        "{{category}} demonstrated high accuracy, with dollar results landing within a single percentage point of forecast.",
        "{{category}} delivered on-point performance, with pricing strength keeping dollar results closely aligned to plan.",
    ],
    "modest_variance": [
        "{{category}} tracked within a modest margin of dollar projections, with pricing strength compensating for volume softness.",
        "{{category}} delivered solid performance, tracking within a few percentage points of dollar forecast despite unit pressure.",
        "{{category}} showed broadly directional accuracy, with offsetting ASP and unit dynamics keeping results close to plan.",
        "{{category}} closely matched forecast in dollar terms, as elevated ASP gains offset declining volume performance.",
        "{{category}} tracked below dollar projections by a manageable margin, driven by softer-than-expected unit demand.",
    ],
    "meaningful_variance": [
        "{{category}} fell below dollar forecasts as unit demand came in softer than anticipated despite pricing resilience.",
        "{{category}} showed mixed performance, with pricing gains cushioning the impact of weaker demand volumes.",
        "{{category}} underperformed dollar expectations, with softer-than-anticipated demand driving variance versus forecast.",
        "{{category}} exceeded dollar expectations, driven by unexpectedly strong unit growth that outpaced modest pricing pressure.",
        "{{category}} displayed a clear price-over-volume dynamic, with ASP strength driving dollar performance despite unit declines.",
    ],
    "material_variance": [
        "{{category}} experienced a pronounced forecast miss, with combined unit and pricing weakness pushing dollar results below plan.",
        "{{category}} showed the widest forecast deviation, as demand declined more steeply than anticipated across volume and value.",
        "{{category}} significantly outperformed dollar forecasts, driven by stronger unit demand that far exceeded projections.",
        "{{category}} diverged from plan as unit demand fell well short of forecast, only partially offset by pricing resilience.",
        "{{category}} faced the largest variance, with units and ASP both falling short of projections in the period.",
    ],
}


def _example_seed_for_category(cat: str) -> int:
    """Derive a deterministic seed from the category name for reproducible example selection."""
    h = hashlib.md5(cat.encode("utf-8")).hexdigest()
    return int(h[4:8], 16)


def sample_category_example(
    category: str,
    accuracy_band: str = None,
    seed: int = None,
) -> str:
    """
    Sample one parameterized example insight and substitute {{category}}.

    Samples from the matching accuracy_band pool when available, so the example
    is structurally consistent with the current row's data. Falls back to the
    full pool if the band is unknown.

    Pass seed=_example_seed_for_category(cat) for reproducible decks.
    """
    pool = _CATEGORY_EXAMPLE_TEMPLATES.get(accuracy_band or "", [])
    if not pool:
        pool = [t for band in _CATEGORY_EXAMPLE_TEMPLATES.values() for t in band]

    rng = random.Random(seed) if seed is not None else random
    template = rng.choice(pool)
    return template.replace("{{category}}", (category or "This category"))


# -----------------------------------------------------------------------------
# Banned words safety net - catches anything that slips through prompts
# -----------------------------------------------------------------------------
_BANNED_WORD_REPLACEMENTS = [
    # Perfect + precision/accuracy combinations -> measured alternatives
    (re.compile(r'\bperfect(?:ly)?\s+(?:forecast\s+)?(?:precision|accuracy|alignment)', re.I), 'tight accuracy'),
    (re.compile(r'\bpinpoint\s+(?:accuracy|precision|alignment)', re.I), 'tight accuracy'),
    (re.compile(r'\bexceptional(?:ly)?\s+(?:accurate|precision|accuracy)', re.I), 'high accuracy'),
    (re.compile(r'\boutstanding\s+(?:accuracy|precision|performance)', re.I), 'solid accuracy'),
    (re.compile(r'\bremarkable\s+(?:accuracy|precision|performance)', re.I), 'strong accuracy'),
    (re.compile(r'\bdemonstrated\s+perfect', re.I), 'achieved tight'),
    (re.compile(r'\bdelivered\s+perfect', re.I), 'delivered tight'),
    (re.compile(r'\bachieved\s+perfect', re.I), 'achieved tight'),
    (re.compile(r'\bprecisely\s+match(?:ed|ing)?', re.I), 'closely tracked'),
    (re.compile(r'\bexactly\s+match(?:ed|ing)?', re.I), 'closely matched'),
    (re.compile(r'\bhit(?:ting)?\s+targets?\s+exactly', re.I), 'tracked closely to targets'),
    (re.compile(r'\bmatched\s+(?:projections?|forecasts?)\s+exactly', re.I), 'tracked closely to forecast'),
    # Standalone banned words
    (re.compile(r'\bperfect\s+(?=\d)', re.I), 'tight '),  # "perfect 0.0" -> "tight 0.0"
    # NOTE: "precision" is allowed for very tight accuracy (<2pp), so not replaced here
]


def _sanitize_banned_words(text: str) -> str:
    """
    Safety net: Replace any banned celebratory words that slip through prompts.
    Applies regex replacements to convert superlatives to measured language.
    """
    if not text:
        return text

    t = text
    for pattern, replacement in _BANNED_WORD_REPLACEMENTS:
        t = pattern.sub(replacement, t)

    # Clean up any double spaces from replacements
    t = re.sub(r'\s+', ' ', t).strip()
    return t


# -----------------------------------------------------------------------------
# Basic, shared cleaner for "one-sentence" results (very lightweight)
# -----------------------------------------------------------------------------
_SENT_SPLIT = re.compile(r'(?<=[.!?])\s+')


def _clean_to_one_sentence(text: str) -> str:
   """
   Light cleaner: strip trivial leading labels and keep only the first sentence.
   Used for meta-slide insights where brevity is critical.
   """
   t = (text or "").strip()

   # Drop simple leading labels like "Insight:", "Answer:" etc.
   SIMPLE_PREFIXES = (
       "Explanation:",
       "Insight:",
       "Reason:",
       "Analysis:",
       "Answer:",
       "Observation:",
       "Note:",
       "Summary:",
   )
   for bad in SIMPLE_PREFIXES:
       if t.startswith(bad):
           t = t[len(bad):].lstrip(" -:")
           break

   # Also strip any leading hyphen/bullet and common slide wrappers
   t = re.sub(r"""^\s*(?:[-*•]\s+|\(?\d+\)?[.)]\s+)""", "", t)

   # Keep just the first sentence
   return _SENT_SPLIT.split(t, 1)[0].strip()


def _clean_category_insight(text: str) -> str:
   """
   Clean category insight: strip labels and bullets but keep ALL content.
   Used for per-category insights that feed into meta-slide synthesis.
   Preserves detail so meta-insights have more information to work with.
   """
   t = (text or "").strip()

   # Drop simple leading labels like "Insight:", "Answer:" etc.
   SIMPLE_PREFIXES = (
       "Explanation:",
       "Insight:",
       "Reason:",
       "Analysis:",
       "Answer:",
       "Observation:",
       "Note:",
       "Summary:",
   )
   for bad in SIMPLE_PREFIXES:
       if t.startswith(bad):
           t = t[len(bad):].lstrip(" -:")
           break

   # Strip any leading hyphen/bullet and common slide wrappers
   t = re.sub(r"""^\s*(?:[-*•]\s+|\(?\d+\)?[.)]\s+)""", "", t)

   # Clean up any trailing incomplete sentences or artifacts
   t = t.strip()

   # Remove any double spaces
   t = re.sub(r'\s+', ' ', t)

   return t


# =============================================================================
# Accuracy bands, drivers, and tone/synonym helpers
# =============================================================================
def compute_accuracy_band(dollar_diff: float) -> str:
   """
   Map Dollar diff to a qualitative accuracy band based on absolute percentage point gap.
   """
   if dollar_diff is None or pd.isna(dollar_diff):
       return "unknown"

   d = abs(float(dollar_diff))
   if d <= 3.5:
       return "on_plan"
   elif d <= 7.0:
       return "modest_variance"
   elif d <= 10.0:
       return "meaningful_variance"
   else:
       return "material_variance"


def compute_primary_driver(diff_asp: float, diff_units: float) -> str:
   """
   Decide whether Units or ASP is the main driver of Dollar variance.
   """
   asp = None if diff_asp is None or pd.isna(diff_asp) else float(diff_asp)
   units = None if diff_units is None or pd.isna(diff_units) else float(diff_units)

   if asp is None and units is None:
       return "balanced"

   asp_abs = abs(asp) if asp is not None else 0.0
   units_abs = abs(units) if units is not None else 0.0

   max_abs = max(asp_abs, units_abs)
   if max_abs < 1.0:
       return "balanced"

   return "units" if units_abs >= asp_abs else "asp"


# Strong negative phrasing we want to soften, especially for small gaps
_TONE_STRONG_NEG = re.compile(
   r"\b(significant(ly)?|sharp(ly)?|substantial(ly)?|severe(ly)?|suffered)\b",
   flags=re.IGNORECASE,
)

# Phrases that signal "accuracy" so we don't keep re-injecting them
_ACCURACY_KEYWORDS = (
   "on plan",
   "closely aligned",
   "highly accurate",
   "accurate",
   "in line with forecast",
   "tracked forecasts closely",
   "broadly on plan",
)

# A small pool of interchangeable "accuracy" phrases
# (kept for compatibility, but we no longer auto-inject these)
_ACCURACY_PHRASES = [
   "Forecasts were closely aligned with actuals",
   "Forecast performance was highly accurate",
   "Results were broadly on plan versus forecast",
   "Performance tracked forecasts closely",
]

# =============================================================================
# VOCABULARY POOLS - for narrative directive variety
# =============================================================================
VOCAB_POOLS = {
    # Accuracy descriptors (tiered by tightness)
    "precision": ["precision", "notable accuracy", "close alignment", "on-point performance", "tight alignment"],
    "tight": ["tight accuracy", "closely aligned", "tracked tightly", "landed within", "remained aligned", "strong accuracy"],
    "solid": ["solid accuracy", "reasonable alignment", "directionally accurate", "broadly on plan", "tracked closely"],

    # Variance descriptors (tiered by magnitude)
    "moderate_miss": ["fell below forecast", "tracked below projections", "came in softer than expected", "landed below plan"],
    "material_miss": ["underperformed expectations", "missed forecasts", "diverged from projections", "fell short of forecast"],
    "significant_miss": ["faced significant variance", "experienced material shortfall", "fell well short", "missed substantially"],

    # Driver dynamics
    "offsetting": ["offset", "cushioned", "compensated for", "mitigated", "helped absorb", "balanced out"],
    "reinforcing": ["compounded", "amplified", "reinforced", "added to", "contributed to", "exacerbated"],

    # Lead metric openers
    "units_lead": ["Unit dynamics", "Demand patterns", "Volume trends", "Unit performance", "Demand movements"],
    "asp_lead": ["Pricing movements", "ASP dynamics", "Value trends", "Pricing patterns", "ASP performance"],
    "dollars_lead": ["Dollar results", "Revenue performance", "Overall results", "Top-line outcomes", "Dollar performance"],

    # Contrast connectors
    "contrast": ["while", "whereas", "in contrast", "conversely", "however", "meanwhile", "on the other hand"],

    # Qualitative range descriptors (for >2 categories)
    "range_tight": ["across the group", "broadly", "generally", "collectively", "as a whole", "across categories"],
    "range_mixed": ["with varying results", "to differing degrees", "with mixed outcomes", "across the portfolio"],

    # Cause/explanation connectors
    "cause": ["driven by", "largely attributable to", "primarily due to", "reflecting", "supported by", "amid"],

    # Outcome descriptors
    "positive_outcome": ["outperformed", "exceeded expectations", "delivered upside", "beat forecast", "surpassed projections"],
    "negative_outcome": ["underperformed", "fell short", "missed expectations", "came in below", "trailed forecast"],
}

def _get_vocab_variant(pool_name: str, exclude: list = None) -> str:
    """Get a random variant from a vocabulary pool, optionally excluding recent uses."""
    if pool_name not in VOCAB_POOLS:
        return pool_name
    pool = VOCAB_POOLS[pool_name]
    if exclude:
        available = [v for v in pool if v.lower() not in [e.lower() for e in exclude]]
        if available:
            return random.choice(available)
    return random.choice(pool)

# Phrase families where we can vary wording a bit
_PHRASE_VARIANTS = [
   (
       re.compile(r"\bmodest variance\b", re.IGNORECASE),
       ["manageable variance", "small variance", "limited variance"],
   ),
   (
       re.compile(r"\bclosely aligned\b", re.IGNORECASE),
       ["very close to forecast", "tightly in line with forecast"],
   ),
   (
       re.compile(r"\bon plan\b", re.IGNORECASE),
       ["in line with forecast", "broadly on plan"],
   ),
   (
       re.compile(r"\bmaterial miss\b", re.IGNORECASE),
       ["more pronounced miss", "clear miss versus plan"],
   ),
   (
       re.compile(r"\bmaterial beat\b", re.IGNORECASE),
       ["clear beat versus plan", "strong beat versus forecast"],
   ),
   # Headwinds variety - avoid overuse
   (
       re.compile(r"\bdemand headwinds?\b", re.IGNORECASE),
       ["softer demand", "demand pressure", "volume weakness", "weaker demand"],
   ),
   (
       re.compile(r"\bpricing headwinds?\b", re.IGNORECASE),
       ["pricing pressure", "softer pricing", "price softness", "ASP drag"],
   ),
   (
       re.compile(r"\bfaced headwinds?\b", re.IGNORECASE),
       ["experienced pressure", "saw softness", "encountered challenges"],
   ),
   (
       re.compile(r"\bheadwinds?\b", re.IGNORECASE),
       ["pressures", "challenges", "softness", "weakness"],
   ),
   # ASP offset variety
   (
       re.compile(r"\bASP gains? offset\b", re.IGNORECASE),
       ["pricing strength cushioned", "ASP gains compensated for", "stronger pricing offset"],
   ),
   (
       re.compile(r"\boffset(?:ting)? unit declines?\b", re.IGNORECASE),
       ["cushioning softer demand", "compensating for volume weakness", "mitigating unit softness"],
   ),
   # Transitional variety - add human editorial flow
   (
       re.compile(r"\bin contrast\b", re.IGNORECASE),
       ["conversely", "meanwhile", "on the other hand", "however"],
   ),
   (
       re.compile(r"\bdriven by\b", re.IGNORECASE),
       ["largely attributable to", "primarily due to", "reflecting", "supported by"],
   ),
   (
       re.compile(r"\bthe strongest\b", re.IGNORECASE),
       ["the standout performer", "notably the strongest", "most notably"],
   ),
   (
       re.compile(r"\bperformed well\b", re.IGNORECASE),
       ["stood out", "delivered notably", "proved the standout"],
   ),
   # Variance phrasing variety
   (
       re.compile(r"\btracked within\b", re.IGNORECASE),
       ["landed within", "came in within", "remained within", "stayed within"],
   ),
   (
       re.compile(r"\bwithin (\d)", re.IGNORECASE),
       ["under \\1", "just \\1", "at \\1"],
   ),
   # Softness/weakness variety
   (
       re.compile(r"\bunit softness\b", re.IGNORECASE),
       ["volume weakness", "demand pressure", "softer unit performance", "unit drag"],
   ),
   (
       re.compile(r"\bvolume softness\b", re.IGNORECASE),
       ["demand weakness", "unit pressure", "softer demand", "volume drag"],
   ),
   (
       re.compile(r"\bsofter demand\b", re.IGNORECASE),
       ["weaker demand", "demand pressure", "volume weakness", "lighter demand"],
   ),
   # Accuracy language variety
   (
       re.compile(r"\bdelivered tight accuracy\b", re.IGNORECASE),
       ["achieved tight accuracy", "maintained tight accuracy", "showed tight accuracy", "demonstrated strong accuracy"],
   ),
   (
       re.compile(r"\bachieved alignment\b", re.IGNORECASE),
       ["delivered alignment", "maintained alignment", "showed alignment", "demonstrated alignment"],
   ),
   (
       re.compile(r"\bforecast precision\b", re.IGNORECASE),
       ["forecasting accuracy", "predictive accuracy", "projection accuracy", "forecast accuracy"],
   ),
   # Outcome variety
   (
       re.compile(r"\boutperformed expectations\b", re.IGNORECASE),
       ["exceeded expectations", "beat forecast", "surpassed projections", "came in above plan"],
   ),
   (
       re.compile(r"\bunderperformed expectations\b", re.IGNORECASE),
       ["fell below expectations", "missed forecast", "trailed projections", "came in below plan"],
   ),
   # Pricing/ASP variety
   (
       re.compile(r"\bpricing strength\b", re.IGNORECASE),
       ["ASP gains", "stronger pricing", "price uplift", "pricing tailwinds", "ASP strength"],
   ),
   (
       re.compile(r"\bpricing pressure\b", re.IGNORECASE),
       ["ASP weakness", "softer pricing", "price erosion", "pricing headwinds", "ASP softness"],
   ),
   # Unit/demand variety
   (
       re.compile(r"\bunit growth\b", re.IGNORECASE),
       ["volume growth", "demand growth", "unit gains", "volume expansion", "demand uplift"],
   ),
   (
       re.compile(r"\bunit decline[s]?\b", re.IGNORECASE),
       ["volume declines", "demand softness", "unit weakness", "volume contraction", "demand pressure"],
   ),
   # Market condition variety
   (
       re.compile(r"\bchallenging market conditions\b", re.IGNORECASE),
       ["difficult market conditions", "market headwinds", "challenging conditions", "market pressures"],
   ),
   (
       re.compile(r"\bmarket conditions\b", re.IGNORECASE),
       ["market dynamics", "market environment", "broader market trends", "industry conditions"],
   ),
   # Structural variety
   (
       re.compile(r"\bas a result\b", re.IGNORECASE),
       ["consequently", "accordingly", "therefore", "thus"],
   ),
   (
       re.compile(r"\bdespite\b", re.IGNORECASE),
       ["notwithstanding", "even with", "in spite of", "regardless of"],
   ),
   (
       re.compile(r"\bdue to\b", re.IGNORECASE),
       ["owing to", "as a result of", "attributable to", "because of"],
   ),
]


def _has_accuracy_language(text: str) -> bool:
   lower = text.lower()
   return any(k in lower for k in _ACCURACY_KEYWORDS)


def _vary_common_phrases(text: str, variation_probability: float = 0.75) -> str:
   """
   Randomly vary some common phrases so every insight doesn't sound identical.
   Changes are small and style-only.

   Args:
       text: The insight text to vary
       variation_probability: Probability of swapping each phrase (0.0-1.0).
                             Higher = more variation. Default 0.75.
   """
   t = text
   for pattern, variants in _PHRASE_VARIANTS:
       if pattern.search(t):
           if random.random() < variation_probability:
               replacement = random.choice(variants)
               t = pattern.sub(replacement, t)
   return t


def calibrate_tone_for_accuracy_and_synonyms(
    text: str,
    dollar_diff: float,
    variation_probability: float = 0.75
) -> str:
   """
   Soften extreme language when forecasts were accurate or variance was modest,
   and add light variation — WITHOUT injecting templated openers.

   (Removed the prior auto-prefix logic that prepended phrases like
   "Forecasts were..." / "Performance tracked..." which was counterproductive.)

   Args:
       text: The insight text to process
       dollar_diff: The dollar variance (for tone calibration)
       variation_probability: Probability of phrase variation (0.0-1.0, default 0.75)
   """
   if not text:
       return text
   try:
       d = abs(float(dollar_diff)) if dollar_diff is not None else None
   except (TypeError, ValueError):
       d = None
   t = text

   # Soften strong negatives when variance is small/modest
   if d is not None:
       if d <= 3.5:
           # Very accurate: avoid dramatic wording, emphasize smallness
           t = _TONE_STRONG_NEG.sub("slight", t)
       elif d <= 7.0:
           # Modest variance: still avoid disaster language
           t = _TONE_STRONG_NEG.sub("notable", t)

   # Apply phrase variation with configurable probability
   t = _vary_common_phrases(t, variation_probability=variation_probability)

   return t


def soften_meta_and_vary(text: str, variation_probability: float = 0.75) -> str:
   """
   Meta/total insights don't have direct numeric context here, but we can
   still soften harsh language and vary some phrases to avoid repetition.

   This is critical for maintaining constructive tone in executive presentations.

   Args:
       text: The insight text to process
       variation_probability: Probability of phrase variation (0.0-1.0, default 0.75)
   """
   if not text:
       return text

   t = text

   # Priority 1: Soften "fell short" variants (very common issue)
   t = re.sub(r"\bfell\s+significantly\s+short\b", "came in below forecast", t, flags=re.IGNORECASE)
   t = re.sub(r"\bfell\s+short\s+of\s+expectations?\b", "tracked below expectations", t, flags=re.IGNORECASE)
   t = re.sub(r"\bfell\s+short\b", "came in below forecast", t, flags=re.IGNORECASE)
   t = re.sub(r"\bsignificantly\s+short\b", "below forecast", t, flags=re.IGNORECASE)

   # Priority 2: Soften "miss" language
   t = re.sub(r"\bmissed\s+significantly\b", "tracked below forecast", t, flags=re.IGNORECASE)
   t = re.sub(r"\bsignificant\s+miss\b", "variance from forecast", t, flags=re.IGNORECASE)
   t = re.sub(r"\bmaterial\s+miss\b", "notable variance", t, flags=re.IGNORECASE)

   # Priority 3: Soften dramatic/alarmist language
   t = re.sub(r"\bsuffered\b", "experienced", t, flags=re.IGNORECASE)
   t = re.sub(r"\bplunged\b", "declined", t, flags=re.IGNORECASE)
   t = re.sub(r"\bcollapsed\b", "contracted", t, flags=re.IGNORECASE)
   t = re.sub(r"\bsharp\s+decline\b", "softer-than-expected trend", t, flags=re.IGNORECASE)
   t = re.sub(r"\bsharp\s+drop\b", "decline", t, flags=re.IGNORECASE)
   t = re.sub(r"\bsharp\s+unit\s+decline[s]?\b", "softer unit demand", t, flags=re.IGNORECASE)
   t = re.sub(r"\bsharply\b", "notably", t, flags=re.IGNORECASE)
   t = re.sub(r"\bdramatically\b", "", t, flags=re.IGNORECASE)
   t = re.sub(r"\bseverely\b", "", t, flags=re.IGNORECASE)

   # Priority 4: Tone down intensity modifiers (only when modifying negative outcomes)
   t = re.sub(r"\bsubstantially\s+(below|under|worse|lower)\b", r"modestly \1", t, flags=re.IGNORECASE)
   t = re.sub(r"\bsignificantly\s+(below|under|worse|lower|weaker)\b", r"moderately \1", t, flags=re.IGNORECASE)

   # Clean up any double spaces from removals
   t = re.sub(r"\s{2,}", " ", t).strip()

   # Vary stock phrases slightly with configurable probability
   t = _vary_common_phrases(t, variation_probability=variation_probability)

   return t


# =============================================================================
# Per-category insight generation - CLAUDE API
# =============================================================================
def generate_llm_insights_remote(
  df: pd.DataFrame,
  system_prompt: str,
  row_prompt_template: str,
  *,
  col_map: Dict[str, str],
  model: str = CLAUDE_MODEL,
  api_key: str = "my_key",
  temperature: float = 0.71,
  top_p: float = 0.87,
  max_tokens: int = 300,
  timeout: int = 60,
  pattern_salt: str = "v1",   # NEW (optional) – reproducible rotation control
  **kwargs  # Catch unused params like base_url, stop
) -> pd.DataFrame:
  """
  For each row in `df`, format a user prompt from `row_prompt_template` and
  request ONE concise insight sentence using Claude API.

  Returns
  -------
  DataFrame
      A copy of `df` with a new `insight` column.
  """
  client = Anthropic(api_key=api_key, timeout=timeout)

  # Validate required columns exist before we iterate.
  for _, c in col_map.items():
      if c not in df.columns:
          raise ValueError(f"Required column '{c}' not found.")

  insights, start = [], time.time()

  # Row-wise generation
  for _, row in df.iterrows():

      vals = {alias: row[col] for alias, col in col_map.items()}

      # Ensure canonical keys exist (support both "cat" and "category")
      if "cat" not in vals:
          # If df has "category" column, prefer it; else fallback to row.get
          if "category" in df.columns:
              vals["cat"] = row["category"]
          else:
              vals["cat"] = vals.get("category", "Unknown")

      # Optional: simplify category name for nicer wording
      if isinstance(vals.get("cat"), str):
          vals["cat"] = vals["cat"].replace("Total ", "").strip()

      diff_dollars = vals.get("diff_dollars")
      diff_asp = vals.get("diff_asp")
      diff_units = vals.get("diff_units")

      vals["accuracy_band"] = compute_accuracy_band(diff_dollars)
      vals["primary_driver"] = compute_primary_driver(diff_asp, diff_units)

      # === Pattern shuffler (kept) ===========================================
      cat_name = vals.get("cat") or "Unknown"
      pattern_code = _pattern_for_category(cat_name, salt=pattern_salt)
      vals["pattern_code"] = pattern_code
      vals["pattern_desc"] = _CATEGORY_PATTERNS.get(pattern_code, _CATEGORY_PATTERNS["A"])

      # (Optional) legacy nudge retained for compatibility; harmless unless used by template
      vals["avoid_phrases"] = (
          "Avoid opening with: 'Forecasts were closely aligned' or 'Performance tracked'."
      )

      # === Band-aware example injection (1 per row) ===========================
      # Deterministic seed keeps decks reproducible across runs.
      vals["example_insight"] = sample_category_example(
          category=cat_name,
          accuracy_band=vals["accuracy_band"],
          seed=_example_seed_for_category(cat_name),
      )
      # ======================================================================

      fact_block = _build_category_fact_block(vals)
      vals["fact_block"] = fact_block  # in case template uses it directly

      prompt = row_prompt_template.format(**vals)

      try:
          response = _call_with_retry(
              client=client,
              model=model,
              max_tokens=max_tokens,
              temperature=temperature,
              top_p=top_p,
              system=system_prompt,
              messages=[{"role": "user", "content": prompt}]
          )
          text = response.content[0].text.strip()
      except APIError as e:
          text = f"(LLM error: {e})"
      except Exception as e:
          text = f"(Unexpected error: {e})"

      # Clean category insight - keep full content for meta-slide synthesis
      cleaned_insight = _clean_category_insight(text) or "No insight generated."
      cleaned_insight = calibrate_tone_for_accuracy_and_synonyms(cleaned_insight, diff_dollars)
      insights.append(cleaned_insight)

  # Timing/logging
  total = time.time() - start
  print(
      f"✓ Remote generation done in {total:.2f}s "
      f"({total / max(1, len(df)):.2f}s/row) using {model}"
  )

  out = df.copy()
  out["insight"] = insights
  return out


# ===========================================================================
# Meta & total cleaners (stricter; used by meta & total)
# ===========================================================================
_WORD_LIMIT = 45
# Common fluff openers / meta wrappers to strip (case-insensitive)
_FLUFF_PREFIX_PATTERNS = [
   r"^slide\s*\d*\s*[:-]?\s*",
   r"^here'?s\s+a\s+concise.*?:\s*",
   r"^here'?s\s+a\s+high-?level\s+summary:\s*",
   r"^here'?s\s+a\s+possible.*?:\s*",
   r"^here\s+is\s+a\s+possible.*?:\s*",
   r"^here\s+is\s+an?\s+insight.*?:\s*",
   r"^summary:\s*",
   r"^insight:\s*",
   r"^observation:\s*",
   r"^note:\s*",
   r"^in\s+summary[:,]?\s*",
   r"^overall[:,]?\s*",
   r"^in\s+short[:,]?\s*",
   r"^tl;dr[:,]?\s*",
]

# Hedging phrases to remove (kept minimal; we avoid changing semantics)
_HEDGING_PATTERNS = [
   r"\b(?:might|may|could|appears|seems|suggests|possibly|likely)\b[, ]*",
   r"\b(?:we\s+see|we\s+observe|it\s+looks\s+like)\b[, ]*",
]

HEDGE_RE = re.compile("|".join(_HEDGING_PATTERNS), re.IGNORECASE)


def _strip_wrappers(text: str) -> str:
   """Remove full-string wrappers (quotes, backticks, full-width quotes, parens)."""
   t = text.strip()

   # Only strip quotes if they wrap the *entire* string
   if (t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")):
       t = t[1:-1].strip()

   # Full-width / backticks
   for lq, rq in (("\"", "\""), ("'", "'"), ("`", "`")):
       if t.startswith(lq) and t.endswith(rq):
           t = t[len(lq):-len(rq)].strip()

   # Strip whole-string parentheses (not inline numbers like -2.5%)
   if t.startswith("(") and t.endswith(")"):
       t = t[1:-1].strip()

   # Normalize whitespace
   return " ".join(t.split())


def _strip_fluff_prefixes(text: str) -> str:
   """Drop known boilerplate openers."""
   t = text.lstrip()
   changed = True
   while changed:
       changed = False
       for pat in _FLUFF_PREFIX_PATTERNS:
           m = re.match(pat, t, flags=re.IGNORECASE | re.DOTALL)
           if m:
               t = t[m.end():].lstrip()
               changed = True
   return t


def _strip_bullets_and_labels(text: str) -> str:
   """Remove a single leading bullet/number label if present."""
   return re.sub(r"""^\s*(?:[-*•]\s+|\(?\d+\)?[.)]\s+)""", "", text)


def _strip_hedging(text: str) -> str:
   """Remove soft hedging/filler phrases and normalize spacing."""
   t = HEDGE_RE.sub("", text)
   return re.sub(r"\s{2,}", " ", t).strip()


def _truncate_word_limit(text: str, limit: int = _WORD_LIMIT) -> str:
   """Hard cap words to keep subheaders short in slides."""
   words = text.split()
   if len(words) <= limit:
       return text
   return " ".join(words[:limit]).rstrip(",;:")


SENT_END = re.compile(
   r"""
 (?<!\b[A-Z])           # not an initial like 'U.S.'
 (?<!\bvs)
 (?<!\betc)
 (?<!\be\.g)
 (?<!\bi\.e)
 (?<!\d)                # not immediately after a digit (e.g., '2.')
 [.!?]
 (?:['")\]]+)?          # optional closing quotes/brackets
 \s+
""",
   re.IGNORECASE | re.VERBOSE,
)


def _to_one_sentence(text: str) -> str:
   """Keep the first sentence conservatively; ensure it ends with punctuation."""
   parts = SENT_END.split(text, maxsplit=2)
   first = parts[0].strip()
   if first and first[-1] not in ".!?":
       first += "."
   return first


def clean_meta_insight(raw_text: str) -> str:
   """
   Normalize a model-generated meta/total insight:
   - Remove wrappers / fluff / bullets
   - Enforce single, ≤60-word sentence
   - Trim hedging and normalize spacing
   - Sanitize banned celebratory words
   """
   text = (raw_text or "").strip()
   if not text:
       return "No meta-insight generated."
   text = _strip_fluff_prefixes(text)
   text = _strip_wrappers(text)
   text = _strip_bullets_and_labels(text)
   text = _to_one_sentence(text)
   text = _strip_hedging(text)
   text = _strip_wrappers(text)
   text = _truncate_word_limit(text)
   text = _sanitize_banned_words(text)  # Safety net for banned words
   return text or "No meta-insight generated."


# =============================================================================
# Slide-level meta insight generation - CLAUDE API
# =============================================================================
def generate_meta_slide_insights(
   slide_mapping: dict,
   insights_df: pd.DataFrame,
   system_prompt: str,
   user_meta_prompt: str,
   api_key: str,
   model: str = CLAUDE_MODEL,
   temperature: float = 0.85,
   top_p: float = 0.9,
   max_tokens: int = 300,
   timeout: int = 60,
   **kwargs  # Catch unused params like base_url
) -> pd.DataFrame:
   """
   Generate one meta-insight per slide by summarizing multiple category insights.
   """
   rows = []
   for slide_id, categories in slide_mapping.items():
       cat_insights = insights_df.loc[
           insights_df["category"].isin(categories),
           ["category", "insight"],
       ]
       if cat_insights.empty:
           continue

       insight_lines = "\n".join(
           f"- {r['category']}: {r['insight']}"
           for _, r in cat_insights.iterrows()
           if isinstance(r["insight"], str) and r["insight"].strip()
       )
       if not insight_lines:
           continue

       base_scaffold = (
           f"Slide: {slide_id}\n"
           f"Categories and insights:\n{insight_lines}\n\n"
       )
       user_prompt = base_scaffold + (user_meta_prompt or "").strip()
       rows.append({"slide_id": slide_id, "prompt": user_prompt})

   if not rows:
       return pd.DataFrame(columns=["slide_id", "meta_insight"])

   client = Anthropic(api_key=api_key, timeout=timeout)

   meta_insights = []
   start = time.time()
   for row in rows:
       try:
           response = _call_with_retry(
               client=client,
               model=model,
               max_tokens=max_tokens,
               temperature=temperature,
               top_p=top_p,
               system=system_prompt,
               messages=[{"role": "user", "content": row["prompt"]}]
           )
           text = response.content[0].text.strip()
           text = clean_meta_insight(text)
           text = soften_meta_and_vary(text)

       except APIError as e:
           text = f"(LLM error: {e})"
       except Exception as e:
           text = f"(Unexpected error: {e})"

       meta_insights.append({"slide_id": row["slide_id"], "meta_insight": text})

   elapsed = time.time() - start
   print(
       f"✓ Meta-insights generated in {elapsed:.2f}s "
       f"({elapsed / max(1, len(rows)):.2f}s/slide) using {model}"
   )
   return pd.DataFrame(meta_insights)


# =============================================================================
# Total slide: single topline subheader - CLAUDE API
# =============================================================================
def _pick_first_total_row(df_tot: Union[pd.DataFrame, list]) -> Optional[pd.Series]:
   """
   (Legacy helper, kept for compatibility.)
   """
   C = {
       "f_asp": "Forecast_ASP",
       "a_asp": "Actual_ASP",
       "diff_asp": "Diff (%)_ASP",
       "f_units": "Forecast_Units",
       "a_units": "Actual_Units",
       "diff_units": "Diff (%)_Units",
       "f_dollars": "Forecast_Dollars",
       "a_dollars": "Actual_Dollars",
       "diff_dollars": "Diff (%)_Dollars",
   }

   def has_cols(df: pd.DataFrame) -> bool:
       return all(col in df.columns for col in C.values())

   if isinstance(df_tot, list):
       for t in df_tot:
           if isinstance(t, pd.DataFrame) and not t.empty and has_cols(t):
               return t.iloc[0]
       return None
   if isinstance(df_tot, pd.DataFrame) and not df_tot.empty and has_cols(df_tot):
       return df_tot.iloc[0]
   return None


def generate_total_slide_subheader(
   df_tot,
   *,
   system_prompt: str,
   user_total_prompt: str,
   api_key: str,
   model: str = CLAUDE_MODEL,
   temperature: float = 0.9,
   top_p: float = 0.97,
   max_tokens: int = 350,
   timeout: int = 70,
   **kwargs  # Catch unused params like base_url
) -> str:
   """
   Create a single 20-25 word topline subheader for the TOTAL slide.
   """
   pv = pivot_total_table(df_tot)
   if pv is None or pv.empty:
       return "Topline: total slide metrics unavailable."

   def fmt(metric: str) -> str:
       if metric not in pv.index:
           return ""
       row = pv.loc[metric]
       f, a, d = row.get("Forecast"), row.get("Actual"), row.get("Diff (%)")

       def safe(v):
           return "NA" if pd.isna(v) else f"{float(v):.1f}%"

       return f"- {metric} → Forecast: {safe(f)} | Actual: {safe(a)} | Diff: {safe(d)}"

   lines = [fmt("ASP"), fmt("Units"), fmt("Dollars")]
   lines = [ln for ln in lines if ln]

   scaffold = "TOTAL (topline) metrics:\n" + "\n".join(lines) + "\n\n"
   user_prompt = scaffold + (user_total_prompt or "").strip()

   client = Anthropic(api_key=api_key, timeout=timeout)
   try:
       response = _call_with_retry(
           client=client,
           model=model,
           max_tokens=max_tokens,
           temperature=temperature,
           top_p=top_p,
           system=(
               system_prompt
               + "\n\n"
               "20-25 words maximum, professional, insight-led. Do NOT invent numbers; "
               "Emphasize forecast vs actual and the main driver briefly. "
           ),
           messages=[{"role": "user", "content": user_prompt}]
       )
       text = response.content[0].text.strip()
       text = clean_meta_insight(text)

       # Try to pull the Dollar diff for tone calibration
       dollar_diff = None
       if "Dollars" in pv.index and "Diff (%)" in pv.columns:
           try:
               dollar_diff = pv.loc["Dollars", "Diff (%)"]
           except Exception:
               dollar_diff = None

       text = calibrate_tone_for_accuracy_and_synonyms(text, dollar_diff)
       text = soften_meta_and_vary(text)
   except APIError as e:
       text = f"(LLM error: {e})"
   except Exception as e:
       text = f"(Unexpected error: {e})"

   return text or "Topline: no subheader produced."


# =============================================================================
# Sampling past insights into prompts (unchanged)
# =============================================================================
def append_sampled_csv_rows_to_prompt(
       csv_path: str,
       prompt_key: str,
       sample_size: int,
       columns_to_include: Optional[list] = None,
       seed: Optional[int] = None,
       section_title: str = "Example Insights",
       context_description: Optional[str] = None,
) -> str:
   """
   Append sampled rows from ANY CSV to a prompt.

   NOTE: This function mutates CONFIG[prompt_key] if CONFIG is available.
   Kept intact for backward compatibility.
   """

   # Read CSV
   try:
       df = pd.read_csv(csv_path)
   except Exception as e:
       print(f"Warning: Could not load CSV at {csv_path}: {e}")
       return CONFIG.get(prompt_key, "")

   if df.empty:
       print(f"Warning: CSV at {csv_path} is empty")
       return CONFIG.get(prompt_key, "")

   # Set random seed if provided
   if seed is not None:
       random.seed(seed)
       try:
           import numpy as np
           np.random.seed(seed)
       except Exception:
           pass

   # Sample rows
   n_samples = min(sample_size, len(df))
   sampled_df = df.sample(n=n_samples, random_state=seed)

   # Determine which columns to show
   if columns_to_include:
       missing = set(columns_to_include) - set(df.columns)
       if missing:
           print(f"Warning: Columns not found in CSV: {missing}")
           print(f"          Available columns: {list(df.columns)}")
           columns_to_show = [c for c in columns_to_include if c in df.columns]
       else:
           columns_to_show = columns_to_include
   else:
       columns_to_show = list(df.columns)

   if not columns_to_show:
       print("Warning: No valid columns to display")
       return CONFIG.get(prompt_key, "")

   # Format rows as bullets
   bullets = []
   for _, row in sampled_df.iterrows():
       row_parts = []
       for col in columns_to_show:
           value = str(row[col]).strip()
           if value and value.lower() not in ('nan', 'none', ''):
               if len(columns_to_show) > 1:
                   row_parts.append(f"{col}: {value}")
               else:
                   row_parts.append(value)

       if row_parts:
           bullets.append(f"• {' | '.join(row_parts)}")

   if not bullets:
       print("Warning: No valid content to display from sampled rows")
       return CONFIG.get(prompt_key, "")

   bullets_text = "\n".join(bullets)

   section_parts = []
   if context_description:
       section_parts.append(f"\n{context_description}\n")

   section_parts.append(f"\n{section_title}:")
   section_parts.append(bullets_text)

   examples_block = "\n".join(section_parts)

   base_prompt = CONFIG.get(prompt_key, "")

   if section_title in base_prompt:
       parts = base_prompt.split(section_title, 1)
       updated_prompt = f"{parts[0].strip()}{examples_block}"
   else:
       updated_prompt = f"{base_prompt.strip()}{examples_block}"

   CONFIG[prompt_key] = updated_prompt
   print(f"✓ Added {len(bullets)} sampled examples to {prompt_key}")
   print(f"     Columns included: {columns_to_show}")

   return updated_prompt


def add_example_insights_from_csv(
       csv_path: str,
       prompt_key: str = "SYSTEM_PROMPT",
       sample_size: int = 5,
       insight_column: str = "Refined Insight",
       score_column: Optional[str] = "Score",
       seed: Optional[int] = None,
) -> str:
   columns = [insight_column]
   if score_column:
       columns.append(score_column)

   return append_sampled_csv_rows_to_prompt(
       csv_path=csv_path,
       prompt_key=prompt_key,
       sample_size=sample_size,
       columns_to_include=columns,
       seed=seed,
       section_title="Example Insights",
       context_description=(
           "Use these examples as style and tone guidance. "
           "Adapt to your specific data - do not copy verbatim."
       )
   )


def add_csv_examples(
       csv_path: str,
       prompt_key: str,
       n: int = 5,
       seed: Optional[int] = None
) -> str:
   return append_sampled_csv_rows_to_prompt(
       csv_path=csv_path,
       prompt_key=prompt_key,
       sample_size=n,
       columns_to_include=None,
       seed=seed,
       section_title="Example Insights",
       context_description="Reference these examples for style and structure:"
   )


"""
Add this function to llm_insights_claude.py

This generates meta-insights directly from raw category data,
bypassing the need for individual category insights first.
"""


def _analyze_slide_narrative(
    category_metrics: list,
    thresholds: dict = None,
    driver_diff_threshold: float = 3.0,
    accuracy_emphasis: float = 0.6,
    framing_weights: dict = None
) -> dict:
   """
   Pre-analyze category data to determine the narrative directive for this slide.
   Returns structured analysis with PROBABILITY-WEIGHTED framing selection.

   BALANCED PHILOSOPHY:
   Accuracy is important but not always the lead. The framing is selected
   probabilistically based on what the data naturally supports:
   - Tight accuracy → higher probability of accuracy-led framing
   - Mixed results → allow contrast, driver, or variance framings to emerge
   - Strong driver story → driver-led framing becomes more likely

   This function determines:
   - Framing type (probabilistically selected based on data characteristics)
   - Accuracy highlight (what forecasts got right)
   - Supporting context (drivers, contrasts, or variance explanation)
   - Spotlight categories (max 2)
   - Driver dynamics

   Args:
       category_metrics: List of dicts with category data
       thresholds: Dict with threshold values (from config). Defaults provided if None.
       driver_diff_threshold: Minimum pp difference to declare unit vs ASP dominant
       accuracy_emphasis: Float 0.0-1.0 controlling bias toward accuracy framing (default 0.6)
       framing_weights: Optional dict to override default framing probabilities

   Returns:
       Dict with framing, accuracy_highlight, supporting_context, spotlight_categories, etc.
   """
   # Default thresholds if not provided (can be overridden from config)
   if thresholds is None:
       thresholds = {
           "precision_pp": 2.0,
           "tight_pp": 3.5,
           "solid_pp": 5.0,
           "contrast_tight_pp": 3.5,
           "contrast_wide_pp": 8.0,
           "significant_miss_pp": 10.0
       }

   if not category_metrics:
       return {
           "framing": "ACCURACY-LED",
           "lead_metric": "dollars",
           "spotlight_categories": [],
           "driver": "balanced",
           "dynamics": "balanced",
           "story_summary": "no data available",
           "pattern": "no_data",
           "accuracy_highlight": "",
           "supporting_context": "",
           "context_type": None,
           "all_metrics": []
       }

   # Ensure required fields are present (handle both naming conventions)
   for m in category_metrics:
       if 'abs_variance' not in m:
           m['abs_variance'] = abs(m.get('dollar_variance_pp', m.get('dollar_diff', 0)))
       if 'units_diff' not in m:
           m['units_diff'] = m.get('units_variance_pp', 0)
       if 'asp_diff' not in m:
           m['asp_diff'] = m.get('asp_variance_pp', 0)

   # Sort by absolute variance (most accurate first - THIS IS KEY)
   sorted_metrics = sorted(category_metrics, key=lambda x: x['abs_variance'])

   # Get variance statistics
   variances = [m['abs_variance'] for m in category_metrics]
   best_var = min(variances)
   worst_var = max(variances)
   avg_var = sum(variances) / len(variances)

   # Get the best and worst performing categories
   best_cat = sorted_metrics[0]
   worst_cat = sorted_metrics[-1]

   # Count how many categories achieved tight accuracy
   tight_count = sum(1 for v in variances if v <= thresholds["tight_pp"])
   solid_count = sum(1 for v in variances if v <= thresholds["solid_pp"])

   # ==========================================================================
   # STEP 1: ALWAYS IDENTIFY ACCURACY ACHIEVEMENT FIRST (PRIMARY MESSAGE)
   # ==========================================================================

   # Determine accuracy tier for BEST performer
   if best_var <= thresholds["precision_pp"]:
       accuracy_tier = "precision"
       accuracy_descriptor = "precision"
   elif best_var <= thresholds["tight_pp"]:
       accuracy_tier = "tight"
       accuracy_descriptor = "tight accuracy"
   elif best_var <= thresholds["solid_pp"]:
       accuracy_tier = "solid"
       accuracy_descriptor = "solid accuracy"
   else:
       accuracy_tier = "moderate"
       accuracy_descriptor = "directional accuracy"

   # Build the PRIMARY accuracy highlight
   if tight_count == len(variances):
       # ALL categories achieved tight accuracy - strong story
       accuracy_highlight = f"All {len(variances)} categories achieved {accuracy_descriptor} (within {thresholds['tight_pp']}pp)"
   elif tight_count > 1:
       # Multiple tight performers
       tight_cats = [m['category'] for m in sorted_metrics[:tight_count]]
       accuracy_highlight = f"{tight_count} of {len(variances)} categories achieved tight accuracy, led by {best_cat['category']} at {best_var:.1f}pp"
   elif best_var <= thresholds["solid_pp"]:
       # At least one solid performer
       accuracy_highlight = f"{best_cat['category']} achieved {accuracy_descriptor} at {best_var:.1f}pp"
   else:
       # Even in challenging conditions, find the positive angle
       accuracy_highlight = f"{best_cat['category']} closest to forecast at {best_var:.1f}pp"

   # ==========================================================================
   # STEP 2: DETERMINE SUPPORTING CONTEXT (SECONDARY MESSAGE)
   # ==========================================================================

   # Determine what supporting context is most relevant
   has_significant_miss = worst_var >= thresholds["significant_miss_pp"]
   has_contrast = best_var <= thresholds["contrast_tight_pp"] and worst_var >= thresholds["contrast_wide_pp"]

   # Calculate driver dynamics
   avg_units_var = sum(abs(m['units_diff']) for m in category_metrics) / len(category_metrics)
   avg_asp_var = sum(abs(m['asp_diff']) for m in category_metrics) / len(category_metrics)
   has_driver_story = abs(avg_units_var - avg_asp_var) >= driver_diff_threshold

   # Determine driver
   if avg_units_var > avg_asp_var + 2.0:
       driver = "unit-driven"
   elif avg_asp_var > avg_units_var + 2.0:
       driver = "asp-driven"
   else:
       driver = "balanced"

   # Check offsetting vs reinforcing dynamics
   units_sign = 1 if best_cat['units_diff'] >= 0 else -1
   asp_sign = 1 if best_cat['asp_diff'] >= 0 else -1
   dynamics = "offsetting" if units_sign != asp_sign else "reinforcing"

   # Build supporting context based on what's most relevant
   if has_significant_miss:
       # Explain the variance, but don't lead with it
       supporting_context = f"variance_explanation: {worst_cat['category']} diverged at {worst_var:.1f}pp"
       context_type = "variance_explanation"
   elif has_contrast and worst_var > thresholds["solid_pp"]:
       # Note the contrast, but accuracy is still the lead
       supporting_context = f"contrast: {worst_cat['category']} showed wider variance at {worst_var:.1f}pp"
       context_type = "contrast"
   elif has_driver_story:
       # Explain the driver dynamics
       if dynamics == "offsetting":
           supporting_context = f"driver: {driver} dynamics with offsetting ASP/unit movements"
       else:
           supporting_context = f"driver: {driver} dynamics reinforced results"
       context_type = "driver"
   else:
       # General driver explanation
       supporting_context = f"driver: {dynamics} value-volume dynamics"
       context_type = "driver"

   # ==========================================================================
   # STEP 3: DETERMINE FRAMING (probability-weighted based on data)
   # ==========================================================================

   # Pattern describes the overall accuracy picture
   if all(v <= thresholds["precision_pp"] for v in variances):
       pattern = "precision"
   elif all(v <= thresholds["tight_pp"] for v in variances):
       pattern = "tight_accuracy"
   elif all(v <= thresholds["solid_pp"] for v in variances):
       pattern = "solid_accuracy"
   elif has_contrast:
       pattern = "mixed_with_contrast"
   elif has_significant_miss:
       pattern = "mixed_with_variance"
   else:
       pattern = "mixed"

   # Define default framing weights based on pattern (can be overridden)
   # Format: {"ACCURACY-LED": prob, "DRIVER-LED": prob, "CONTRAST-LED": prob, "VARIANCE-LED": prob}
   default_weights = {
       "precision": {"ACCURACY-LED": 0.85, "DRIVER-LED": 0.15, "CONTRAST-LED": 0.0, "VARIANCE-LED": 0.0},
       "tight_accuracy": {"ACCURACY-LED": 0.70, "DRIVER-LED": 0.25, "CONTRAST-LED": 0.05, "VARIANCE-LED": 0.0},
       "solid_accuracy": {"ACCURACY-LED": 0.55, "DRIVER-LED": 0.30, "CONTRAST-LED": 0.15, "VARIANCE-LED": 0.0},
       "mixed_with_contrast": {"ACCURACY-LED": 0.35, "DRIVER-LED": 0.20, "CONTRAST-LED": 0.40, "VARIANCE-LED": 0.05},
       "mixed_with_variance": {"ACCURACY-LED": 0.25, "DRIVER-LED": 0.25, "CONTRAST-LED": 0.15, "VARIANCE-LED": 0.35},
       "mixed": {"ACCURACY-LED": 0.40, "DRIVER-LED": 0.35, "CONTRAST-LED": 0.15, "VARIANCE-LED": 0.10},
   }

   # Get weights for this pattern
   weights = framing_weights if framing_weights else default_weights.get(pattern, default_weights["mixed"])

   # Apply accuracy_emphasis modifier (shifts probability toward ACCURACY-LED)
   # accuracy_emphasis of 0.6 is neutral, >0.6 increases accuracy bias, <0.6 decreases it
   if accuracy_emphasis != 0.6:
       emphasis_shift = (accuracy_emphasis - 0.6) * 0.5  # Max shift of ±0.2
       accuracy_prob = min(0.95, max(0.15, weights.get("ACCURACY-LED", 0.4) + emphasis_shift))
       remaining = 1.0 - accuracy_prob
       other_total = sum(v for k, v in weights.items() if k != "ACCURACY-LED")
       if other_total > 0:
           scale = remaining / other_total
           weights = {k: (v * scale if k != "ACCURACY-LED" else accuracy_prob) for k, v in weights.items()}
       else:
           weights["ACCURACY-LED"] = accuracy_prob

   # Probabilistic framing selection
   rand_val = random.random()
   cumulative = 0.0
   framing = "ACCURACY-LED"  # Default fallback
   for frame_type, prob in weights.items():
       cumulative += prob
       if rand_val < cumulative:
           framing = frame_type
           break

   # ==========================================================================
   # STEP 4: DETERMINE LEAD METRIC (prefer dollars for accuracy story)
   # ==========================================================================

   # For accuracy-led framing, prefer dollars unless drivers are the supporting story
   if context_type == "driver" and driver != "balanced":
       lead_metric = "units" if driver == "unit-driven" else "asp"
   else:
       lead_metric = "dollars"

   # ==========================================================================
   # STEP 5: SELECT SPOTLIGHT CATEGORIES (prioritize accurate performers)
   # ==========================================================================

   spotlight_categories = [best_cat['category']]

   # Add second category strategically
   if len(sorted_metrics) > 1:
       if context_type == "contrast" or context_type == "variance_explanation":
           # Include the wider performer for context
           if worst_cat['category'] != best_cat['category']:
               spotlight_categories.append(worst_cat['category'])
       elif sorted_metrics[1]['abs_variance'] <= thresholds["tight_pp"]:
           # Include another tight performer
           spotlight_categories.append(sorted_metrics[1]['category'])

   # ==========================================================================
   # STEP 6: GENERATE STORY SUMMARY (adapts to selected framing)
   # ==========================================================================

   # Story summary adapts to the probabilistically selected framing
   if framing == "ACCURACY-LED":
       if pattern == "precision":
           story_summary = f"Highlight precision across categories (all within {thresholds['precision_pp']}pp)"
       elif pattern in ("tight_accuracy", "solid_accuracy"):
           story_summary = f"Highlight {accuracy_tier} accuracy; {best_cat['category']} at {best_var:.1f}pp"
       else:
           story_summary = f"Note {best_cat['category']} accuracy ({best_var:.1f}pp) with supporting context"
   elif framing == "DRIVER-LED":
       if dynamics == "offsetting":
           story_summary = f"Lead with {driver} dynamics (offsetting movements); accuracy as outcome"
       else:
           story_summary = f"Lead with {driver} dynamics shaping results; note accuracy where relevant"
   elif framing == "CONTRAST-LED":
       story_summary = f"Contrast {best_cat['category']} ({best_var:.1f}pp) vs {worst_cat['category']} ({worst_var:.1f}pp)"
   elif framing == "VARIANCE-LED":
       story_summary = f"Explain {worst_cat['category']} variance ({worst_var:.1f}pp); note {best_cat['category']} stability"
   else:
       story_summary = f"Synthesize results with {best_cat['category']} as reference point"

   return {
       "framing": framing,
       "pattern": pattern,
       "lead_metric": lead_metric,
       "spotlight_categories": spotlight_categories,
       "driver": driver,
       "dynamics": dynamics,
       # NEW: Structured accuracy-first messaging
       "accuracy_highlight": accuracy_highlight,
       "supporting_context": supporting_context,
       "context_type": context_type,
       "story_summary": story_summary,
       # Statistics for reference
       "best_category": best_cat,
       "worst_category": worst_cat,
       "best_variance": best_var,
       "worst_variance": worst_var,
       "tight_count": tight_count,
       "total_categories": len(category_metrics),
       "all_metrics": sorted_metrics,
       "thresholds_used": thresholds
   }


def _extract_opening_pattern(text: str) -> str:
   """Extract the first 3-4 words as the opening pattern to avoid."""
   if not text:
       return ""
   words = text.split()[:4]
   return " ".join(words).rstrip(",.:;")


def _build_meta_prompt_clean(
       slide_id: str,
       category_metrics: list,
       previous_insights: list,
       user_meta_prompt: str,
       sampled_examples: list = None,
       narrative_directive: dict = None,
       look_back_slides: int = 4
) -> str:
   """
   Build a well-structured prompt for meta-insight generation.

   Structure:
   1. Style examples first (primary teaching signal)
   2. Data with clear context
   3. Narrative directive (deterministic framing - NEW)
   4. Variety guidance (anti-repetition)
   5. Task instructions

   Args:
       slide_id: Identifier for this slide
       category_metrics: List of category data dicts
       previous_insights: List of (slide_id, insight) tuples from prior slides
       user_meta_prompt: The task instructions from prompt file
       sampled_examples: Management-approved example insights
       narrative_directive: Dict from _analyze_slide_narrative() with framing decisions
       look_back_slides: Number of previous insights to check for repetition (default 4)
   """
   sections = []

   # SECTION 1: APPROVED EXAMPLES (primary style guide - placed first for emphasis)
   if sampled_examples:
       sections.append("=== APPROVED STYLE EXAMPLES ===\n\n")
       sections.append("**Study these carefully - they represent Circana's industry-standard style.**\n")
       sections.append("These were approved by management and delivered to paying clients.\n")
       sections.append("Replicate their tone, structure, and professional balance:\n\n")
       for ex in sampled_examples:
           insight = (
               ex.get('Refined Insight') or
               ex.get('insight') or
               ex.get('Insight') or
               ex.get('meta_insight')
           )
           if insight:
               sections.append(f"• {insight}\n")
       sections.append("\n")

   # SECTION 2: SLIDE DATA with clear context
   sections.append(f"=== SLIDE DATA: {slide_id} ===\n\n")
   sections.append("Category metrics below show year-over-year percentage changes.\n")
   sections.append("Variance = Forecast minus Actual (positive means forecast exceeded actual).\n\n")

   for m in category_metrics:
       # Use full "percentage points" for variance to reinforce the rule
       sections.append(
           f"**{m['category']}**\n"
           f"  • Dollars: Forecast {m['forecast_dollars']:+.1f}% YoY → Actual {m['actual_dollars']:+.1f}% YoY → Variance {m['dollar_diff']:+.1f} percentage points\n"
           f"  • Units:   Forecast {m['forecast_units']:+.1f}% YoY → Actual {m['actual_units']:+.1f}% YoY → Variance {m['units_diff']:+.1f} percentage points\n"
           f"  • ASP:     Forecast {m['forecast_asp']:+.1f}% YoY → Actual {m['actual_asp']:+.1f}% YoY → Variance {m['asp_diff']:+.1f} percentage points\n\n"
       )

   # SECTION 3: NARRATIVE DIRECTIVE (framing-aware guidance)
   if narrative_directive:
       framing = narrative_directive.get('framing', 'ACCURACY-LED')
       sections.append(f"=== NARRATIVE GUIDANCE ({framing}) ===\n\n")

       # Framing-specific lead guidance
       accuracy_highlight = narrative_directive.get('accuracy_highlight', '')
       supporting_context = narrative_directive.get('supporting_context', '')
       context_type = narrative_directive.get('context_type', 'driver')
       story_summary = narrative_directive.get('story_summary', '')

       if framing == "ACCURACY-LED":
           sections.append(f"**SUGGESTED LEAD:** {accuracy_highlight}\n")
           if supporting_context:
               sections.append(f"**SUPPORTING CONTEXT:** {supporting_context}\n\n")
       elif framing == "DRIVER-LED":
           driver = narrative_directive.get('driver', 'balanced')
           dynamics = narrative_directive.get('dynamics', 'balanced')
           sections.append(f"**SUGGESTED LEAD:** {driver.replace('-', ' ')} dynamics ({dynamics} movements)\n")
           sections.append(f"**ACCURACY NOTE:** {accuracy_highlight}\n\n")
       elif framing == "CONTRAST-LED":
           best_cat = narrative_directive.get('best_category', {})
           worst_cat = narrative_directive.get('worst_category', {})
           sections.append(f"**SUGGESTED LEAD:** Contrast between performers\n")
           sections.append(f"  • Tight: {best_cat.get('category', 'N/A')} at {narrative_directive.get('best_variance', 0):.1f}pp\n")
           sections.append(f"  • Wide: {worst_cat.get('category', 'N/A')} at {narrative_directive.get('worst_variance', 0):.1f}pp\n\n")
       elif framing == "VARIANCE-LED":
           sections.append(f"**SUGGESTED LEAD:** Explain the variance drivers\n")
           sections.append(f"**STABILITY NOTE:** {accuracy_highlight}\n\n")

       # Story summary (guidance, not mandate)
       if story_summary:
           sections.append(f"NARRATIVE ANGLE: {story_summary}\n\n")

       # Spotlight and metrics
       spotlight = narrative_directive.get('spotlight_categories', [])
       if spotlight:
           sections.append(f"SPOTLIGHT CATEGORIES: {', '.join(spotlight)}\n")
       sections.append(f"SUGGESTED LEAD METRIC: {narrative_directive.get('lead_metric', 'dollars').capitalize()}\n")
       sections.append(f"DRIVER DYNAMICS: {narrative_directive.get('dynamics', 'balanced')}\n\n")

       # Accuracy statistics for reference (always useful context)
       tight_count = narrative_directive.get('tight_count', 0)
       total_cats = narrative_directive.get('total_categories', 0)
       best_var = narrative_directive.get('best_variance', 0)
       if tight_count and total_cats:
           sections.append(f"ACCURACY CONTEXT: {tight_count}/{total_cats} categories within tight threshold; best at {best_var:.1f}pp\n\n")

       # Framing-specific writing guidance (softer than before)
       sections.append("WRITING GUIDANCE:\n")
       if framing == "ACCURACY-LED":
           sections.append("• Lead with what forecasts got right, then add driver context\n")
           sections.append("• Use accuracy vocabulary naturally: 'tracked closely', 'achieved alignment', 'landed within'\n")
       elif framing == "DRIVER-LED":
           sections.append("• Lead with the driver story (ASP/unit dynamics), weave in accuracy as outcome\n")
           sections.append("• Phrases like 'pricing strength cushioned...', 'demand patterns drove...'\n")
       elif framing == "CONTRAST-LED":
           sections.append("• Lead with the contrast between performers using 'while', 'whereas', 'in contrast'\n")
           sections.append("• Both accuracy and variance are part of the story\n")
       elif framing == "VARIANCE-LED":
           sections.append("• Lead with explaining the variance, note stability where present\n")
           sections.append("• Be honest about misses but explain the drivers\n")

       sections.append("• Spotlight max 2 categories; synthesize don't enumerate\n")
       sections.append("• Let the data guide emphasis - this is guidance, not a rigid template\n\n")

   # SECTION 4: VARIETY GUIDANCE (avoid repetition) - Extended to look_back_slides
   if previous_insights:
       sections.append("=== PREVIOUS INSIGHTS (vary your approach) ===\n\n")
       sections.append("Do not repeat these sentence structures, openers, or phrasing:\n\n")

       # Use configurable look-back window
       recent_insights = previous_insights[-look_back_slides:]
       recent_text = " ".join([ins for _, ins in recent_insights])
       recent_lower = recent_text.lower()

       # Enhanced pattern detection with extended look-back
       has_asp_offset = any(phrase in recent_lower for phrase in
           ["offset", "offsetting", "cushion", "compensat"])
       has_headwinds = "headwind" in recent_lower
       has_alignment = recent_lower.count("align") >= 2
       has_precision = "precision" in recent_lower
       has_forecasts_opener = sum(1 for _, ins in recent_insights
           if ins.lower().strip().startswith(("forecast", "forecasts"))) >= 2
       has_variance_framing = sum(1 for phrase in ["fell", "missed", "underperform", "below forecast"]
           if phrase in recent_lower) >= 2
       has_accuracy_framing = sum(1 for phrase in ["delivered tight", "achieved", "tracked closely", "on-point"]
           if phrase in recent_lower) >= 2
       has_notably = sum(1 for phrase in ["notably", "of note", "standout"] if phrase in recent_lower) >= 2
       has_conversely = sum(1 for phrase in ["conversely", "in contrast", "meanwhile"] if phrase in recent_lower) >= 2
       has_dollars_lead = sum(1 for _, ins in recent_insights
           if any(ins.lower().strip().startswith(word) for word in ["dollar", "revenue"])) >= 2
       has_tracked_within = recent_lower.count("tracked within") >= 2 or recent_lower.count("within") >= 4
       has_softness = recent_lower.count("softness") >= 2 or recent_lower.count("soft") >= 3

       # NEW: Track opener patterns (first 3 words)
       recent_openers = []
       for _, ins in recent_insights:
           opener = " ".join(ins.split()[:3]).lower().rstrip(",.:;")
           recent_openers.append(opener)

       # NEW: Track category mentions to avoid over-repetition
       mentioned_categories = set()
       for _, ins in recent_insights:
           # Simple extraction of capitalized words that might be categories
           words = ins.split()
           for i, word in enumerate(words):
               if word and word[0].isupper() and len(word) > 2:
                   # Check if it's likely a category (not sentence start)
                   if i > 0 or (i == 0 and len(recent_insights) > 1):
                       mentioned_categories.add(word.lower().rstrip(",.:;"))

       for prev_slide, prev_insight in recent_insights:
           sections.append(f"• {prev_insight}\n")

       sections.append("\n")

       # Build specific avoidance list
       avoid_phrases = []
       avoid_openers = []

       if has_asp_offset:
           avoid_phrases.extend(["offset", "cushioned", "compensated"])
       if has_headwinds:
           avoid_phrases.append("headwinds")
       if has_alignment:
           avoid_phrases.append("aligned")
       if has_precision:
           avoid_phrases.append("precision")
       if has_tracked_within:
           avoid_phrases.extend(["tracked within", "within"])
       if has_softness:
           avoid_phrases.extend(["softness", "soft"])
       if has_conversely:
           avoid_phrases.extend(["in contrast", "conversely"])

       if has_forecasts_opener:
           avoid_openers.append("Forecasts...")
       if has_dollars_lead:
           avoid_openers.extend(["Dollar...", "Revenue..."])

       # Add AVOID section if we have specific things to avoid
       if avoid_phrases or avoid_openers:
           sections.append("AVOID (overused in recent slides):\n")
           if avoid_openers:
               sections.append(f"• Openers: {', '.join(avoid_openers)}\n")
           if avoid_phrases:
               sections.append(f"• Phrases: {', '.join(avoid_phrases[:6])}\n")  # Limit to 6
           sections.append("\n")

       # Add specific variety guidance based on detected patterns
       variety_notes = []
       if has_asp_offset:
           variety_notes.append("• ASP/units offset language used recently - use continuity ('consistent with trends') or focus on dominant driver only")
       if has_headwinds:
           variety_notes.append("• 'Headwinds' used recently - use alternatives: pressures, challenges, weakness")
       if has_alignment:
           variety_notes.append("• 'Alignment/aligned' overused - try: tracked closely, landed within, came in at")
       if has_precision:
           variety_notes.append("• 'Precision' used recently - rotate to: tight accuracy, strong accuracy, on-point")
       if has_forecasts_opener:
           variety_notes.append("• Multiple insights started with 'Forecasts...' - vary opener: lead with category name, driver, or contrast")
       if has_variance_framing and narrative_directive and narrative_directive.get('framing') != 'VARIANCE-LED':
           variety_notes.append("• Variance-led framing used frequently - try accuracy-led or driver-led framing")
       if has_accuracy_framing and narrative_directive and narrative_directive.get('framing') != 'ACCURACY-LED':
           variety_notes.append("• Accuracy-led framing used frequently - try contrast-led or driver-led framing")
       if has_notably:
           variety_notes.append("• 'Notably/standout' used frequently - use sparingly")
       if has_conversely:
           variety_notes.append("• 'Conversely/in contrast' overused - try: whereas, meanwhile, however, while")
       if has_dollars_lead:
           variety_notes.append("• Recent insights led with dollars/revenue - consider leading with units/demand")
       if has_tracked_within:
           variety_notes.append("• 'Tracked within'/'within' overused - try: landed at, came in at, or qualitative")
       if has_softness:
           variety_notes.append("• 'Softness/soft' overused - try: weakness, pressure, decline, drag")

       if variety_notes:
           sections.append("VARIETY SUGGESTIONS:\n")
           sections.append("\n".join(variety_notes[:5]))  # Limit to 5 suggestions
           sections.append("\n\n")

   # SECTION 5: TASK (instructions last, closest to where model generates)
   sections.append("=== YOUR TASK ===\n\n")
   sections.append(user_meta_prompt)

   return "".join(sections)


def generate_meta_slide_insights_from_data(
       slide_mapping: dict,
       collapsed_df: pd.DataFrame,
       system_prompt: str,
       user_meta_prompt: str,
       api_key: str,
       model: str = CLAUDE_MODEL,
       temperature: float = 0.8,
       top_p: float = 0.88,
       max_tokens: int = 300,
       timeout: int = 60,
       sampled_examples: list = None,
       narrative_config: dict = None,
       **kwargs
) -> pd.DataFrame:
   """
   Generate meta-insights directly from category DATA with sequential context.

   Uses PROBABILITY-WEIGHTED narrative analysis that selects framing based on
   what the data naturally supports:
   - Tight accuracy → higher probability of accuracy-led framing
   - Mixed results → contrast, driver, or variance framings can emerge
   - Strong driver story → driver-led framing becomes more likely

   This maintains accuracy as an important theme while allowing natural variety
   in how insights are framed.

   Args:
       slide_mapping: Dict mapping slide_id to list of categories
       collapsed_df: DataFrame with category metrics
       system_prompt: System prompt for LLM
       user_meta_prompt: User task prompt
       api_key: Anthropic API key
       model: Model to use
       temperature: LLM temperature
       top_p: LLM top_p
       max_tokens: Max tokens for response
       timeout: API timeout
       sampled_examples: Management-approved example insights
       narrative_config: Dict with narrative analysis settings from config:
           - enabled: bool (default True)
           - look_back_slides: int (default 4)
           - variation_probability: float (default 0.75)
           - thresholds: dict with threshold values
           - driver_difference_threshold_pp: float (default 3.0)
           - accuracy_emphasis: float 0.0-1.0 (default 0.6, balanced)
             Higher values bias toward accuracy-led framing
           - framing_weights: dict to override default framing probabilities
   """
   # Extract narrative config settings with defaults
   if narrative_config is None:
       narrative_config = {}

   narrative_enabled = narrative_config.get('enabled', True)
   look_back_slides = narrative_config.get('look_back_slides', 4)
   variation_probability = narrative_config.get('variation_probability', 0.75)
   thresholds = narrative_config.get('thresholds', None)
   driver_diff_threshold = narrative_config.get('driver_difference_threshold_pp', 3.0)
   # NEW: Probability-weighted framing parameters
   accuracy_emphasis = narrative_config.get('accuracy_emphasis', 0.6)  # 0.0-1.0, 0.6 is balanced
   framing_weights = narrative_config.get('framing_weights', None)  # Optional override

   # Round data to 1 decimal place for cleaner LLM consumption
   numeric_cols = [col for col in collapsed_df.columns if col != 'category']
   collapsed_df_rounded = collapsed_df.copy()
   for col in numeric_cols:
       if col in collapsed_df_rounded.columns:
           collapsed_df_rounded[col] = excel_round(collapsed_df_rounded[col], decimals=1)

   rows = []
   for slide_id, categories in slide_mapping.items():
       cat_data = collapsed_df_rounded[
           collapsed_df_rounded["category"].isin(categories)
       ]

       if cat_data.empty:
           continue

       category_metrics = []

       for _, row in cat_data.iterrows():
           cat_name = row['category']
           # Extract variance (diff) values
           dollar_diff = row.get('Diff (%)_Dollars', 0)
           units_diff = row.get('Diff (%)_Units', 0)
           asp_diff = row.get('Diff (%)_ASP', 0)
           abs_variance = abs(dollar_diff)

           # Extract forecast values (YoY %)
           forecast_dollars = row.get('Forecast_Dollars', 0)
           forecast_units = row.get('Forecast_Units', 0)
           forecast_asp = row.get('Forecast_ASP', 0)

           # Extract actual values (YoY %)
           actual_dollars = row.get('Actual_Dollars', 0)
           actual_units = row.get('Actual_Units', 0)
           actual_asp = row.get('Actual_ASP', 0)

           category_metrics.append({
               'category': cat_name,
               'abs_variance': abs_variance,
               # Variance (Forecast - Actual)
               'dollar_diff': dollar_diff,
               'units_diff': units_diff,
               'asp_diff': asp_diff,
               # Forecast YoY %
               'forecast_dollars': forecast_dollars,
               'forecast_units': forecast_units,
               'forecast_asp': forecast_asp,
               # Actual YoY %
               'actual_dollars': actual_dollars,
               'actual_units': actual_units,
               'actual_asp': actual_asp,
           })

       category_metrics.sort(key=lambda x: x['abs_variance'])

       rows.append({
           "slide_id": slide_id,
           "category_metrics": category_metrics,
           "categories": categories
       })

   if not rows:
       return pd.DataFrame(columns=["slide_id", "meta_insight"])

   client = Anthropic(api_key=api_key, timeout=timeout)

   meta_insights = []
   previous_insights = []
   start = time.time()
   total_slides = len(rows)

   print(f"\n{'─' * 60}")
   print(f"GENERATING META INSIGHTS ({total_slides} slides)")
   print(f"{'─' * 60}")

   for idx, row in enumerate(rows):
       slide_id = row['slide_id']
       category_metrics = row['category_metrics']
       categories = [m['category'] for m in category_metrics[:2]]

       # STEP 1: Probability-weighted narrative analysis (if enabled)
       narrative_directive = None
       if narrative_enabled:
           narrative_directive = _analyze_slide_narrative(
               category_metrics=category_metrics,
               thresholds=thresholds,
               driver_diff_threshold=driver_diff_threshold,
               accuracy_emphasis=accuracy_emphasis,
               framing_weights=framing_weights
           )
           # Log the narrative decision (now shows probabilistically selected framing)
           framing = narrative_directive.get('framing', 'N/A')
           pattern = narrative_directive.get('pattern', 'N/A')
           lead = narrative_directive.get('lead_metric', 'N/A')
           spotlight = narrative_directive.get('spotlight_categories', [])
           print(f"\n[{idx + 1}/{total_slides}] {slide_id}")
           print(f"    Pattern: {pattern} → Framing: {framing} | Lead: {lead} | Spotlight: {', '.join(spotlight)}")

       # STEP 2: Build prompt with narrative directive
       prompt = _build_meta_prompt_clean(
           slide_id=slide_id,
           category_metrics=category_metrics,
           previous_insights=previous_insights,  # Full list, function handles look-back
           user_meta_prompt=user_meta_prompt,
           sampled_examples=sampled_examples,
           narrative_directive=narrative_directive,
           look_back_slides=look_back_slides
       )

       # STEP 3: Call LLM
       try:
           response = _call_with_retry(
               client=client,
               model=model,
               max_tokens=max_tokens,
               temperature=temperature,
               top_p=top_p,
               system=system_prompt,
               messages=[{"role": "user", "content": prompt}]
           )
           text = response.content[0].text.strip()
           text = clean_meta_insight(text)
           # soften_meta_and_vary includes _vary_common_phrases with configurable probability
           text = soften_meta_and_vary(text, variation_probability=variation_probability)

       except APIError as e:
           text = f"(LLM error: {e})"
       except Exception as e:
           text = f"(Unexpected error: {e})"

       meta_insights.append({
           "slide_id": slide_id,
           "meta_insight": text
       })

       previous_insights.append((slide_id, text))

       # Real-time display of generated insight
       word_count = len(text.split())
       if not narrative_enabled:
           print(f"\n[{idx + 1}/{total_slides}] {slide_id}")
       print(f"    Categories: {', '.join(categories)}")
       print(f"    Insight ({word_count} words): \"{text[:100]}{'...' if len(text) > 100 else ''}\"")

   elapsed = time.time() - start
   print(f"\n{'─' * 60}")
   print(f"Complete: {total_slides} insights in {elapsed:.1f}s ({elapsed / max(1, total_slides):.1f}s/slide)")
   print(f"Narrative: {'ENABLED' if narrative_enabled else 'DISABLED'} | Accuracy emphasis: {accuracy_emphasis:.0%} | Variation: {variation_probability:.0%}")
   print(f"{'─' * 60}")

   return pd.DataFrame(meta_insights)


def generate_category_insights_optional(
       df: pd.DataFrame,
       system_prompt: str,
       row_prompt_template: str,
       *,
       col_map: Dict[str, str],
       api_key: str,
       model: str = CLAUDE_MODEL,
       temperature: float = 0.7,
       top_p: float = 0.9,
       max_tokens: int = 200,
       timeout: int = 60,
       **kwargs
) -> pd.DataFrame:
   """
   Generate individual category insights (for Excel export/tracking).

   OPTIONAL - only needed if you want detailed category-level insights in Excel.
   """
   return generate_llm_insights_remote(
       df=df,
       system_prompt=system_prompt,
       row_prompt_template=row_prompt_template,
       col_map=col_map,
       api_key=api_key,
       model=model,
       temperature=temperature,
       top_p=top_p,
       max_tokens=max_tokens,
       timeout=timeout,
       **kwargs
   )


from pathlib import Path
from typing import Optional, List
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
   """
   Appends N sampled example insights from a CSV to the END of a prompt.

   Examples are placed at the END to avoid confusing the model's primary task.
   The main prompt instructions come first, examples serve as supplementary reference.
   """
   base_prompt = (base_prompt or "").strip()

   path = Path(csv_path).expanduser().resolve()
   if not path.exists():
       raise FileNotFoundError(f"CSV not found: {path}")

   df = pd.read_csv(path)
   if df.empty:
       return base_prompt

   insight_columns = insight_columns or ["Refined Insight", "refined_insight", "insight", "Insight", "meta_insight"]

   def first_existing(cols: List[str]) -> Optional[str]:
       for c in cols:
           if c in df.columns:
               return c
       return None

   insight_col = first_existing(insight_columns)

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

   # Build examples block for END of prompt (supplementary reference)
   examples_block = (
       f"\n\n=== {section_title} ===\n"
       "Reference these approved examples for tone and structure (do not copy verbatim):\n"
       + "\n".join(bullets)
   )

   # Remove any existing marker if present (for idempotency)
   marker = f"=== {section_title} ==="
   if marker in base_prompt:
       base_prompt = base_prompt.split(marker, 1)[0].strip()

   # Append examples at the END
   return base_prompt + examples_block


# Legacy alias for backward compatibility
def append_sampled_insights_to_prompt(
   base_prompt: str,
   csv_path: str,
   sample_size: int = 5,
   *,
   insight_columns: Optional[List[str]] = None,
   score_columns: Optional[List[str]] = None,
   reason_columns: Optional[List[str]] = None,
   seed: Optional[int] = None,
   section_title: str = "DIRECTOR-APPROVED STYLE EXAMPLES",
   context_description: str = "Use these for style and quality. Do not copy verbatim."
) -> str:
   """
   Legacy wrapper - now redirects to prepend_sampled_insights_to_prompt.
   Score and reason columns are ignored for cleaner prompts.
   """
   return prepend_sampled_insights_to_prompt(
       base_prompt=base_prompt,
       csv_path=csv_path,
       sample_size=sample_size,
       insight_columns=insight_columns,
       seed=seed,
       section_title=section_title,
   )







