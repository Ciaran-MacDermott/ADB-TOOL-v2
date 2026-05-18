#!/usr/bin/env python3
"""
data_analysis.py
NPD Data Analysis Module — Merging, YoY Calculations, and Variance Analysis

Handles the core data pipeline for foodservice forecast accuracy analysis.
Takes raw forecast and actuals CSVs exported by dashboard_extract.py, aligns
column naming between forecast (predictions) and actuals (real performance),
then calculates Year-over-Year percentage changes and variance columns.

Data Flow:
    forecast_full.csv + actuals_full.csv
        -> load_and_merge_data()   : merge on shared keys, calc YoY%, add variance
        -> make_total_table()      : aggregate to level1 totals for the reporting quarter
        -> [chart builders in data_prep.py consume the merged output]

Key Design Decisions:
    - YoY is calculated as pct_change(periods=4) because data is quarterly.
    - excel_round() from acc_deck_pkg is used throughout for Excel-compatible rounding,
      ensuring the numbers in the deck match what analysts see in Excel.
    - Variance = Actual - Forecast (positive means actuals exceeded forecast).
    - Column renaming strategy: each metric gets a _forecast / _actual suffix after
      the merge so both sources can coexist in one DataFrame without collision.
"""

import pandas as pd
from typing import List
from acc_deck_pkg.yoy_transformers import excel_round

# ============================================================================
# DATA PROCESSING CONFIGURATION
# ============================================================================

DATA_CONFIG = {
    'columns_to_drop': [],              # Columns to remove before processing (if any)
    'rename_columns': {                 # Map API column names to foodservice terminology
        'units': 'traffic_servings',    #   "units" in NPD API = restaurant visits/servings
        'asp': 'avg_eater_check'        #   "asp" in NPD API = average eater check (per-visit $)
    },
    'decimal_places': 2,                # Rounding precision for Excel compatibility
    'metrics_to_analyze': ['traffic_servings', 'dollars', 'avg_eater_check']
}


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def split_yyyyq(df: pd.DataFrame) -> pd.DataFrame:
    """
    Split the yyyyq integer column into separate year and quarter columns.

    The NPD API returns a composite column 'yyyyq' where the last digit is the
    quarter and the preceding digits form the year (e.g. 20254 -> year=2025, quarter=4).

    Args:
        df: DataFrame containing a 'yyyyq' column with integer values.

    Returns:
        Copy of the DataFrame with 'year' and 'quarter' columns added.
    """
    df = df.copy()
    df['year'] = df['yyyyq'] // 10
    df['quarter'] = df['yyyyq'] % 10
    return df


def process_dataframe(df: pd.DataFrame, env_name: str) -> pd.DataFrame:
    """
    Apply standard transformations to a raw DataFrame from the NPD API.

    Processing steps (in order):
        1. Excel-round numeric columns (dollars, units, asp) for consistency
        2. Drop any columns listed in DATA_CONFIG['columns_to_drop']
        3. Rename columns to foodservice terminology (units -> traffic_servings, etc.)
        4. Split yyyyq into year and quarter
        5. Tag rows with the source environment name

    Args:
        df: Raw DataFrame from the NPD API (forecast or actuals).
        env_name: Environment label (e.g. 'prod', 'qa') added as a 'source' column.

    Returns:
        Processed copy of the DataFrame with renamed columns and added fields.
    """
    df = df.copy()
    
    # Clean up numeric columns (before renaming) — Excel-style rounding
    if 'dollars' in df.columns:
        df['dollars'] = excel_round(df['dollars'], decimals=DATA_CONFIG['decimal_places'])
    if 'units' in df.columns:
        df['units'] = excel_round(df['units'], decimals=DATA_CONFIG['decimal_places'])
    if 'asp' in df.columns:
        df['asp'] = excel_round(df['asp'], decimals=DATA_CONFIG['decimal_places'])

    # Drop columns (if any specified)
    if DATA_CONFIG['columns_to_drop']:
        df = df.drop(columns=DATA_CONFIG['columns_to_drop'], errors='ignore')

    # Rename columns: units → traffic_servings, asp → avg_eater_check
    df = df.rename(columns=DATA_CONFIG['rename_columns'])

    # Split yyyyq into year and quarter
    df = split_yyyyq(df)

    # Add source label
    df['source'] = env_name

    return df


def calculate_yoy_growth(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate Year-over-Year percentage growth for traffic servings.

    Uses pct_change(periods=4) because data is quarterly: comparing Q4 2025
    against Q4 2024 means looking back 4 rows within the same level2 group.
    Result is multiplied by 100 to express as a percentage.

    Args:
        df: DataFrame with 'level2', 'traffic_servings', and a time column
            ('yyyyq' or 'yyyy') for sorting.

    Returns:
        Copy of the DataFrame with a 'yoy_percent_growth' column appended.
    """
    df = df.copy()
    
    # Check what columns we have for sorting
    sort_cols = ['level2']
    if 'yyyy' in df.columns:
        sort_cols.append('yyyy')
    if 'yyyyq' in df.columns:
        sort_cols.append('yyyyq')

    df = df.sort_values(sort_cols).reset_index(drop=True)

    # YoY growth: compare same quarter from previous year (4 quarters back)
    df['yoy_percent_growth'] = (
        df.groupby('level2')['traffic_servings']
        .pct_change(periods=4) * 100  # 4 quarters = 1 year
    )
    df['yoy_percent_growth'] = excel_round(df['yoy_percent_growth'], decimals=DATA_CONFIG['decimal_places'])
    return df


def filter_quarters(df: pd.DataFrame, quarters: List[int]) -> pd.DataFrame:
    """
    Filter a DataFrame to only include rows matching the given yyyyq values.

    Args:
        df: DataFrame with a 'yyyyq' column (integer, e.g. 20254).
        quarters: List of yyyyq values to keep (e.g. [20244, 20254]).

    Returns:
        Filtered and sorted copy of the DataFrame.
    """
    df = df.copy()
    filtered = df[df['yyyyq'].isin(quarters)]
    return filtered.sort_values(['level1', 'level2', 'yyyyq']).reset_index(drop=True)


# ============================================================================
# MERGING FUNCTIONS
# ============================================================================

def load_and_merge_data(
    forecast_path: str = None,
    actuals_path: str = None,
    metrics: List[str] = None,
    *,
    df_forecast: pd.DataFrame = None,
    df_actuals: pd.DataFrame = None,
) -> pd.DataFrame:
    """
    Merge forecast and actuals data and return a single aligned DataFrame.

    Accepts either file paths (CSV) or pre-loaded DataFrames. When DataFrames
    are supplied directly they are used as-is, skipping CSV I/O entirely — this
    is the preferred path when data has just been fetched from the API.

    Merge workflow:
        1. Load / receive both sources and split yyyyq into year/quarter
        2. Calculate YoY% per metric on each source independently (before merge)
        3. Rename columns with _forecast / _actual suffixes to avoid collision
        4. Inner-merge on shared keys (project, year, quarter, yyyyq, level1, level2)
        5. Calculate variance columns: actual minus forecast for both raw and YoY%

    Args:
        forecast_path: Path to forecast CSV (used only when df_forecast is None).
        actuals_path:  Path to actuals CSV  (used only when df_actuals is None).
        metrics:       Metric column names to merge (default: ['traffic_servings']).
        df_forecast:   Pre-loaded forecast DataFrame (takes priority over forecast_path).
        df_actuals:    Pre-loaded actuals DataFrame  (takes priority over actuals_path).

    Returns:
        Merged DataFrame with columns for each metric's forecast, actual,
        YoY forecast, YoY actual, raw variance, and YoY variance.
    """
    if metrics is None:
        metrics = ['traffic_servings']

    print("\n" + "=" * 60)
    print("LOADING AND MERGING DATA")
    print("=" * 60)

    # Use provided DataFrames if available, otherwise read from CSV
    if df_forecast is not None:
        df_forecast = df_forecast.copy()
        print(f"\nForecast data: {len(df_forecast)} rows (in-memory)")
    else:
        print(f"\nLoading forecast from: {forecast_path}")
        df_forecast = pd.read_csv(forecast_path)
        print(f"  Loaded {len(df_forecast)} rows")

    if df_actuals is not None:
        df_actuals = df_actuals.copy()
        print(f"Actuals data:  {len(df_actuals)} rows (in-memory)")
    else:
        print(f"\nLoading actuals from: {actuals_path}")
        df_actuals = pd.read_csv(actuals_path)
        print(f"  Loaded {len(df_actuals)} rows")

    # Split yyyyq into year and quarter for both
    df_forecast = split_yyyyq(df_forecast)
    df_actuals = split_yyyyq(df_actuals)

    # Calculate YoY% per metric on each source before merging
    group_keys = ['project', 'level1', 'level2']
    for src_df, label in [(df_forecast, 'forecast'), (df_actuals, 'actuals')]:
        src_df.sort_values(group_keys + ['yyyyq'], inplace=True)
        for metric in metrics:
            if metric in src_df.columns:
                src_df[f'yoy_{metric}'] = excel_round(
                    src_df.groupby(group_keys)[metric]
                    .pct_change(periods=4) * 100,  # 4 quarters = 1 year
                    decimals=2
                )
    print(f"  Calculated YoY% for {metrics}")

    # Build rename mappings so forecast and actuals columns don't collide after merge.
    # Each metric gets a _forecast / _actual suffix, e.g. dollars -> dollars_forecast.
    forecast_rename = {'source': 'source_forecast'}
    actuals_rename = {'source': 'source_actual'}

    for metric in metrics:
        if metric in df_forecast.columns:
            forecast_rename[metric] = f"{metric}_forecast"
        if f'yoy_{metric}' in df_forecast.columns:
            forecast_rename[f'yoy_{metric}'] = f"yoy_{metric}_forecast"

    for metric in metrics:
        if metric in df_actuals.columns:
            actuals_rename[metric] = f"{metric}_actual"
        if f'yoy_{metric}' in df_actuals.columns:
            actuals_rename[f'yoy_{metric}'] = f"yoy_{metric}_actual"

    df_forecast = df_forecast.rename(columns=forecast_rename)
    df_actuals = df_actuals.rename(columns=actuals_rename)

    # Define merge keys
    merge_keys = ['project', 'year', 'quarter', 'yyyyq', 'level1', 'level2']

    # Collect columns to keep
    forecast_cols = merge_keys.copy()
    actuals_cols = merge_keys.copy()

    for metric in metrics:
        for col in [f"{metric}_forecast", f"yoy_{metric}_forecast"]:
            if col in df_forecast.columns:
                forecast_cols.append(col)
        for col in [f"{metric}_actual", f"yoy_{metric}_actual"]:
            if col in df_actuals.columns:
                actuals_cols.append(col)

    df_forecast_merge = df_forecast[forecast_cols].copy()
    df_actuals_merge = df_actuals[actuals_cols].copy()

    # Merge
    print(f"\nMerging forecast and actuals on {metrics}...")
    df_merged = pd.merge(
        df_forecast_merge,
        df_actuals_merge,
        on=merge_keys,
        how='inner'
    )
    print(f"  Merged successfully: {len(df_merged)} rows")

    # Calculate variance columns: positive variance means actuals exceeded forecast.
    # Two types: raw variance (absolute difference) and YoY variance (difference in % growth).
    for metric in metrics:
        fc_col = f"{metric}_forecast"
        ac_col = f"{metric}_actual"
        yoy_fc = f"yoy_{metric}_forecast"
        yoy_ac = f"yoy_{metric}_actual"

        # Raw variance: actual - forecast
        if fc_col in df_merged.columns and ac_col in df_merged.columns:
            df_merged[f'{metric}_variance'] = excel_round(
                df_merged[ac_col] - df_merged[fc_col], decimals=2
            )

        # YoY variance: actual YoY% - forecast YoY%
        if yoy_fc in df_merged.columns and yoy_ac in df_merged.columns:
            df_merged[f'yoy_{metric}_variance'] = excel_round(
                df_merged[yoy_ac] - df_merged[yoy_fc], decimals=2
            )

    print(f"  Added variance columns")

    # Sort
    df_merged = df_merged.sort_values(['project', 'level1', 'level2', 'year', 'quarter']).reset_index(drop=True)

    return df_merged


# ============================================================================
# AGGREGATION FUNCTIONS
# ============================================================================

def make_total_table(
    df: pd.DataFrame,
    input_year: int,
    input_quarter: int,
    metrics: List[str] = None
) -> pd.DataFrame:
    """
    Create a total-level summary table grouped by level1 (e.g. restaurant type).

    Filters to level2 == 'Total Restaurants' first to avoid double-counting
    sub-categories in the rollup. Then groups by year, sums metric columns, and
    calculates YoY% from the summed values (not from pre-computed YoY% rows,
    which would be incorrect for aggregated totals).

    Only the reporting year's row is kept in the final output. If the input_year
    is not present in the data (e.g. future quarter), that level1 is silently
    skipped rather than raising an error.

    Args:
        df: Merged DataFrame from load_and_merge_data().
        input_year: The reporting year (e.g. 2025).
        input_quarter: The reporting quarter (1-4).
        metrics: List of metric names to aggregate (default: ['traffic_servings']).

    Returns:
        DataFrame with one row per level1, containing forecast, actual, YoY%,
        and variance columns for each metric. Returns empty DataFrame if no
        matching data is found.
    """
    if metrics is None:
        metrics = ['traffic_servings']

    # Filter to level2 == 'Total Restaurants' first
    df_filtered = df[df['level2'] == 'Total Restaurants'].copy()

    if df_filtered.empty:
        print("  Warning: No data found for level2 == 'Total Restaurants'")
        return pd.DataFrame()

    # Filter to the specified quarter only (keep all years for YoY calculation)
    df_filtered = df_filtered[df_filtered['quarter'] == input_quarter].copy()

    if df_filtered.empty:
        print(f"  Warning: No data found for Q{input_quarter}")
        return pd.DataFrame()

    results = []

    for level1_name in df_filtered['level1'].unique():
        # Filter to this level1
        level1_df = df_filtered[df_filtered['level1'] == level1_name]

        # Build list of metric columns
        metric_cols = []
        for metric in metrics:
            forecast_col = f"{metric}_forecast"
            actual_col = f"{metric}_actual"
            if forecast_col in level1_df.columns:
                metric_cols.append(forecast_col)
            if actual_col in level1_df.columns:
                metric_cols.append(actual_col)

        if not metric_cols:
            continue

        # Group by year and sum
        tot = (
            level1_df
            .groupby("year")[metric_cols]
            .sum()
            .sort_index()
        )

        # Calculate YoY (pct_change from previous year) × 100
        for metric in metrics:
            forecast_col = f"{metric}_forecast"
            actual_col = f"{metric}_actual"

            if forecast_col in tot.columns:
                tot[f'yoy_{metric}_forecast'] = excel_round(tot[forecast_col].pct_change(1) * 100, decimals=2)

            if actual_col in tot.columns:
                tot[f'yoy_{metric}_actual'] = excel_round(tot[actual_col].pct_change(1) * 100, decimals=2)

        # Keep only the reporting year
        if input_year not in tot.index:
            continue

        year_row = tot.loc[input_year]
        row_data = {'level1': level1_name}

        # Extract all values for this year
        for metric in metrics:
            forecast_col = f"{metric}_forecast"
            actual_col = f"{metric}_actual"
            yoy_forecast_col = f"yoy_{metric}_forecast"
            yoy_actual_col = f"yoy_{metric}_actual"

            if forecast_col in year_row.index:
                row_data[forecast_col] = excel_round(year_row[forecast_col], decimals=2)

            if actual_col in year_row.index:
                row_data[actual_col] = excel_round(year_row[actual_col], decimals=2)

            if yoy_forecast_col in year_row.index:
                row_data[yoy_forecast_col] = excel_round(year_row[yoy_forecast_col], decimals=2)

            if yoy_actual_col in year_row.index:
                row_data[yoy_actual_col] = excel_round(year_row[yoy_actual_col], decimals=2)

            # Calculate YoY variance (Actual YoY% - Forecast YoY%)
            if yoy_forecast_col in year_row.index and yoy_actual_col in year_row.index:
                yoy_variance = year_row[yoy_actual_col] - year_row[yoy_forecast_col]
                row_data[f'yoy_{metric}_variance'] = excel_round(yoy_variance, decimals=2)

        results.append(row_data)

    if not results:
        return pd.DataFrame()

    df_result = pd.DataFrame(results)

    # Reorder columns for better readability
    ordered_cols = ['level1']
    for metric in metrics:
        metric_cols = [
            f'{metric}_forecast',
            f'{metric}_actual',
            f'yoy_{metric}_forecast',
            f'yoy_{metric}_actual',
            f'yoy_{metric}_variance'
        ]
        ordered_cols.extend([c for c in metric_cols if c in df_result.columns])

    return df_result[[c for c in ordered_cols if c in df_result.columns]]




if __name__ == "__main__":
    df = load_and_merge_data("forecast_full.csv",
                             "actuals_full.csv",
                             ["dollars", "units", "asp"])
    print(df.columns)