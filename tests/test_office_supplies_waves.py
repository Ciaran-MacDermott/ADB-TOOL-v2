"""
tests/test_office_supplies_waves.py
===================================
Diagnose wave structure for office-supplies and verify load_data_from_api
produces correct (non-duplicated) merged data.

Two modes
---------
1. Unit tests (pytest)  — use synthetic mock data, no network required.
2. Live integration     — run directly to hit the real API:
       python tests/test_office_supplies_waves.py

The live mode prompts for NPD credentials, fetches raw wave data, prints
a full wave/column breakdown, then runs the same assertions the unit tests use.
"""

import sys
import getpass
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd

# Ensure ADB root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acc_deck_pkg.data_io import load_data_from_api


# ─────────────────────────────────────────────────────────────────────────────
# Helpers shared by unit tests and live mode
# ─────────────────────────────────────────────────────────────────────────────

def _check_waves(label: str, df: pd.DataFrame):
    """Print a concise wave/column/src breakdown for one raw API DataFrame."""
    print(f"\n  [{label}]")
    print(f"  Total rows   : {len(df):,}")
    print(f"  Columns      : {list(df.columns)}")
    if "wave" in df.columns:
        wave_counts = df["wave"].value_counts().sort_index()
        print(f"  Waves ({len(wave_counts)} total):")
        for w, n in wave_counts.items():
            print(f"    wave={w!r:30s}  rows={n:,}")
    else:
        print("  WARNING: no 'wave' column found")
    if "src" in df.columns:
        src_counts = df["src"].value_counts()
        print(f"  src values:")
        for s, n in src_counts.items():
            print(f"    src={s!r:30s}  rows={n:,}")
    else:
        print("  WARNING: no 'src' column — cannot split forecast vs actuals")
    if "yyyyq" in df.columns:
        print(f"  yyyyq range  : {df['yyyyq'].min()} → {df['yyyyq'].max()}")
    if "level1" in df.columns:
        print(f"  level1 unique: {sorted(df['level1'].dropna().unique())}")
    if "level2" in df.columns:
        lvl2 = df["level2"].dropna().unique()
        preview = list(lvl2[:8])
        suffix  = f" … ({len(lvl2)} total)" if len(lvl2) > 8 else ""
        print(f"  level2 sample: {preview}{suffix}")


def _build_wave_df(
    wave_id: str,
    label: str,
    rows: list[dict],
) -> pd.DataFrame:
    """Build a DataFrame that mimics a single waveObject table after get_industry_forecast."""
    df = pd.DataFrame(rows)
    df["wave"]   = wave_id
    df["label"]  = label
    df["filter"] = None
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Synthetic data — two waves on each side
# ─────────────────────────────────────────────────────────────────────────────

_PERIODS = [
    {"yyyyq": 20251, "level1": "Office Supplies", "level2": "Pens"},
    {"yyyyq": 20251, "level1": "Office Supplies", "level2": "Paper"},
    {"yyyyq": 20252, "level1": "Office Supplies", "level2": "Pens"},
    {"yyyyq": 20252, "level1": "Office Supplies", "level2": "Paper"},
]


def _make_forecast_df() -> pd.DataFrame:
    """Two forecast waves — wave_A is older, wave_B is the current wave."""
    wave_a_rows = [
        {**p, "units": 100 + i * 10, "dollars": 1000 + i * 100}
        for i, p in enumerate(_PERIODS)
    ]
    wave_b_rows = [
        {**p, "units": 110 + i * 10, "dollars": 1100 + i * 100}
        for i, p in enumerate(_PERIODS)
    ]
    return pd.concat([
        _build_wave_df("wave_A", "Old Forecast", wave_a_rows),
        _build_wave_df("wave_B", "Current Forecast", wave_b_rows),
    ], ignore_index=True)


def _make_actuals_df() -> pd.DataFrame:
    """One actuals wave."""
    actuals_rows = [
        {**p, "units": 105 + i * 10, "dollars": 1050 + i * 100}
        for i, p in enumerate(_PERIODS)
    ]
    return _build_wave_df("wave_actual", "Actuals", actuals_rows)


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadDataFromApiWaves(unittest.TestCase):
    """Verify wave handling in load_data_from_api."""

    def _run(self, df_forecast: pd.DataFrame, df_actuals: pd.DataFrame) -> pd.DataFrame:
        """Patch get_industry_forecast and call load_data_from_api."""
        mock_prod = MagicMock()
        mock_qa   = MagicMock()

        def _side(session, env_key, industry_id, time_gran="yyyyq"):
            return df_forecast if env_key == "prod" else df_actuals

        with patch("acc_deck_pkg.data_io.get_industry_forecast", side_effect=_side):
            return load_data_from_api(mock_prod, mock_qa, "office-supplies")

    # ------------------------------------------------------------------
    def test_single_wave_each_correct_row_count(self):
        """Baseline: 1 forecast wave × 1 actuals wave → exactly 4 merged rows."""
        forecast = _build_wave_df("wave_B", "Current Forecast", [
            {**p, "units": 110, "dollars": 1100} for p in _PERIODS
        ])
        actuals  = _make_actuals_df()

        out = self._run(forecast, actuals)
        self.assertEqual(
            len(out), len(_PERIODS),
            f"Expected {len(_PERIODS)} rows (one per period), got {len(out)}.\n{out}",
        )

    # ------------------------------------------------------------------
    def test_multi_wave_forecast_causes_row_explosion(self):
        """
        KNOWN BUG DEMONSTRATION: 2 forecast waves × 1 actuals wave
        currently produces 8 rows (cartesian product) instead of 4.

        When this test FAILS (AssertionError), the bug is present.
        When it PASSES, load_data_from_api correctly deduplicates waves.
        """
        forecast = _make_forecast_df()   # 2 waves × 4 periods = 8 rows
        actuals  = _make_actuals_df()    # 1 wave  × 4 periods = 4 rows

        out = self._run(forecast, actuals)

        # The correct expectation is 4 rows (one per period).
        # If we get 8, the multi-wave cartesian-product bug is present.
        expected = len(_PERIODS)
        self.assertEqual(
            len(out), expected,
            f"\n{'─'*60}\n"
            f"  WAVE BUG DETECTED!\n"
            f"  Expected {expected} rows (one per period).\n"
            f"  Got      {len(out)} rows — likely a cartesian product of waves.\n"
            f"\n  Breakdown by yyyyq:\n"
            f"{out.groupby(['year','quarter','level2'])[['units_prevwave','units_latest']].first().to_string()}\n"
            f"{'─'*60}",
        )

    # ------------------------------------------------------------------
    def test_no_matching_waves_returns_empty(self):
        """Forecast and actuals with no overlapping periods → empty DataFrame."""
        forecast = _build_wave_df("wave_B", "Current Forecast", [
            {"yyyyq": 20231, "level1": "Office Supplies", "level2": "Pens",
             "units": 50, "dollars": 500},
        ])
        actuals = _build_wave_df("wave_actual", "Actuals", [
            {"yyyyq": 20254, "level1": "Office Supplies", "level2": "Pens",
             "units": 60, "dollars": 600},
        ])

        out = self._run(forecast, actuals)
        self.assertEqual(
            len(out), 0,
            f"Expected empty merge when periods don't overlap, got {len(out)} rows.",
        )

    # ------------------------------------------------------------------
    def test_output_schema(self):
        """Merged output must contain the required columns in the correct order."""
        forecast = _build_wave_df("wave_B", "Current Forecast", [
            {**_PERIODS[0], "units": 110, "dollars": 1100}
        ])
        actuals = _build_wave_df("wave_actual", "Actuals", [
            {**_PERIODS[0], "units": 105, "dollars": 1050}
        ])

        out = self._run(forecast, actuals)
        required = {
            "month", "quarter", "year", "level1", "level2",
            "units_latest", "dollars_latest", "units_prevwave", "dollars_prevwave",
        }
        missing = required - set(out.columns)
        self.assertFalse(
            missing,
            f"Output DataFrame is missing columns: {missing}",
        )

    # ------------------------------------------------------------------
    def test_values_not_inflated_by_multi_wave(self):
        """
        With 2 forecast waves, units_prevwave must equal the wave_B value (110),
        not a sum of both waves (210) or a duplicate-inflated value.
        """
        forecast = _make_forecast_df()   # wave_A=100, wave_B=110 for first period
        actuals  = _make_actuals_df()    # actuals=105

        out = self._run(forecast, actuals)
        if len(out) == 0:
            self.skipTest("Merge returned 0 rows — check wave/period alignment")

        first = out[
            (out["year"] == 2025) & (out["quarter"] == 1) & (out["level2"] == "Pens")
        ]
        if first.empty:
            self.skipTest("Row for 2025-Q1 Pens not found")

        # There should be exactly one row for this period/category
        self.assertEqual(len(first), 1, f"Duplicate rows for same period: {first}")


# ─────────────────────────────────────────────────────────────────────────────
# Live integration mode  (python tests/test_office_supplies_waves.py)
# ─────────────────────────────────────────────────────────────────────────────

def _live_test():
    from acc_deck_pkg.api_extractor import connect, fetch_industries, get_industry_forecast

    SEP = "─" * 70

    print("\n" + "=" * 70)
    print("  NPD API — Office Supplies Wave Diagnostics (live)")
    print("=" * 70)
    print("\nEnter your NPD credentials:")
    username = input("  Username: ").strip()
    password = getpass.getpass("  Password: ").strip()

    # ── Connect ──────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  STEP 1: Connect to PROD + QA in parallel")
    print(SEP)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        pf = pool.submit(connect, username, password, "prod")
        qf = pool.submit(connect, username, password, "qa")
        prod_session = pf.result()
        qa_session   = qf.result()

    if not prod_session:
        print("  FAIL — PROD login failed"); sys.exit(1)
    if not qa_session:
        print("  FAIL — QA login failed");   sys.exit(1)
    print("  PASS — sessions obtained")

    # ── Find office-supplies industry ─────────────────────────────────────────
    print(f"\n{SEP}")
    print("  STEP 2: Fetch industry list + find office-supplies")
    print(SEP)
    industries = fetch_industries(prod_session)
    print(f"  {len(industries)} industries available")

    office_id = next(
        (i["id"] for i in industries if "office" in i["label"].lower() or "office" in i["id"].lower()),
        None,
    )
    if office_id is None:
        print("\n  WARNING: no 'office' industry found.  Available:")
        for ind in industries:
            print(f"    id={ind['id']!r:45s}  label={ind['label']!r}")
        office_id = industries[0]["id"]
        print(f"\n  Falling back to first industry: {office_id!r}")
    else:
        label = next(i["label"] for i in industries if i["id"] == office_id)
        print(f"  Found: id={office_id!r}  label={label!r}")

    # ── Raw API fetch ─────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print(f"  STEP 3: Fetch raw wave data for '{office_id}'")
    print(SEP)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        pf = pool.submit(get_industry_forecast, prod_session, "prod", office_id, "yyyyq")
        qf = pool.submit(get_industry_forecast, qa_session,   "qa",   office_id, "yyyyq")
        df_forecast_raw = pf.result()
        df_actuals_raw  = qf.result()

    _check_waves("PROD (forecast)", df_forecast_raw)
    _check_waves("QA   (actuals)",  df_actuals_raw)

    # ── src split diagnostic ──────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  STEP 4: src column — how forecast vs actuals are split")
    print(SEP)

    for df_raw, env_lbl in [(df_forecast_raw, "PROD"), (df_actuals_raw, "QA")]:
        if "src" not in df_raw.columns:
            print(f"  {env_lbl}: no 'src' column — cannot split forecast vs actuals in this response")
            continue
        src_counts = df_raw["src"].value_counts()
        print(f"\n  {env_lbl} src breakdown:")
        for src_val, n in src_counts.items():
            sub = df_raw[df_raw["src"] == src_val]
            yyyyq_range = f"{sub['yyyyq'].min()} → {sub['yyyyq'].max()}" if "yyyyq" in sub.columns else "n/a"
            print(f"    src={src_val!r:35s}  rows={n:,}  yyyyq={yyyyq_range}")

    # ── level3/level4 multiplicity check ─────────────────────────────────────
    print(f"\n{SEP}")
    print("  STEP 5: level3/level4 — rows per level2 per period")
    print(SEP)

    sample = df_forecast_raw.copy()
    if "yyyyq" in sample.columns:
        sample["_year"]    = sample["yyyyq"] // 10
        sample["_quarter"] = sample["yyyyq"] % 10
    base_keys = [c for c in ["_year", "_quarter", "level1", "level2"] if c in sample.columns]
    if base_keys and "src" in sample.columns:
        for src_val in sample["src"].unique():
            sub = sample[sample["src"] == src_val]
            counts = sub.groupby(base_keys).size()
            multi  = counts[counts > 1]
            max_rows = int(counts.max()) if len(counts) else 0
            print(f"\n  src={src_val!r}: {len(multi)} combos have >1 row (max={max_rows} rows per combo)")
            if not multi.empty:
                print(f"  → level3/level4 sub-rows present — must aggregate before merge")
                sample_sub = sub[sub.set_index(base_keys).index.isin(multi.index)].head(4)
                extra_cols = [c for c in ["level3", "level4", "units", "dollars"] if c in sample_sub.columns]
                print(sample_sub[base_keys + extra_cols].head(6).to_string(index=False))
            else:
                print(f"  → No sub-level rows — merge keys are unique")

    # ── load_data_from_api (live, no mock) ────────────────────────────────────
    print(f"\n{SEP}")
    print("  STEP 6: load_data_from_api — current output")
    print(SEP)

    try:
        out = load_data_from_api(prod_session, qa_session, office_id)
        print(f"\n  Merged rows : {len(out):,}")
        if len(out) > 0:
            print(f"  Columns     : {list(out.columns)}")
            print(f"  Year range  : {out['year'].min()} – {out['year'].max()}")
            dup_check = out.duplicated(subset=["year", "quarter", "level1", "level2"])
            n_dup = dup_check.sum()
            if n_dup:
                print(f"\n  *** {n_dup} DUPLICATE rows on merge keys — cartesian product bug active ***")
                print(out[dup_check][["year", "quarter", "level2",
                                      "units_prevwave", "units_latest"]].head(6).to_string())
            same_pct = (out["units_prevwave"] == out["units_latest"]).mean() * 100
            if same_pct > 90:
                print(f"\n  *** WARNING: {same_pct:.0f}% of rows — units_prevwave == units_latest ***")
                print("  → PROD and QA likely return same data; split must come from 'src' column")
            else:
                print(f"\n  Forecast vs actuals differ in {100 - same_pct:.0f}% of rows — OK")
            print(f"\n  Sample (head 5):")
            print(out.head(5).to_string(index=False))
        else:
            print("  WARNING: merged output is empty — check merge keys and src filtering")
    except Exception as exc:
        import traceback as _tb
        print(f"  FAIL — {exc}")
        _tb.print_exc()

    print(f"\n{'=' * 70}")
    print("  Diagnostics complete")
    print("=" * 70)


if __name__ == "__main__":
    _live_test()
else:
    # pytest discovers and runs the unit test class
    pass
