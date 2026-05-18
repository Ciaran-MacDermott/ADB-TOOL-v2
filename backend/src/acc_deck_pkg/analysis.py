"""
analysis.py - UPDATED
=====================

What this module does
---------------------
1) Builds "topline" tables for category selection (wide YoY format).
2) Ranks categories by actual dollar sales volume for ordering in the deck.
3) Creates total (industry-level) tables for charting.
4) Merges multiple category analysis tables for LLM prompt generation.

Key Changes
-----------
- Removed hits/misses logic
- Added get_categories_by_sales_volume() to rank categories by actual dollar sales
- Updated build_topline to include sales volume calculation
"""

import pandas as pd
from acc_deck_pkg.yoy_transformers import yoy, yoy_total_from_l2_sum, excel_round


def build_topline(
    df: pd.DataFrame,
    input_year: int,
    input_quarter: int,
) -> pd.DataFrame:
    """
    Build a wide YoY table for all Level-2 categories, including actual dollar sales volume.

    Parameters
    ----------
    df : pd.DataFrame
        Merged dataset (actuals + forecast).
    input_year : int
        Target year.
    input_quarter : int
        Target quarter (1-4).

    Returns
    -------
    pd.DataFrame
        Wide table with columns like 'yoy_units_actual_qtr', 'yoy_dollars_actual_qtr', etc.
        Plus 'actual_dollars_volume' for sorting.
        Index = Level-2 category names.
    """
    if "level2" not in df.columns:
        raise KeyError("Column 'level2' required for topline analysis.")

    cats = sorted(df["level2"].dropna().unique())
    frames = []

    for cat in cats:
        try:
            wide = yoy(
                df,
                input_year=input_year,
                input_quarter=input_quarter,
                cat=cat,
                total=False,
                topline=True,  # Returns wide format
            )
            if not wide.empty:
                # Calculate actual dollar sales volume for this category/quarter
                cat_data = df[
                    (df["level2"] == cat) &
                    (df["year"] == input_year) &
                    (df["quarter"] == input_quarter)
                ].copy()

                actual_dollars_volume = cat_data["dollars_latest"].sum()
                wide["actual_dollars_volume"] = actual_dollars_volume

                frames.append(wide)
        except Exception as e:
            print(f"Warning: Skipped '{cat}': {e}")

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, axis=0)
    return combined


def get_categories_by_sales_volume(
    topline: pd.DataFrame,
    ascending: bool = False
) -> list:
    """
    Return list of categories ordered by actual dollar sales volume.

    Parameters
    ----------
    topline : pd.DataFrame
        Output from build_topline() with 'actual_dollars_volume' column.
    ascending : bool
        If True, sort ascending (smallest first). Default False (largest first).

    Returns
    -------
    list
        Category names sorted by sales volume.
    """
    if topline.empty or "actual_dollars_volume" not in topline.columns:
        return []

    sorted_df = topline.sort_values("actual_dollars_volume", ascending=ascending)
    return sorted_df.index.tolist()


def pick_hits_misses(topline: pd.DataFrame) -> tuple:
    """
    DEPRECATED: Legacy function kept for compatibility.
    Returns empty lists since we're using sales volume ordering instead.
    
    Parameters
    ----------
    topline : pd.DataFrame
        Wide YoY topline table.

    Returns
    -------
    tuple
        ([], []) - empty lists for hits and misses
    """
    return [], []


def make_tot_table(
    df: pd.DataFrame,
    input_year: int,
    input_quarter: int,
    level1_label: str,
) -> list:
    """
    Create total (industry-level) table for charting.

    Parameters
    ----------
    df : pd.DataFrame
        Merged dataset.
    input_year : int
        Target year.
    input_quarter : int
        Target quarter.
    level1_label : str
        Industry label for chart title (e.g., "US Tech").

    Returns
    -------
    list
        Single-element list containing the tidy total table.
    """
    tot = yoy(
        df,
        input_year=input_year,
        input_quarter=input_quarter,
        total=True,
        topline=False,
    )

    if not tot.empty:
        tot.columns.name = f"Total {level1_label}"

    return [tot]


def merge_analysis_tables(*table_groups) -> pd.DataFrame:
    """
    Merge multiple category analysis tables into a single wide DataFrame for LLM prompts.

    Each table group is a list of DataFrames (from yoy with topline=False).
    Returns a wide table with one row per category and columns:
        ['category', 'Forecast_ASP', 'Actual_ASP', 'Diff (%)_ASP',
         'Forecast_Units', 'Actual_Units', 'Diff (%)_Units',
         'Forecast_Dollars', 'Actual_Dollars', 'Diff (%)_Dollars']

    Parameters
    ----------
    *table_groups : list of pd.DataFrame
        Variable number of lists, each containing category DataFrames.

    Returns
    -------
    pd.DataFrame
        Collapsed wide table ready for LLM insight generation.
    """
    all_dfs = []
    for group in table_groups:
        if group:
            all_dfs.extend(group)

    if not all_dfs:
        return pd.DataFrame()

    rows = []
    for tidy in all_dfs:
        if tidy.empty:
            continue

        cat_name = tidy.columns.name or "Unknown"

        # Pivot: metric × f_or_a → YoY value
        pv = tidy.pivot(index="metric", columns="f_or_a", values="YoY")

        # Flatten column names from MultiIndex if needed
        if isinstance(pv.columns, pd.MultiIndex):
            pv.columns = ['_'.join(col).strip() for col in pv.columns.values]
        
        # Reset index to make metric a column
        pv = pv.reset_index()

        # Build row dictionary
        row_dict = {"category": cat_name}
        
        # Extract values for each metric/f_or_a combination
        for _, metric_row in pv.iterrows():
            metric = metric_row.get("metric", "")
            for col in pv.columns:
                if col != "metric":
                    # col should be like "Forecast" or "Actual"
                    key = f"{col}_{metric}"
                    row_dict[key] = metric_row[col]

        rows.append(row_dict)

    if not rows:
        return pd.DataFrame()

    df_out = pd.DataFrame(rows)

    # Standardize column names for LLM
    rename_map = {}
    for col in df_out.columns:
        if col == "category":
            continue
        # Handle both "Forecast_Asp" and "Forecast_ASP" formats
        new_col = col.replace("_Asp", "_ASP")
        if new_col != col:
            rename_map[col] = new_col

    if rename_map:
        df_out = df_out.rename(columns=rename_map)

    # Calculate Diff (%) columns
    for metric in ["ASP", "Units", "Dollars"]:
        f_col = f"Forecast_{metric}"
        a_col = f"Actual_{metric}"
        diff_col = f"Diff (%)_{metric}"

        if f_col in df_out.columns and a_col in df_out.columns:
            df_out[diff_col] = df_out[a_col] - df_out[f_col]

    # Reorder columns to desired format
    desired_order = [
        "category",
        "Forecast_ASP", "Actual_ASP", "Diff (%)_ASP",
        "Forecast_Units", "Actual_Units", "Diff (%)_Units",
        "Forecast_Dollars", "Actual_Dollars", "Diff (%)_Dollars",
    ]
    available = [c for c in desired_order if c in df_out.columns]

    return df_out[available]


def pivot_total_table(df_tot) -> pd.DataFrame:
    """
    Pivot a tidy total table to wide format for LLM total subheader generation.
    NOW ROUNDS TO 1 DECIMAL PLACE FOR CLEANER LLM CONSUMPTION.
    """
    if isinstance(df_tot, list):
        if not df_tot or not isinstance(df_tot[0], pd.DataFrame):
            return pd.DataFrame()
        df = df_tot[0].copy()
    elif isinstance(df_tot, pd.DataFrame):
        df = df_tot.copy()
    else:
        return pd.DataFrame()

    if df.empty or not {"metric", "f_or_a", "YoY"}.issubset(df.columns):
        return pd.DataFrame()

    # Pivot to wide
    pv = df.pivot(index="metric", columns="f_or_a", values="YoY")

    # Add Diff column
    if "Forecast" in pv.columns and "Actual" in pv.columns:
        pv["Diff (%)"] = pv["Actual"] - pv["Forecast"]

    # ROUND ALL VALUES TO 1 DECIMAL PLACE (Excel-style rounding)
    pv = excel_round(pv, decimals=1)

    return pv
