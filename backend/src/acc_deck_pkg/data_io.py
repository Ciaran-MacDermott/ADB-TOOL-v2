""""
data_io.py - UPDATED (Quarter-first, Month optional)
===================================================


Load, normalize, and merge Actuals + Forecast data for the Forecast vs Actuals pipeline.


Key updates vs prior version
----------------------------
- Month is now OPTIONAL.
- If month is missing, we will use (year + quarter) for time alignment.
- Merge keys are now quarterly: ['year','quarter','level1','level2'].
- If quarter is given as a label like "2022 Q1" / "2022Q1" / "Q1 2022", we parse it.
- We still emit a 'month' column for compatibility (quarter-start date) even when not provided.


Configurability
---------------
Reads mappings via cfg["column_map"] (config_loader normalizes column_mapping -> column_map).


Expected time inputs (any one of these):
1) month column (parseable date) -> derives year/quarter
2) year + quarter columns -> quarter can be numeric (1-4) or a label like "2022 Q1"
"""


import re
import time
import datetime
import pandas as pd
import os




# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_DEFAULT_MAP = {
    "actual":   {"level1": "project", "level2": "highlevelrollup",
                 "units": "units_actual", "dollars": "dollars_actual"},
    "forecast": {"level1": "project", "level2": "highlevelrollup",
                 "units": "units_final", "dollars": "dollars_final"},
    "time":     {"month": "month", "quarter": "quarter", "year": "year"},
}




def _get_map(cfg: dict, branch: str, key: str) -> str:
    """Fetch a column name from CONFIG['column_map'], falling back to defaults."""
    try:
        return str(cfg.get("column_map", {}).get(branch, {}).get(key) or _DEFAULT_MAP[branch][key])
    except Exception:
        return _DEFAULT_MAP[branch][key]




def _lower_trim_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase + strip column names for robust matching."""
    df = df.copy()
    df.columns = df.columns.str.lower().str.strip()
    return df




def _safe_read_csv(path: str) -> None:
    """Best-effort read for the 'month file' (kept for compatibility)."""
    try:
        _ = pd.read_csv(path)
    except Exception:
        pass




def _detect_file_type(path: str) -> str:
    """Return 'excel' or 'csv' based on file extension."""
    ext = path.lower().rsplit('.', 1)[-1] if '.' in path else ''
    if ext in ('xlsx', 'xls'):
        return 'excel'
    elif ext == 'csv':
        return 'csv'
    return 'unknown'




def _load_file(path: str, sheet_name: str = None) -> pd.DataFrame:
    """
    Load Excel or CSV file intelligently with smart sheet detection.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Data file not found: {path}")


    file_type = _detect_file_type(path)


    if file_type == 'csv':
        return pd.read_csv(path)


    if file_type == 'excel':
        xl = pd.ExcelFile(path)
        available_sheets = xl.sheet_names
        filename = os.path.basename(path)

        # Single sheet: always use it regardless of sheet_name config
        if len(available_sheets) == 1:
            return pd.read_excel(path, sheet_name=available_sheets[0])

        # Multiple sheets: try specified sheet, fall back gracefully
        if sheet_name:
            for sheet in available_sheets:
                if sheet.upper() == sheet_name.upper():
                    return pd.read_excel(path, sheet_name=sheet)
            print(f"  Sheet '{sheet_name}' not found, using '{available_sheets[0]}'")
            return pd.read_excel(path, sheet_name=available_sheets[0])

        # No sheet specified for multi-sheet file - warn and use first
        print(f"  Multi-sheet file, using '{available_sheets[0]}'")
        return pd.read_excel(path, sheet_name=available_sheets[0])


    raise ValueError(f"Unsupported file type: {path}. Expected .xlsx, .xls, or .csv")




def _clean_month_column(series: pd.Series, source_name: str = "data") -> pd.Series:
    """
    Robustly parse a month/date column handling multiple formats.
    Raises if >10% fail to parse (or all fail).
    """
    result = pd.Series(index=series.index, dtype='datetime64[ns]')
    failed_indices = []
    failed_samples = []


    for idx, val in series.items():
        parsed = None


        if pd.isna(val):
            result[idx] = pd.NaT
            continue


        if isinstance(val, (pd.Timestamp, datetime.datetime)):
            parsed = pd.Timestamp(val)


        elif isinstance(val, (int, float)) and not isinstance(val, bool):
            try:
                if 1 <= val <= 100000:
                    parsed = pd.Timestamp('1899-12-30') + pd.Timedelta(days=int(val))
                else:
                    parsed = pd.to_datetime(val, errors='coerce')
            except Exception:
                pass


        elif isinstance(val, str):
            val_clean = val.strip()
            if not val_clean:
                result[idx] = pd.NaT
                continue


            formats_to_try = [
                '%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%d.%m.%Y',
                '%m-%d-%Y', '%d-%m-%Y', '%Y/%m/%d',
                '%m/%d/%y', '%d/%m/%y', '%d.%m.%y',
                '%b %d, %Y', '%d %b %Y', '%B %d, %Y', '%d %B %Y',
            ]


            for fmt in formats_to_try:
                try:
                    parsed = pd.to_datetime(val_clean, format=fmt)
                    break
                except (ValueError, TypeError):
                    continue


            if parsed is None:
                try:
                    parsed = pd.to_datetime(val_clean, dayfirst=True, errors='coerce')
                    if pd.isna(parsed):
                        parsed = pd.to_datetime(val_clean, dayfirst=False, errors='coerce')
                except Exception:
                    pass


        if parsed is not None and not pd.isna(parsed):
            result[idx] = parsed
        else:
            result[idx] = pd.NaT
            failed_indices.append(idx)
            if len(failed_samples) < 5:
                failed_samples.append(repr(val))


    total = len(series)
    failed_count = len(failed_indices)
    success_count = total - failed_count


    if success_count == 0 and total > 0:
        raise ValueError(
            f"Date parsing failed for {source_name}: Could not parse ANY dates in the month column. "
            f"Sample values: {failed_samples[:5]}."
        )


    if failed_count > 0:
        failure_pct = (failed_count / total) * 100
        if failure_pct > 10:
            raise ValueError(
                f"Date parsing failed for {source_name}: {failed_count}/{total} dates ({failure_pct:.1f}%) "
                f"could not be parsed. Sample failures: {failed_samples}."
            )
        else:
            print(
                f"Warning ({source_name}): {failed_count} dates could not be parsed and will be excluded. "
                f"Samples: {failed_samples}"
            )


    return result




def _extract_quarter_number(q_series: pd.Series) -> pd.Series:
    """
    Normalize quarter input into numeric 1-4.


    Accepts:
    - 1,2,3,4
    - 'Q1', 'q2'
    - '2022 Q1', '2022Q1', 'Q1 2022'
    """
    s = q_series.astype(str).str.upper().str.strip()


    # Try to extract Q[1-4]
    q_from_label = s.str.extract(r"Q\s*([1-4])", expand=False)
    q_num = pd.to_numeric(q_from_label, errors="coerce")


    # If not label, try numeric directly
    q_direct = pd.to_numeric(s, errors="coerce")


    out = q_num.fillna(q_direct)
    return out




def _quarter_start_month(year: pd.Series, quarter: pd.Series) -> pd.Series:
    """Quarter-start date as a 'month' proxy (YYYY-(1|4|7|10)-01)."""
    return pd.to_datetime(
        dict(
            year=year,
            month=(quarter.sub(1).mul(3).add(1)),
            day=1
        ),
        errors="coerce"
    )




# ---------------------------------------------------------------------------
# Primary file loading interface
# ---------------------------------------------------------------------------


def load_data(cfg: dict) -> pd.DataFrame:
    """
    Load actuals + forecast, align columns, and return merged DataFrame.


    Output columns:
      ['month','quarter','year','level1','level2',
       'units_latest','dollars_latest','units_prevwave','dollars_prevwave']
    """
    t0 = time.time()


    # 1) Load files (best-effort read of 'month_file' for parity with old code)
    if cfg.get("month_file"):
        _safe_read_csv(cfg["month_file"])


    # 2) Load actual and forecast files
    actual_path = cfg["paths"]["actual"]
    forecast_path = cfg["paths"]["forecast"]

    actual_sheet = cfg.get("sheet_name_actual")
    df_actual = _load_file(actual_path, sheet_name=actual_sheet)

    forecast_sheet = cfg.get("sheet_name_forecast")
    df_forecast = _load_file(forecast_path, sheet_name=forecast_sheet)


    # 3) Normalize column names (lowercase + trim)
    df_actual = _lower_trim_cols(df_actual)
    df_forecast = _lower_trim_cols(df_forecast)


    # 4) Resolve source column names from CONFIG (with safe defaults)
    a_lvl1 = _get_map(cfg, "actual", "level1")
    a_lvl2 = _get_map(cfg, "actual", "level2")
    a_units = _get_map(cfg, "actual", "units")
    a_dols = _get_map(cfg, "actual", "dollars")


    f_lvl1 = _get_map(cfg, "forecast", "level1")
    f_lvl2 = _get_map(cfg, "forecast", "level2")
    f_units = _get_map(cfg, "forecast", "units")
    f_dols = _get_map(cfg, "forecast", "dollars")


    month_col = _get_map(cfg, "time", "month")
    quarter_col = _get_map(cfg, "time", "quarter")
    year_col = _get_map(cfg, "time", "year")


    # 5) Per-source renames to the standard schema
    df_actual.rename(columns={
        a_lvl1: "level1",
        a_lvl2: "level2",
        a_units: "units_latest",
        a_dols: "dollars_latest",
    }, inplace=True)


    df_forecast.rename(columns={
        f_lvl1: "level1",
        f_lvl2: "level2",
        f_units: "units_prevwave",
        f_dols: "dollars_prevwave",
    }, inplace=True)


    # 6) Optional: if level1 sometimes comes as "X: Y" and you only want "Y"
    for d in (df_actual, df_forecast):
        if "level1" in d.columns:
            d["level1"] = d["level1"].astype(str).str.split(": ").str[-1]


    # 7) Ensure time fields exist and derive year/quarter (month optional)
    for d, source_name in [(df_actual, "actuals"), (df_forecast, "forecast")]:
        # Detect columns (note: columns already lower+trimmed)
        has_month = (month_col.lower().strip() in d.columns)
        has_year = (year_col.lower().strip() in d.columns)
        has_quarter = (quarter_col.lower().strip() in d.columns)


        if has_month:
            if month_col.lower().strip() != "month":
                d.rename(columns={month_col.lower().strip(): "month"}, inplace=True)


            d["month"] = _clean_month_column(d["month"], source_name=source_name)
            d["year"] = d["month"].dt.year
            d["quarter"] = d["month"].dt.quarter


            # Drop failed month parses
            d.dropna(subset=["month"], inplace=True)


        else:
            # Month missing -> require year+quarter
            if not (has_year and has_quarter):
                raise KeyError(
                    f"Missing time fields in {source_name}. Provide '{month_col}' OR "
                    f"('{year_col}' and '{quarter_col}')."
                )


            # Normalize names to 'year'/'quarter'
            if year_col.lower().strip() != "year":
                d.rename(columns={year_col.lower().strip(): "year"}, inplace=True)
            if quarter_col.lower().strip() != "quarter":
                d.rename(columns={quarter_col.lower().strip(): "quarter"}, inplace=True)


            d["year"] = pd.to_numeric(d["year"], errors="coerce")
            d["quarter"] = _extract_quarter_number(d["quarter"])


            # Basic validation
            bad_time = d["year"].isna() | d["quarter"].isna()
            if bad_time.any():
                bad_n = int(bad_time.sum())
                sample = d.loc[bad_time, ["year", "quarter"]].head(5).to_dict(orient="records")
                raise ValueError(
                    f"{source_name}: {bad_n} rows have unparseable year/quarter. "
                    f"Sample: {sample}"
                )


            # Create quarter-start month for compatibility
            d["month"] = _quarter_start_month(d["year"], d["quarter"])


    # 8) Merge on quarterly keys (month removed)
    key_cols = ["year", "quarter", "level1", "level2"]


    missing_keys_actual = [k for k in key_cols if k not in df_actual.columns]
    missing_keys_forecast = [k for k in key_cols if k not in df_forecast.columns]
    if missing_keys_actual:
        raise KeyError(f"Actuals file missing merge keys: {missing_keys_actual}")
    if missing_keys_forecast:
        raise KeyError(f"Forecast file missing merge keys: {missing_keys_forecast}")


    df_actual_agg = (
        df_actual
        .groupby(key_cols, as_index=False)[["units_latest", "dollars_latest"]]
        .sum()
    )

    df_forecast_agg = (
        df_forecast
        .groupby(key_cols, as_index=False)[["units_prevwave", "dollars_prevwave"]]
        .sum()
    )

    df_combined = pd.merge(df_actual_agg, df_forecast_agg, on=key_cols, how="inner")


    # Recreate 'month' in the combined output (quarter-start)
    df_combined["month"] = _quarter_start_month(df_combined["year"], df_combined["quarter"])


    # 9) Select output columns
    use_cols = [
        "month", "quarter", "year", "level1", "level2",
        "units_latest", "dollars_latest", "units_prevwave", "dollars_prevwave",
    ]
    available = [c for c in use_cols if c in df_combined.columns]


    out = df_combined[available].copy()


    print(f"✓ Data loaded and merged in {time.time() - t0:.2f}s ({len(out)} rows)")
    return out




# ---------------------------------------------------------------------------
# API-based data loading
# ---------------------------------------------------------------------------


def load_data_from_api(
    prod_session,
    qa_session,
    industry_id: str,
    level1_filter: str = None,
    analysis_level: str = "level2",
) -> pd.DataFrame:
    """
    Fetch forecast (prod) + actuals (qa) from the NPD API and return a
    merged DataFrame in the same schema as load_data().

    Parameters
    ----------
    prod_session : requests.Session
        Authenticated session for Production environment (forecast data).
    qa_session : requests.Session
        Authenticated session for QA environment (actuals data).
    industry_id : str
        NPD industry ID (e.g. 'food-service').
    level1_filter : str, optional
        If set, only rows where level1 == level1_filter are kept.
    analysis_level : str, default "level2"
        Which level column to use as the category dimension.  The chosen
        column is renamed to "level2" in the output so the rest of the
        pipeline is unchanged.

    Returns
    -------
    pd.DataFrame
        Columns: month, quarter, year, level1, level2,
                 units_latest, dollars_latest, units_prevwave, dollars_prevwave
    """
    import concurrent.futures
    from acc_deck_pkg.api_extractor import get_industry_forecast

    t0 = time.time()

    print(f"  Fetching forecast (prod) + actuals (qa) in parallel for '{industry_id}'...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        prod_f = pool.submit(get_industry_forecast, prod_session, 'prod', industry_id, 'yyyyq')
        qa_f   = pool.submit(get_industry_forecast, qa_session,   'qa',   industry_id, 'yyyyq')
        df_forecast = prod_f.result()
        df_actuals  = qa_f.result()

    print(f"  {len(df_forecast):,} forecast rows, {len(df_actuals):,} actuals rows")

    # Apply level1 filter before any further processing
    if level1_filter:
        df_forecast = df_forecast[df_forecast["level1"] == level1_filter].copy()
        df_actuals  = df_actuals[df_actuals["level1"] == level1_filter].copy()
        print(f"  After level1 filter '{level1_filter}': {len(df_forecast):,} forecast, {len(df_actuals):,} actuals rows")

    # Validate analysis_level column exists
    if analysis_level not in df_forecast.columns:
        available = [c for c in df_forecast.columns if c.startswith("level")]
        raise ValueError(
            f"analysis_level={analysis_level!r} not found in data. "
            f"Available level columns: {available}"
        )

    # Derive year + quarter from yyyyq integer (e.g. 20254 → year=2025, quarter=4)
    for df in (df_forecast, df_actuals):
        df["year"]    = df["yyyyq"] // 10
        df["quarter"] = df["yyyyq"] % 10

    merge_keys = ["year", "quarter", "level1", analysis_level]

    # Diagnostic: show wave structure
    print(f"  Forecast waves: {sorted(df_forecast['wave'].unique())}")
    print(f"  Actuals  waves: {sorted(df_actuals['wave'].unique())}")
    print(f"  Forecast rows per merge key (sample): {df_forecast.groupby(merge_keys).size().describe().to_dict()}")

    forecast_slim = (
        df_forecast.groupby(merge_keys, as_index=False)[["units", "dollars"]].sum()
        .rename(columns={"units": "units_prevwave", "dollars": "dollars_prevwave"})
    )
    actuals_slim = (
        df_actuals.groupby(merge_keys, as_index=False)[["units", "dollars"]].sum()
        .rename(columns={"units": "units_latest", "dollars": "dollars_latest"})
    )
    print(f"  After groupby sum — forecast keys: {len(forecast_slim)}, actuals keys: {len(actuals_slim)}")

    merged = pd.merge(forecast_slim, actuals_slim, on=merge_keys, how="inner")

    # Rename chosen analysis level to "level2" so the rest of the pipeline is unchanged
    if analysis_level != "level2":
        merged = merged.rename(columns={analysis_level: "level2"})
        print(f"  Renamed '{analysis_level}' → 'level2' for pipeline compatibility")

    # Synthesise quarter-start month: Q1→Jan, Q2→Apr, Q3→Jul, Q4→Oct
    merged["month"] = pd.to_datetime({
        "year":  merged["year"],
        "month": (merged["quarter"] - 1) * 3 + 1,
        "day":   1,
    })

    out = merged[[
        "month", "quarter", "year", "level1", "level2",
        "units_latest", "dollars_latest", "units_prevwave", "dollars_prevwave",
    ]].copy()

    print(f"✓ API data loaded and merged in {time.time() - t0:.2f}s ({len(out)} rows)")
    return out


# ---------------------------------------------------------------------------
# Excel export helper
# ---------------------------------------------------------------------------


def to_excel_multi(dfs: dict, path: str) -> None:
    """
    Write multiple DataFrames to a single .xlsx (one sheet per key).
    - Cleans sheet names to satisfy Excel's constraints (≤31 chars; no []:*?/\\).
    - De-duplicates sheet names by adding numeric suffixes.
    - Freezes header row and applies a simple auto-width based on first 100 rows.
    """
    def clean(name: str) -> str:
        name = re.sub(r'[:\\/*?\[\]]', "_", str(name))
        return name[:31] if len(name) > 31 else name


    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        used = set()
        for key, df in dfs.items():
            if not isinstance(df, pd.DataFrame):
                continue


            base = clean(key)
            name = base
            i = 1
            while name in used:
                suffix = f"_{i}"
                name = (base[: (31 - len(suffix))] + suffix) if len(base) + len(suffix) > 31 else base + suffix
                i += 1
            used.add(name)


            df.to_excel(writer, sheet_name=name, index=False)


            ws = writer.sheets[name]
            ws.freeze_panes = "A2"
            for col_idx, col_name in enumerate(df.columns, start=1):
                sample_vals = df[col_name].head(100).fillna("")
                max_len = max((len(str(col_name)), *(len(str(v)) for v in sample_vals)), default=0)
                ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(
                    max(12, max_len + 2), 60
                )









