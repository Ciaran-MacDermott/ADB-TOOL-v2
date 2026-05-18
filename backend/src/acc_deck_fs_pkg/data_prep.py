#!/usr/bin/env python3
"""
NPD Data Preparation Module
General-purpose function for filtering, grouping, and shaping
merged DataFrames into chart-ready views.
"""

import re
import pandas as pd
from typing import List, Dict, Tuple, Union
from acc_deck_pkg.yoy_transformers import excel_round

# ============================================================================
# METRIC DISPLAY CONFIGURATION
# ============================================================================

# Raw metric name → chart display label
METRIC_DISPLAY_NAMES = {
    'units': 'Traffic',
    'dollars': 'Dollars',
    'asp': 'Average Eater Check',
}

# X-axis ordering on charts
METRIC_ORDER = ['Traffic', 'Dollars', 'Average Eater Check']

# ============================================================================
# LABEL MATCHING — normalization + aliases
# ============================================================================

# Known semantic equivalents across markets (both directions are listed).
# These are tried in order after exact + normalized matching both fail.
# Also used for short display-name → full level2 mappings (e.g. 'Retail' → 'Retail Foodservice').
LABEL_ALIASES: Dict[str, List[str]] = {
    # Daypart names
    'Dinner':    ['Supper'],
    'Supper':    ['Dinner'],
    'P.M. Snack': ['PM Snack', 'Afternoon Snack'],
    'PM Snack':   ['P.M. Snack', 'Afternoon Snack'],
    # Short display names for CA segment chart
    'Total Commercial': ['Total Commercial Foodservice'],
    'Retail':           ['Retail Foodservice'],
    # US segment chart — "Fast Casual Restaurants" is the deck-display label
    # for the API's "Fast Casual" segment.
    'Fast Casual Restaurants': ['Fast Casual'],
}


def _normalize_label(s: str) -> str:
    """
    Normalize a display label for fuzzy matching.

    Steps:
        1. Lowercase.
        2. Remove dots entirely so abbreviations collapse ('P.M.' → 'pm').
        3. Replace hyphens/underscores with spaces ('Carry-Out' → 'carry out').
        4. Collapse multiple spaces.

    Examples:
        'P.M. Snack' → 'pm snack'    matches 'PM Snack' → 'pm snack'
        'Carry-Out'  → 'carry out'   matches 'Carry Out' → 'carry out'
    """
    s = s.lower()
    s = re.sub(r'\.', '', s)        # Remove dots (P.M. → pm, not p m)
    s = re.sub(r'[\-_]', ' ', s)   # Hyphens/underscores → space
    return re.sub(r'\s+', ' ', s).strip()


def _find_level2(df: pd.DataFrame, label: str) -> pd.DataFrame:
    """
    Locate rows whose level2 value matches *label* with progressive fallback.

    Resolution order:
        1. Exact match.
        2. Normalized match  — handles punctuation/hyphen variants
                               ('P.M. Snack' ↔ 'PM Snack', 'Carry-Out' ↔ 'Carry Out').
        3. Alias matching    — handles semantic variants ('Dinner' ↔ 'Supper').
           For prefixed labels like 'FSR Dinner', the prefix is preserved and
           the alias is applied to the item part ('FSR Supper' is tried).
           Both exact and normalized forms of each alias are tried.
        4. Warn and return an empty DataFrame.

    Args:
        df:    DataFrame to search (should already be filtered to the
               target year/quarter so messages are concise).
        label: The requested level2 label (e.g. 'QSR P.M. Snack').

    Returns:
        Matching rows, or an empty DataFrame if nothing found.
    """
    # 1. Exact
    exact = df[df['level2'] == label]
    if not exact.empty:
        return exact

    # Pre-build normalised map once
    norm_map = {v: _normalize_label(v) for v in df['level2'].unique()}

    # 2. Normalized
    target_norm = _normalize_label(label)
    for raw_val, norm_val in norm_map.items():
        if norm_val == target_norm:
            print(f"  Note: '{label}' matched as '{raw_val}' (normalized)")
            return df[df['level2'] == raw_val]

    # 3. Alias-based matching.
    # Two strategies tried in order:
    #   a) Full-label alias — for display names like 'Total Commercial' → 'Total Commercial Foodservice'
    #   b) Prefix+item alias — for prefixed labels like 'FSR Dinner' → 'FSR Supper'
    #      (split on first space: prefix='FSR', item='Dinner', alias='Supper' → 'FSR Supper')
    parts = label.split(' ', 1)
    prefix, item_part = (parts[0], parts[1]) if len(parts) == 2 else ('', label)

    # Strategy a: treat the whole label as the alias key (handles multi-word display names)
    for alias in LABEL_ALIASES.get(label, []):
        alias_exact = df[df['level2'] == alias]
        if not alias_exact.empty:
            print(f"  Note: '{label}' matched as '{alias}' (alias)")
            return alias_exact
        alias_norm = _normalize_label(alias)
        for raw_val, norm_val in norm_map.items():
            if norm_val == alias_norm:
                print(f"  Note: '{label}' matched as '{raw_val}' (alias + normalized)")
                return df[df['level2'] == raw_val]

    # Strategy b: treat item_part as the alias key, re-apply original prefix
    for alias in LABEL_ALIASES.get(item_part, []):
        candidate = f"{prefix} {alias}".strip()

        alias_exact = df[df['level2'] == candidate]
        if not alias_exact.empty:
            print(f"  Note: '{label}' matched as '{candidate}' (prefix-item alias)")
            return alias_exact

        alias_norm = _normalize_label(candidate)
        for raw_val, norm_val in norm_map.items():
            if norm_val == alias_norm:
                print(f"  Note: '{label}' matched as '{raw_val}' (prefix-item alias + normalized)")
                return df[df['level2'] == raw_val]

    # 4. Nothing found
    available = sorted(df['level2'].unique().tolist())
    print(f"  WARNING: '{label}' not found in data. Available level2 values: {available}")
    return pd.DataFrame()

# level2 → food/drink classification (for food-bev slide).
# 'f' = food, 'd' = drink.
# All known level2 values from US, Canada, and Australia are mapped here.
# Unmapped categories are silently dropped by build_food_bev_chart_df, so
# keep this list complete and add new entries as the NPD taxonomy evolves.
FOOD_DRINK_MAP = {
    # ── Food ──────────────────────────────────────────────────────────────────
    'All Other Appetizers/Side Dishes': 'f',
    'Asian Appetizers': 'f',
    'Bacon/Breakfast Sausage': 'f',
    'Bagel': 'f',
    'Baked Goods (total)': 'f',
    'Beef Burgers': 'f',
    'Breakfast Sandwiches': 'f',
    'Breakfast Sandwiches Wraps / Burritos': 'f',
    'Burgers (total)': 'f',
    'Chicken (total)': 'f',
    'Chicken Sandwiches': 'f',
    'Chicken Wings': 'f',
    'Deli Sandwiches': 'f',
    'Desserts/Sweet Baked Goods': 'f',
    'Donut': 'f',
    'French Fries': 'f',
    'Fried Appetizers': 'f',
    'Fried/Grilled Chicken': 'f',
    'Hash Browns/Home Fries': 'f',
    'Hot Dogs/Sausages/BLTs': 'f',
    'Main Dish Salad': 'f',
    'Mexican': 'f',
    'Muffin': 'f',
    'Nuggets/Strips': 'f',
    'Other Baked Goods': 'f',
    'Other Chicken/Turkey': 'f',
    'Other Sandwiches': 'f',
    'Other Side Dish / Appetizer': 'f',
    'Pizza': 'f',
    'Salads': 'f',
    'Salty Snacks': 'f',
    'Seafood': 'f',
    'Soup': 'f',
    'Veggie Sandwich/Burger': 'f',
    'World Cuisine': 'f',
    # Australia-specific food
    'Baked Goods': 'f',
    'Beef': 'f',
    'Breakfast Foods': 'f',
    'Burger': 'f',
    'Chips/french Fries': 'f',
    'Desserts/Snacks': 'f',
    'Fish': 'f',
    'Sandwich/Wrap': 'f',
    'Total Potato': 'f',
    # ── Drinks ────────────────────────────────────────────────────────────────
    'All Other Drinks': 'd',
    'Carbonated Soft Drinks': 'd',
    'Coffee (total)': 'd',
    'Diet CSD': 'd',
    'Frozen Sweets': 'd',
    'Frozen Sweets/Shakes': 'd',
    'Frozen/Slushy Soft Drinks': 'd',
    'Hot Specialty Coffee': 'd',
    'Hot Tea': 'd',
    'Iced Tea': 'd',
    'Iced/Frozen/Slushy Coffee': 'd',
    'Lemonade': 'd',
    'Regular CSD': 'd',
    'Regular Coffee': 'd',
    # Australia-specific drinks
    'Carbonated Soft Drink': 'd',   # AU uses singular (vs US 'Carbonated Soft Drinks')
    'Cold Coffee/Dairy Drink': 'd',
    'Hot Drink': 'd',
}


def prepare_data(
    df: pd.DataFrame,
    *,
    groupby: List[str] | None = None,
    filters: Dict[str, object] | None = None,
    columns: List[str] | None = None,
    agg: Dict[str, str] | None = None,
    sort_by: List[str] | None = None,
    ascending: Union[bool, List[bool]] = True,
) -> pd.DataFrame:
    """
    Filter, group, and shape a merged DataFrame for charting or analysis.

    Args:
        df: Source DataFrame (typically from load_and_merge_data).
        groupby: Columns to group by (e.g. ['level1', 'year']).
        filters: Row filters as {column: value_or_list}.
                 Single value  -> equality match.
                 List of values -> .isin() match.
        columns: Subset of columns to include in the output.
                 When used with groupby, these are selected *after* aggregation.
        agg: Aggregation dict (e.g. {'dollars_forecast': 'sum'}).
             Required when groupby is provided.
        sort_by: Columns to sort the result by.
        ascending: Sort direction (single bool or list matching sort_by).

    Returns:
        Prepared DataFrame.
    """
    result = df.copy()

    # 1. Apply filters
    if filters:
        for col, value in filters.items():
            if col not in result.columns:
                raise KeyError(f"Filter column '{col}' not found in DataFrame")
            if isinstance(value, list):
                result = result[result[col].isin(value)]
            else:
                result = result[result[col] == value]

    # 2. Group + aggregate
    if groupby:
        if agg is None:
            raise ValueError("agg dict is required when groupby is provided")
        result = result.groupby(groupby, as_index=False).agg(agg)

    # 3. Select columns
    if columns:
        available = [c for c in columns if c in result.columns]
        result = result[available]

    # 4. Sort
    if sort_by:
        valid_sort = [c for c in sort_by if c in result.columns]
        if valid_sort:
            result = result.sort_values(valid_sort, ascending=ascending).reset_index(drop=True)

    return result


# ============================================================================
# CHART DATAFRAME BUILDERS
# ============================================================================

def build_total_chart_df(
    df: pd.DataFrame,
    input_year: int,
    input_quarter: int,
    metrics: List[str] | None = None,
    display_names: Dict[str, str] | None = None,
    chart_label: str = "Total Restaurants",
    total_level2: str = "Total Restaurants",
) -> pd.DataFrame:
    """
    Build a tidy DataFrame for the Total chart.

    Filters to level2 == total_level2 for the target year/quarter,
    then reshapes into the (metric, f_or_a, YoY) format expected by
    ppt_builder._create_clustered_chart.

    Args:
        df: Merged DataFrame from load_and_merge_data.
        input_year: Reporting year.
        input_quarter: Reporting quarter (1-4).
        metrics: Raw metric names (default: ['units', 'dollars', 'asp']).
        display_names: Mapping of raw metric name → chart label.
        chart_label: Name set on df.columns.name (used as chart header).
        total_level2: The level2 value that represents the market-level total
                      (default 'Total Restaurants'; override per market in CHART_CONFIG).

    Returns:
        Tidy DataFrame with columns [metric, f_or_a, YoY].
    """
    if metrics is None:
        metrics = ['units', 'dollars', 'asp']
    if display_names is None:
        display_names = METRIC_DISPLAY_NAMES

    filtered = prepare_data(
        df,
        filters={
            'level2': total_level2,
            'year': input_year,
            'quarter': input_quarter,
        },
    )

    if filtered.empty:
        available = sorted(df['level2'].unique().tolist()) if 'level2' in df.columns else []
        raise ValueError(
            f"No data found for level2='{total_level2}' in Q{input_quarter} {input_year}.\n"
            f"Available level2 values: {available}"
        )

    rows = []
    for metric in metrics:
        label = display_names.get(metric, metric)
        yoy_fc = f'yoy_{metric}_forecast'
        yoy_ac = f'yoy_{metric}_actual'

        fc_val = filtered[yoy_fc].mean() if yoy_fc in filtered.columns else 0.0
        ac_val = filtered[yoy_ac].mean() if yoy_ac in filtered.columns else 0.0

        rows.append({'metric': label, 'f_or_a': 'Forecast', 'YoY': excel_round(fc_val, 1)})
        rows.append({'metric': label, 'f_or_a': 'Actual', 'YoY': excel_round(ac_val, 1)})

    result = pd.DataFrame(rows)
    result.columns.name = chart_label
    return result


def build_segment_chart_df(
    df: pd.DataFrame,
    input_year: int,
    input_quarter: int,
    categories: List[str],
    metric: str = 'units',
    display_names: Dict[str, str] | None = None,
    chart_label: str = "",
) -> pd.DataFrame:
    """
    Build a tidy DataFrame comparing Forecast vs Actual YoY% for a single
    metric across multiple level2 categories.

    X-axis = category names, series = Forecast / Actual.

    Args:
        df: Merged DataFrame from load_and_merge_data.
        input_year: Reporting year.
        input_quarter: Reporting quarter (1-4).
        categories: level2 values to include (also controls x-axis order).
        metric: Raw metric name (e.g. 'units', 'dollars', 'asp').
        display_names: Optional rename for metric (unused on axis, used in chart_label).
        chart_label: Name set on df.columns.name (used as chart header).

    Returns:
        Tidy DataFrame with columns [metric, f_or_a, YoY].
        'metric' column holds the category names.
    """
    if display_names is None:
        display_names = METRIC_DISPLAY_NAMES

    # Filter broadly to year/quarter only — _find_level2 handles individual
    # label matching with normalization + alias fallback.
    filtered = prepare_data(
        df,
        filters={
            'year': input_year,
            'quarter': input_quarter,
        },
    )

    if filtered.empty:
        raise ValueError(
            f"No data for Q{input_quarter} {input_year}"
        )

    yoy_fc = f'yoy_{metric}_forecast'
    yoy_ac = f'yoy_{metric}_actual'

    rows = []
    for cat in categories:
        cat_data = _find_level2(filtered, cat)
        fc_val = cat_data[yoy_fc].mean() if not cat_data.empty and yoy_fc in cat_data.columns else 0.0
        ac_val = cat_data[yoy_ac].mean() if not cat_data.empty and yoy_ac in cat_data.columns else 0.0

        rows.append({'metric': cat, 'f_or_a': 'Forecast', 'YoY': excel_round(fc_val, 1)})
        rows.append({'metric': cat, 'f_or_a': 'Actual', 'YoY': excel_round(ac_val, 1)})

    result = pd.DataFrame(rows)
    result.columns.name = chart_label
    return result


def build_prefix_split_chart_dfs(
    df: pd.DataFrame,
    input_year: int,
    input_quarter: int,
    prefix_map: Dict[str, str],
    items: Union[List[str], Dict[str, List[str]]],
    metric: str = 'units',
) -> List[pd.DataFrame]:
    """
    Build multiple tidy DataFrames by splitting level2 values on a prefix.

    For example, level2 values like 'QSR Dinner', 'FSR Dinner' are split
    into separate DataFrames per prefix, with the prefix stripped for display.

    Args:
        df: Merged DataFrame from load_and_merge_data.
        input_year: Reporting year.
        input_quarter: Reporting quarter (1-4).
        prefix_map: {prefix: chart_label} e.g. {'QSR': 'Quick Service Restaurants'}.
                    Iteration order controls chart order on the slide.
        items: Either a shared list (same items for every prefix) or a dict
               keyed by prefix with per-prefix item lists.
               e.g. ['Morning Meal', 'Lunch']
               e.g. {'QSR': ['On-Premises', 'Carry-Out'], 'FSR': ['On-Premises']}
        metric: Raw metric name (default 'units' = Traffic).

    Returns:
        List of tidy DataFrames (one per prefix), each with columns
        [metric, f_or_a, YoY].  df.columns.name set to the chart label.
    """
    # Resolve per-prefix item lists
    if isinstance(items, list):
        items_by_prefix = {pfx: items for pfx in prefix_map}
    else:
        items_by_prefix = items

    # Filter broadly to year/quarter — do NOT pre-filter to specific level2 values
    # so that _find_level2 can use normalization and alias fallback on the full set.
    filtered = prepare_data(
        df,
        filters={
            'year': input_year,
            'quarter': input_quarter,
        },
    )

    if filtered.empty:
        raise ValueError(
            f"No data for Q{input_quarter} {input_year}"
        )

    yoy_fc = f'yoy_{metric}_forecast'
    yoy_ac = f'yoy_{metric}_actual'

    chart_dfs = []
    for prefix, chart_label in prefix_map.items():
        rows = []
        for item in items_by_prefix[prefix]:
            level2_val = f"{prefix} {item}"
            cat_data = _find_level2(filtered, level2_val)
            fc_val = cat_data[yoy_fc].mean() if not cat_data.empty and yoy_fc in cat_data.columns else 0.0
            ac_val = cat_data[yoy_ac].mean() if not cat_data.empty and yoy_ac in cat_data.columns else 0.0

            rows.append({'metric': item, 'f_or_a': 'Forecast', 'YoY': excel_round(fc_val, 1)})
            rows.append({'metric': item, 'f_or_a': 'Actual', 'YoY': excel_round(ac_val, 1)})

        result = pd.DataFrame(rows)
        result.columns.name = chart_label
        chart_dfs.append(result)

    return chart_dfs


def build_food_bev_chart_df(
    df: pd.DataFrame,
    input_year: int,
    input_quarter: int,
    top_food: int = 5,
    top_drink: int = 3,
    metric: str = 'units',
    chart_label: str = "",
    food_drink_map: Dict[str, str] | None = None,
) -> Tuple[pd.DataFrame, List[str]]:
    """
    Build a tidy DataFrame for the Food & Beverage slide.

    Ranks level2 categories within level1=='food-bev' by actual servings
    volume, takes the top N food items and top M drink items, and returns
    a single chart DataFrame with food items first then drinks.

    Args:
        df: Merged DataFrame from load_and_merge_data.
        input_year: Reporting year.
        input_quarter: Reporting quarter (1-4).
        top_food: Number of top food items to include.
        top_drink: Number of top drink items to include.
        metric: Raw metric name for YoY% (default 'units' = Traffic/Servings).
        chart_label: Name set on df.columns.name (used as chart header).
        food_drink_map: {level2: 'f'|'d'} mapping. Defaults to FOOD_DRINK_MAP.

    Returns:
        Tuple of:
          - Tidy DataFrame with columns [metric, f_or_a, YoY].
            'metric' column holds the level2 category names.
          - ordered_categories: list of category names in chart order
            (food items first, then drink items).
    """
    if food_drink_map is None:
        food_drink_map = FOOD_DRINK_MAP

    # Filter to food-bev level1 and target quarter/year
    filtered = prepare_data(
        df,
        filters={
            'level1': 'food-bev',
            'year': input_year,
            'quarter': input_quarter,
        },
    )

    if filtered.empty:
        raise ValueError(
            f"No food-bev data for Q{input_quarter} {input_year}"
        )

    # Apply food/drink classification
    filtered = filtered.copy()
    filtered['fd_type'] = filtered['level2'].map(food_drink_map)
    # Drop unmapped categories (e.g. Total Restaurants)
    filtered = filtered.dropna(subset=['fd_type'])

    # Rank by actual servings volume (descending)
    volume_col = f'{metric}_actual'
    if volume_col not in filtered.columns:
        raise KeyError(f"Column '{volume_col}' not found — check metrics list")

    ranked = filtered.sort_values(volume_col, ascending=False)

    # Top N food + top M drink
    top_foods = ranked[ranked['fd_type'] == 'f'].head(top_food)['level2'].tolist()
    top_drinks = ranked[ranked['fd_type'] == 'd'].head(top_drink)['level2'].tolist()
    ordered_categories = top_foods + top_drinks

    # Build tidy chart DataFrame
    yoy_fc = f'yoy_{metric}_forecast'
    yoy_ac = f'yoy_{metric}_actual'

    rows = []
    for cat in ordered_categories:
        cat_data = filtered[filtered['level2'] == cat]
        fc_val = cat_data[yoy_fc].mean() if not cat_data.empty and yoy_fc in cat_data.columns else 0.0
        ac_val = cat_data[yoy_ac].mean() if not cat_data.empty and yoy_ac in cat_data.columns else 0.0

        rows.append({'metric': cat, 'f_or_a': 'Forecast', 'YoY': excel_round(fc_val, 1)})
        rows.append({'metric': cat, 'f_or_a': 'Actual', 'YoY': excel_round(ac_val, 1)})

    result = pd.DataFrame(rows)
    result.columns.name = chart_label
    return result, ordered_categories
