#!/usr/bin/env python3
"""
fs_api_smoke_test.py
====================
One-off live NPD API smoke test for the 3 foodservice deck types.

Pulls forecast + actuals for:
  - food-service              (US)
  - food-service-canada       (CA)
  - food-service-australia    (AUS)

For each, saves the raw CSVs and dumps a sorted list of unique level2 values
so we can confirm the exact nomenclature on the site — especially whether
AUS has un-prefixed daypart values (Morning Meal / Lunch / Dinner / PM Snack)
and un-prefixed service-mode values (On-Premises / Carry Out / Drive-Thru /
Delivery/Pickup) per CHART_CONFIG['food-service-australia'] in pipeline.py.

Cookie reuse: connect() tries cached cookies in ADB/Cookies/ first. If they
are stale, Selenium SSO runs with the credentials provided.

Usage:
    # via args
    python fs_api_smoke_test.py <npd_username> <npd_password>

    # or via env vars (PowerShell):
    $env:NPD_USERNAME = "you@email.com"; $env:NPD_PASSWORD = "..."
    python fs_api_smoke_test.py
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

# Repo root on path so acc_deck_fs_pkg imports cleanly when run directly
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import pandas as pd
from acc_deck_fs_pkg.api_extractor_v2 import connect, fetch_industries, extract_data

USERNAME = os.environ.get("NPD_USERNAME") or (sys.argv[1] if len(sys.argv) > 1 else "")
PASSWORD = os.environ.get("NPD_PASSWORD") or (sys.argv[2] if len(sys.argv) > 2 else "")

if not USERNAME or not PASSWORD:
    print(
        "ERROR: NPD credentials not provided.\n"
        "  Pass as args: python fs_api_smoke_test.py <username> <password>\n"
        "  Or set env vars NPD_USERNAME and NPD_PASSWORD.\n"
        "  (Cached cookies in ADB/Cookies/ will be reused if still valid.)"
    )
    sys.exit(2)

CASES = [
    ("fs_us",  "food-service"),
    ("fs_ca",  "food-service-canada"),
    ("fs_aus", "food-service-australia"),
]

OUT_ROOT = _HERE / "test_output_fs" / "api_dumps"
OUT_ROOT.mkdir(parents=True, exist_ok=True)


def _print_section(title: str) -> None:
    print("\n" + "=" * 78)
    print(f"  {title}")
    print("=" * 78)


_print_section("Authenticating PROD + QA (cached cookies if fresh)")
prod = connect(USERNAME, PASSWORD, "prod")
if not prod:
    print("FAIL: PROD authentication failed.")
    sys.exit(1)
qa = connect(USERNAME, PASSWORD, "qa")
if not qa:
    print("FAIL: QA authentication failed.")
    sys.exit(1)
print("\nBoth environments authenticated.")

_print_section("Industry list — confirming the 3 foodservice IDs are visible")
try:
    industries = fetch_industries(prod)
    print(f"Total industries available: {len(industries)}")
    fs_visible = [i for i in industries if "food" in str(i.get("id", "")).lower()
                  or "food" in str(i.get("label", "")).lower()]
    print(f"Foodservice-related industries visible to this account ({len(fs_visible)}):")
    for i in fs_visible:
        print(f"  id={i.get('id')!r:<32}  label={i.get('label')!r}")
except Exception as e:
    print(f"WARN: industry listing failed: {type(e).__name__}: {e}")
    industries = []

# Foodservice industries we expect to extract regardless of listing
expected_ids = {industry_id for _, industry_id in CASES}
listed_ids   = {str(i.get("id", "")).lower() for i in industries}
missing      = expected_ids - listed_ids
if missing:
    print(f"\nNote: these expected IDs are NOT in the visible industry list: {sorted(missing)}")
    print("      The extractor will still attempt them — your account may have hidden access,\n"
          "      or the API may serve them by ID even when the listing endpoint omits them.\n")

results_summary: list[tuple[str, str, str]] = []

for code, industry_id in CASES:
    _print_section(f"EXTRACT: {code}  ({industry_id})")

    out_dir = OUT_ROOT / code
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        results = extract_data(prod, qa, industry_id=industry_id, output_dir=str(out_dir))
        df_f = results.get("prod")
        df_a = results.get("qa")

        if df_f is None or df_a is None:
            msg = f"prod={'OK' if df_f is not None else 'FAILED'}, qa={'OK' if df_a is not None else 'FAILED'}"
            print(f"  FAIL: {msg}")
            results_summary.append((code, "FAIL", msg))
            continue

        print(f"  forecast rows: {len(df_f):,} | actuals rows: {len(df_a):,}")
        print(f"  forecast cols: {list(df_f.columns)}")

        # Save full raw CSVs (extract_data already writes its own; we add canonical names too)
        df_f.to_csv(out_dir / "forecast_full.csv", index=False)
        df_a.to_csv(out_dir / "actuals_full.csv", index=False)

        # Unique level2 values — the key thing we want to confirm
        l2_vals = sorted(df_f["level2"].dropna().unique().tolist())
        with open(out_dir / "level2_values.txt", "w", encoding="utf-8") as fh:
            fh.write(f"# industry_id: {industry_id}\n")
            fh.write(f"# unique level2 values: {len(l2_vals)}\n\n")
            for v in l2_vals:
                fh.write(f"{v}\n")
        print(f"  unique level2 values: {len(l2_vals)} (saved to level2_values.txt)")

        # Sniff for the daypart + service-mode values per CHART_CONFIG expectations
        daypart_us_ca = ["Morning Meal", "Lunch", "Supper", "PM Snack"]
        daypart_aus   = ["Morning Meal", "Lunch", "Dinner", "PM Snack"]
        svc_us_ca_qsr = ["On-Premises", "Carry-Out", "Drive-Thru", "Delivery"]
        svc_us_ca_fsr = ["On-Premises", "Carry-Out", "Delivery"]
        svc_aus       = ["On-Premises", "Carry Out", "Drive-Thru", "Delivery/Pickup"]

        def _present(items: list[str]) -> tuple[list[str], list[str]]:
            found, missing = [], []
            for it in items:
                (found if it in l2_vals else missing).append(it)
            return found, missing

        if industry_id == "food-service-australia":
            f, m = _present(daypart_aus)
            print(f"  AUS dayparts (un-prefixed) — found: {f}  missing: {m}")
            f, m = _present(svc_aus)
            print(f"  AUS service modes (un-prefixed) — found: {f}  missing: {m}")
        else:
            # US/CA expect QSR/FSR-prefixed level2 values for slides 3 + 4
            qsr_dp = [f"QSR {d}" for d in daypart_us_ca]
            fsr_dp = [f"FSR {d}" for d in daypart_us_ca]
            qsr_sv = [f"QSR {s}" for s in svc_us_ca_qsr]
            fsr_sv = [f"FSR {s}" for s in svc_us_ca_fsr]
            for label, items in [("QSR dayparts", qsr_dp), ("FSR dayparts", fsr_dp),
                                 ("QSR service modes", qsr_sv), ("FSR service modes", fsr_sv)]:
                f, m = _present(items)
                print(f"  {label} — found: {len(f)}/{len(items)}  missing: {m}")

        results_summary.append((code, "PASS", f"{len(df_f)} rows, {len(l2_vals)} l2 values"))

    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
        traceback.print_exc(limit=3)
        results_summary.append((code, "ERROR", f"{type(e).__name__}: {e}"))


_print_section("SUMMARY")
for code, status, note in results_summary:
    print(f"  {code:<8} {status:<6} {note}")
print(f"\nAll outputs under: {OUT_ROOT}")
print("\nNext: review test_output_fs/api_dumps/fs_aus/level2_values.txt to confirm AUS\n"
      "      nomenclature, then update CHART_CONFIG['food-service-australia'] in\n"
      "      acc_deck_fs_pkg/pipeline.py if the live values differ from the current\n"
      "      Morning Meal / Lunch / Dinner / PM Snack and On-Premises / Carry Out /\n"
      "      Drive-Thru / Delivery/Pickup expectations.")
