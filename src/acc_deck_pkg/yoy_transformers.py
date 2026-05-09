"""
transformers.py
===============

What this module does
---------------------
- Exposes a single public transform: `yoy(...)`.
- Converts raw monthly actuals + forecast data into *quarterly* aggregates,
  then computes **year-over-year (YoY) percentage change** for:
    • Units (Forecast, Actual)
    • Dollars (Forecast, Actual)
    • ASP = Dollars / Units (Forecast, Actual)
- Returns either:
    1) A **tidy** table (metric × f_or_a → YoY), for charts and LLMs
    2) A **wide** topline table (when `topline=True`) for category selection

Key concepts
------------
- **f_or_a**: shorthand for *forecast-or-actual* (column values: "Forecast" or "Actual")
- **total**: when True, compute overall totals (all categories). When False,
  subset to a specific Level-2 category passed via `cat`.
- **topline**: when True, return the internal *wide* YoY table (used by selection
  logic in `analysis.build_topline`). When False (default), return the tidy shape
  (metric/f_or_a/YoY) used by charting and LLM prompting.

Input expectations
------------------
Dataframe `df_old` must contain at least:
    - A datetime-like 'month' column (monthly observations)
    - Metric columns for:
        * Actuals (units, dollars)
        * Previous forecast wave (units, dollars)
      Column names are configurable via `var_map` (see DEFAULT_VAR_MAP).

Computation outline
-------------------
1) (Optional) Filter to a single Level-2 category (if `total=False`).
2) Derive `year` and `quarter` from `month`, and *filter to `input_quarter` only*.
3) Aggregate quarterly totals per (year, quarter) for each metric (units/dollars,
   forecast/actual). This produces *_qtr columns.
4) Compute ASP for forecast and actual (ASP = dollars_qtr / units_qtr).
5) For each quarterly series, compute YoY% via `.pct_change()` (current year vs
   prior year) × 100. This yields columns like `yoy_units_actual_qtr`.
6) Keep only the row for `input_year`. If `topline=True`, return this wide table.
   Otherwise, reshape to a tidy long table:
     - `metric` ∈ {'Units','ASP','Dollars'}
     - `f_or_a` ∈ {'Forecast','Actual'}
     - `YoY` in percentage points (float)

Notes / edge cases
------------------
- If `input_year` is not present (e.g., no data in that quarter), we return
  an empty tidy table (or the wide frame, if `topline=True`).
- Division by zero in ASP will propagate NaN/inf; callers should format robustly.
- We preserve the original notebook’s row ordering in the tidy output:
  Units → ASP → Dollars, each as Forecast then Actual.

=========== DEFINITIONS ===========
f_or_a = "forecast or actual" tag used in tidy outputs.
The transform works with a configurable mapping from  input schema to the original notebook’s expected metric names.
"""

from __future__ import annotations
import pandas as pd
import numpy as np
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Dict, Union


def excel_round(value: Union[float, pd.Series, pd.DataFrame], decimals: int = 1) -> Union[float, pd.Series, pd.DataFrame]:
    """
    Round using Excel-style "round half away from zero" (ROUND_HALF_UP).

    This matches Excel's ROUND() function behavior:
    - 1.25 → 1.3 (not 1.2 like Python's banker's rounding)
    - 1.35 → 1.4
    - -1.25 → -1.3

    Args:
        value: A float, pandas Series, or DataFrame to round
        decimals: Number of decimal places (default 1)

    Returns:
        Rounded value(s) matching Excel's rounding behavior
    """
    def _round_scalar(x):
        if pd.isna(x) or np.isinf(x):
            return x
        try:
            # Use Decimal for precise rounding
            d = Decimal(str(float(x)))
            rounded = d.quantize(Decimal(10) ** -decimals, rounding=ROUND_HALF_UP)
            return float(rounded)
        except Exception:
            return x

    if isinstance(value, pd.DataFrame):
        return value.apply(lambda col: col.apply(_round_scalar) if col.dtype in ['float64', 'float32', 'int64', 'int32'] else col)
    elif isinstance(value, pd.Series):
        if value.dtype in ['float64', 'float32', 'int64', 'int32']:
            return value.apply(_round_scalar)
        return value
    else:
        return _round_scalar(value)


# --- mapping from the original notebook names to your current columns ---
# original expected: units_forecast / units_actual / dollars_forecast / dollars_actual
DEFAULT_VAR_MAP: Dict[str, str] = {
    "units_forecast":   "units_prevwave",
    "units_actual":     "units_latest",
    "dollars_forecast": "dollars_prevwave",
    "dollars_actual":   "dollars_latest",
}


def _ensure_time_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure year and quarter columns exist in DataFrame.

    If year/quarter columns already exist (from data_io), use them directly.
    Otherwise, derive from month column for backward compatibility.
    """
    df = df.copy(deep=True)

    # If year/quarter already exist, use them directly
    if "year" in df.columns and "quarter" in df.columns:
        return df

    # Otherwise, derive from month
    if "month" not in df.columns:
        raise KeyError("DataFrame must have 'month' column or both 'year' and 'quarter' columns")

    df["month"] = pd.to_datetime(df["month"], errors="coerce")
    df["year"] = df["month"].dt.year
    df["quarter"] = df["month"].dt.quarter
    return df


def total_quarter_sums(
        df: pd.DataFrame,
        year: int,
        quarter: int,
        var_map: Dict[str, str],
) -> pd.DataFrame:
    """Compute quarterly sums for Units/Dollars/ASP (Forecast and Actual)."""
    df = _ensure_time_columns(df)

    df_q = df[(df["year"] == year) & (df["quarter"] == quarter)].copy()
    if df_q.empty:
        return pd.DataFrame({
            "Year": [year], "Quarter": [quarter],
            "Units_Forecast": [0], "Units_Actual": [0],
            "Dollars_Forecast": [0], "Dollars_Actual": [0],
            "ASP_Forecast": [None], "ASP_Actual": [None],
        })

    # Use var_map to map to actual column names
    uf = var_map["units_forecast"]
    ua = var_map["units_actual"]
    dfc = var_map["dollars_forecast"]
    dac = var_map["dollars_actual"]

    # TOTAL sums
    tot_units_f = df_q[uf].sum()
    tot_units_a = df_q[ua].sum()
    tot_dollars_f = df_q[dfc].sum()
    tot_dollars_a = df_q[dac].sum()

    # ASP (handle divide-by-zero)
    asp_f = tot_dollars_f / tot_units_f if tot_units_f != 0 else None
    asp_a = tot_dollars_a / tot_units_a if tot_units_a != 0 else None

    return pd.DataFrame({
        "Year": [year],
        "Quarter": [quarter],
        "Units_Forecast": [tot_units_f],
        "Units_Actual": [tot_units_a],
        "Dollars_Forecast": [tot_dollars_f],
        "Dollars_Actual": [tot_dollars_a],
        "ASP_Forecast": [asp_f],
        "ASP_Actual": [asp_a],
    })


def compare_totals_two_years(df, year1, year2, quarter, var_map=DEFAULT_VAR_MAP):
    t1 = total_quarter_sums(df, year1, quarter, var_map)
    t2 = total_quarter_sums(df, year2, quarter, var_map)
    return pd.concat([t1, t2], ignore_index=True)



def yoy_total_from_l2_sum(
    df_old: pd.DataFrame,
    *,
    input_year: int,
    input_quarter: int,
    var_map: Dict[str, str] = DEFAULT_VAR_MAP,
) -> pd.DataFrame:
    """
    Compute YoY % for Total Industry by:
    1) Summing quarterly totals at Level-2
    2) Summing those Level-2 totals across all Level-2s
    This mirrors the "sum the grand totals of L2s" approach used in Excel.
    Returns a tidy table with ['metric', 'f_or_a', 'YoY'].
    """
    if "level2" not in df_old.columns:
        raise KeyError("Column 'level2' is required to build Total from L2 sums.")

    # 1) Time derivation & quarter filter
    df = _ensure_time_columns(df_old)
    df = df[df["quarter"] == input_quarter].copy()

    # Expected notebook metric keys (left-hand side)
    original_vars = ["units_forecast", "units_actual", "dollars_forecast", "dollars_actual"]
    metric_cols = {k: var_map[k] for k in original_vars}

    for col in metric_cols.values():
        if col not in df.columns:
            raise KeyError(f"Expected column '{col}' not found in input DataFrame.")


    # 2) First, build quarterly totals per (level2, year)
    #    (this is your "grand total for each L2" per year/quarter)
    l2_qtr = (
        df
        .groupby(["level2", "year"], as_index=False)[list(metric_cols.values())]
        .sum()
    )


    # 3) Now sum those Level-2 totals across all level2s → Total Industry by year
    tot = (
        l2_qtr
        .groupby("year")[list(metric_cols.values())]
        .sum()
        .sort_index()
    )


    # 4) Rename to canonical quarterly names like in `yoy`
    rename_map = {
        metric_cols["units_forecast"]:   "units_forecast_qtr",
        metric_cols["units_actual"]:     "units_actual_qtr",
        metric_cols["dollars_forecast"]: "dollars_forecast_qtr",
        metric_cols["dollars_actual"]:   "dollars_actual_qtr",
    }
    tot = tot.rename(columns=rename_map)


    # 5) Compute ASP from quarterly totals
    tot["asp_forecast"] = tot["dollars_forecast_qtr"] / tot["units_forecast_qtr"]
    tot["asp_actual"]   = tot["dollars_actual_qtr"]   / tot["units_actual_qtr"]


    # 6) Year-over-year % change ×100
    cols_snapshot = tot.columns.to_list()
    for col in cols_snapshot:
        yoy_col = f"yoy_{col}"
        tot[yoy_col] = excel_round(tot[col].pct_change(1) * 100.0, decimals=1)
        tot.drop(columns=col, inplace=True)


    # 7) Keep only the reporting year
    if input_year not in tot.index:
        return pd.DataFrame(columns=["metric", "f_or_a", "YoY"])


    tot = tot.loc[[input_year]]  # keep as DataFrame


    # Label index for downstream titles/headers
    tot.index = pd.Index([f"Q{input_quarter} Forecasts vs. Actuals"], name="Total")


    # 8) Tidy reshape (copying the bottom half of your existing `yoy`)
    col_name = tot.index[0]
    df_t = (
        tot.T.reset_index()
           .rename(columns={"index": "indicator", col_name: "YoY"})
    )
    df_t.columns.name = col_name


    # Parse indicator into metric + f_or_a:
    # 'yoy_units_forecast_qtr' → metric='Units', f_or_a='Forecast'
    df_t["metric"] = df_t["indicator"].str.split("_").str[1].str.title()
    df_t["f_or_a"] = df_t["indicator"].str.split("_").str[2].str.title()
    df_t = df_t.drop(columns="indicator")


    # Preserve original ordering: Units → ASP → Dollars, each Forecast then Actual
    def pick_rows(metric):
        blk = df_t[df_t["metric"].eq(metric)].copy()
        blk["metric"] = blk["metric"].replace({"Asp": "ASP"})
        order = {"Forecast": 0, "Actual": 1}
        blk["__o__"] = blk["f_or_a"].map(order).fillna(99)
        return blk.sort_values("__o__").drop(columns="__o__")


    df_final = pd.concat(
        [pick_rows("Units"), pick_rows("Asp"), pick_rows("Dollars")],
        ignore_index=True,
    )
    return df_final[["metric", "f_or_a", "YoY"]]




def yoy(
    df_old: pd.DataFrame,
    *,
    input_year: int,
    input_quarter: int,
    cat: Optional[str] = None,
    total: bool = True,
    topline: bool = False,
    var_map: Dict[str, str] = DEFAULT_VAR_MAP,
) -> pd.DataFrame:
    """
    Compute YoY % for Units, Dollars, and ASP (Forecast/Actual) for a given quarter.
    Parameters
    ----------
    df_old : pd.DataFrame
        Raw, merged monthly dataset (after `load_data`). Must include:
        'month' (datetime-like), level fields (level2 if `total=False`),
        and metric columns referenced by `var_map`.
    input_year : int
        Year to *report* (YoY compares this year's quarter to prior year's quarter).
    input_quarter : int
        Quarter to analyze (1–4). Only this quarter is used in aggregation.
    cat : str | None
        Level-2 category name when `total=False`. Ignored when `total=True`.
    total : bool
        If True, aggregate across all categories (default).
        If False, filter to Level-2 == `cat` (raises if level2 missing).
    topline : bool
        If True, return the internal *wide* YoY table (used by selection logic).
        If False (default), return tidy long table (metric/f_or_a/YoY).
    var_map : Dict[str,str]
        Mapping from original names → actual column names in `df_old`, e.g.:
            {'units_forecast':'units_prevwave', 'dollars_actual':'dollars_latest', ...}

    Returns
    -------
    pd.DataFrame
        - If `topline=False` (default): tidy table with columns
          ['metric','f_or_a','YoY'] and columns.name set for chart headers.
        - If `topline=True`: the *wide* YoY table with columns like
          'yoy_units_actual_qtr', 'yoy_asp_actual', etc. (used by topline selection).
    Raises KeyError
        If required columns (e.g., 'level2' when total=False, or any `var_map` column) are missing.
    """
    # 1) Category filtering (if not total view)
    if not total:
        if "level2" not in df_old.columns:
            raise KeyError("Column 'level2' is required when total=False (category view).")
        # Use .copy() after boolean indexing to ensure independent DataFrame
        df = df_old[df_old["level2"] == cat].copy()
    else:
        df = df_old.copy(deep=True)

    # 2) Time derivation & quarter filter
    df = _ensure_time_columns(df)
    df = df[df["quarter"] == input_quarter].copy()

    # Expected notebook metric keys (left-hand side)
    original_vars = ["units_forecast", "units_actual", "dollars_forecast", "dollars_actual"]

    # 3) Aggregate to *quarterly totals* per (year, quarter) for each metric
    #    and materialize *_qtr columns to use in YoY pct_change.
    for orig_name in original_vars:
        col = var_map[orig_name]
        if col not in df.columns:
            raise KeyError(f"Expected column '{col}' not found in input DataFrame.")
        new_var = f"{orig_name}_qtr"
        df[new_var] = df.groupby(["year", "quarter"])[col].transform("sum")

    # 4) Collapse to unique (year) rows for this quarter — order by year for pct_change
    qtr_vars = [f"{v}_qtr" for v in original_vars]
    keep_cols = ["year"] + qtr_vars
    df = df[keep_cols].drop_duplicates().set_index("year").sort_index()

    # 5) Compute ASP series from quarterly totals
    df["asp_forecast"] = df["dollars_forecast_qtr"] / df["units_forecast_qtr"]
    df["asp_actual"]   = df["dollars_actual_qtr"]   / df["units_actual_qtr"]

    # 6) Year-over-year % change (this year vs prior year) ×100 for each series
    #    Then drop the raw series, leaving only yoy_* columns.
    cols_snapshot = df.columns.to_list()
    for col in cols_snapshot:
        yoy_col = f"yoy_{col}"
        df[yoy_col] = excel_round(df[col].pct_change(1) * 100.0, decimals=1)
        df.drop(columns=col, inplace=True)

    # 7) Keep only the target reporting year
    if input_year not in df.index:
        # When topline=True, callers expect the wide frame (even if empty);
        # otherwise, return an empty tidy table with the canonical columns.
        return df if topline else pd.DataFrame(columns=["metric", "f_or_a", "YoY"])

    df = df.loc[[input_year]]  # keep as DataFrame to preserve shape

    # 8) Label the single-row index for downstream titles/headers
    if not total:
        df.index = pd.Index([cat], name="Level 2")
    else:
        df.index = pd.Index([f"Q{input_quarter} Forecasts vs. Actuals"], name="Total")

    # 9) Topline mode returns the wide yoy_* table (used by build_topline → selection)
    if topline:
        return df  # wide yoy_* table (percent scale)

    # 10) Tidy reshape for charts/LLM prompts
    # Transpose: columns become 'indicator' (e.g., 'yoy_units_forecast_qtr'),
    # and the single data column is named after the index label.
    col_name = df.index[0]  # single column name after transpose
    df_t = (
        df.T.reset_index()
          .rename(columns={"index": "indicator", col_name: "YoY"})
    )
    df_t.columns.name = col_name

    # Parse indicator into metric + f_or_a:
    #   'yoy_units_forecast_qtr' → metric='Units', f_or_a='Forecast'
    df_t["metric"] = df_t["indicator"].str.split("_").str[1].str.title()
    df_t["f_or_a"] = df_t["indicator"].str.split("_").str[2].str.title()
    df_t = df_t.drop(columns="indicator")

    # Preserve original notebook ordering:
    # Units → ASP → Dollars, each with Forecast first, then Actual
    def pick_rows(metric):
        blk = df_t[df_t["metric"].eq(metric)].copy()
        blk["metric"] = blk["metric"].replace({"Asp": "ASP"})
        order = {"Forecast": 0, "Actual": 1}
        blk["__o__"] = blk["f_or_a"].map(order).fillna(99)
        return blk.sort_values("__o__").drop(columns="__o__")

    df_final = pd.concat([pick_rows("Units"), pick_rows("Asp"), pick_rows("Dollars")], ignore_index=True)
    return df_final[["metric", "f_or_a", "YoY"]]

