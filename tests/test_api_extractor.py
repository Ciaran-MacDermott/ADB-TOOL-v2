"""
tests/test_api_extractor.py
Manual integration test for acc_deck_pkg.api_extractor.

Run from ADB root:
    python tests/test_api_extractor.py

You will be prompted for your NPD credentials.
Each step prints clearly so you can see exactly where a failure occurs.
"""

import sys
import getpass
from pathlib import Path
import requests

# Ensure the ADB root is on sys.path so acc_deck_pkg imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acc_deck_pkg.api_extractor import (
    ENVIRONMENTS,
    connect,
    fetch_industries,
    get_industry_forecast,
)

SEP = "─" * 60


def _header(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def _step(n: int, title: str):
    print(f"\n{SEP}")
    print(f"  STEP {n}: {title}")
    print(SEP)


def main():
    _header("NPD API — Integration Test")

    print("\nEnter your NPD credentials (password is hidden):")
    username = input("  Username: ").strip()
    password = getpass.getpass("  Password: ").strip()

    # ------------------------------------------------------------------
    # Step 1: Login to PROD
    # ------------------------------------------------------------------
    _step(1, "Connect to PROD (Selenium SSO + session)")
    prod_session = connect(username, password, "qa")
    if prod_session is None:
        print("\n  FAIL — prod session is None. Check credentials / Selenium / Chrome.")
        sys.exit(1)
    print("  PASS — prod session obtained")

    # ------------------------------------------------------------------
    # Step 2: Login to QA  [SKIPPED]
    # ------------------------------------------------------------------
    # _step(2, "Connect to QA (Selenium SSO + session)")
    # qa_session = connect(username, password, "qa")

    # ------------------------------------------------------------------
    # Step 3: Fetch ALL industries
    # ------------------------------------------------------------------
    _step(3, "GET /api/ext/industries (prod) — full list")
    try:
        industries = fetch_industries(prod_session)
    except Exception as exc:
        print(f"\n  FAIL — {exc}")
        import traceback; traceback.print_exc()
        sys.exit(1)

    if not industries:
        print("\n  FAIL — empty industry list returned")
        sys.exit(1)

    print(f"\n  PASS — {len(industries)} industries returned:")
    for ind in sorted(industries, key=lambda x: x['label']):
        print(f"    id={ind['id']!r:40s}  label={ind['label']!r}")

    # ------------------------------------------------------------------
    # Steps 4-8 skipped — run explore_levels() once B2B Tech ID is known
    # ------------------------------------------------------------------
    TARGET_INDUSTRY_ID = "apparel"
    _explore_levels(prod_session, TARGET_INDUSTRY_ID)

    _header("DONE")


def _explore_levels(session: requests.Session, industry_id: str):
    """Fetch forecast for an industry and print distinct values for every level column."""
    _header(f"Level Explorer — {industry_id!r}")
    try:
        df = get_industry_forecast(session, "qa", industry_id, time_gran="yyyyq")
    except Exception as exc:
        print(f"  FAIL — {exc}")
        import traceback; traceback.print_exc()
        return

    print(f"\n  {len(df):,} rows, {len(df.columns)} columns")
    print(f"  Columns: {list(df.columns)}\n")

    level_cols = [c for c in df.columns if c.startswith("level")]
    if not level_cols:
        print("  No 'levelN' columns found — printing all column uniques instead")
        level_cols = df.columns.tolist()

    for col in level_cols:
        vals = sorted(df[col].dropna().unique().tolist())
        print(f"  {col} ({len(vals)} distinct):")
        for v in vals:
            print(f"    {v!r}")
        print()


if __name__ == "__main__":
    main()
