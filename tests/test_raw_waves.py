"""
tests/test_raw_waves.py
=======================
Hit the forecast endpoint in isolation and print every waveObject
exactly as the API returns it — no processing, no concatenation.

Run:
    python tests/test_raw_waves.py
"""

import sys
import getpass
import json
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acc_deck_pkg.api_extractor import connect, fetch_industries, _get_environments

SEP = "─" * 70


def main():
    print("\n" + "=" * 70)
    print("  Raw waveObject inspector")
    print("=" * 70)

    username = input("\nUsername: ").strip()
    password = getpass.getpass("Password: ").strip()

    # ── Connect to PROD + QA in parallel ─────────────────────────────────────
    import concurrent.futures
    print(f"\n{SEP}\n  Connecting to PROD + QA in parallel...\n{SEP}")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        pf = pool.submit(connect, username, password, "prod")
        qf = pool.submit(connect, username, password, "qa")
        prod_session = pf.result()
        qa_session   = qf.result()

    if not prod_session:
        print("PROD login failed"); sys.exit(1)
    if not qa_session:
        print("QA login failed"); sys.exit(1)

    # ── Find office-supplies (from prod industry list) ────────────────────────
    print(f"\n{SEP}\n  Fetching industries...\n{SEP}")
    industries = fetch_industries(prod_session)
    office = next(
        (i for i in industries if "office" in i["label"].lower() or "office" in i["id"].lower()),
        None,
    )
    if not office:
        print("No office industry found. Available:")
        for i in industries:
            print(f"  {i['id']!r:45s}  {i['label']!r}")
        sys.exit(1)
    print(f"Found: id={office['id']!r}  label={office['label']!r}")

    # ── Raw GET for both envs ─────────────────────────────────────────────────
    envs      = _get_environments()
    dfs_20261 = {}   # env_key -> aggregated DataFrame for the comparison step

    for env_key, session in [("prod", prod_session), ("qa", qa_session)]:
        base_url = envs[env_key]["base_url"]
        url      = f"{base_url}/api/ext/industry/{office['id']}/forecast"
        params   = {"timeGran": "yyyyq"}

        print(f"\n{SEP}")
        print(f"  [{env_key.upper()}] GET {url}")
        print(f"  Params: {params}")
        print(SEP)

        resp = session.get(url, params=params, timeout=60)
        print(f"  HTTP {resp.status_code}")
        resp.raise_for_status()

        data = resp.json()
        print(f"\n  Total waveObjects in response: {len(data)}")

        all_20261 = []

        for i, wave_obj in enumerate(data):
            wave_id = wave_obj.get("wave")
            label   = wave_obj.get("label")
            filt    = wave_obj.get("filter")
            table   = wave_obj.get("table", [])
            n_rows  = len(table)
            cols    = list(table[0].keys()) if table else []

            print(f"\n  [{i}] wave={wave_id!r}  label={label!r}  filter={filt!r}")
            print(f"       rows={n_rows:,}  columns={cols}")

            if table:
                src_vals = {}
                for row in table:
                    s = row.get("src", "<no src>")
                    src_vals[s] = src_vals.get(s, 0) + 1
                print(f"       src breakdown: {src_vals}")

                yyyyq_vals = [r["yyyyq"] for r in table if "yyyyq" in r]
                if yyyyq_vals:
                    print(f"       yyyyq range : {min(yyyyq_vals)} → {max(yyyyq_vals)}")

                print(f"       sample row  : {json.dumps(table[0], default=str)}")

                df = pd.DataFrame(table)
                df["wave"]  = wave_id
                df["label"] = label
                df_20261 = df[df["yyyyq"] == 20261]
                if not df_20261.empty:
                    print(f"\n       yyyyq=20261 ({len(df_20261)} rows):")
                    print(df_20261.to_string(index=False))
                    all_20261.append(df_20261)
                else:
                    print(f"       yyyyq=20261: no rows in this wave")

        if all_20261:
            dfs_20261[env_key] = pd.concat(all_20261, ignore_index=True)

    # ── PROD vs QA % difference for 20261 ────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("  PROD vs QA — % difference for yyyyq=20261")
    print(f"{'=' * 70}")

    group_keys = ["yyyyq", "level1", "level2"]

    if "prod" not in dfs_20261 or "qa" not in dfs_20261:
        print("  Cannot compare — yyyyq=20261 missing from one or both environments")
    else:
        agg_cols = {c: "sum" for c in ["units", "dollars"] if c in dfs_20261["prod"].columns}
        avail_keys = [k for k in group_keys if k in dfs_20261["prod"].columns]

        prod_agg = dfs_20261["prod"].groupby(avail_keys, as_index=False).agg(agg_cols)
        qa_agg   = dfs_20261["qa"].groupby(avail_keys, as_index=False).agg(agg_cols)

        merged = prod_agg.merge(qa_agg, on=avail_keys, suffixes=("_prod", "_qa"), how="outer")

        for col in ["units", "dollars"]:
            p, q = f"{col}_prod", f"{col}_qa"
            if p in merged.columns and q in merged.columns:
                merged[f"{col}_pct_diff"] = (
                    (merged[p] - merged[q]) / merged[q].abs() * 100
                ).round(2)

        pd.set_option("display.max_rows", 200)
        pd.set_option("display.max_columns", 20)
        pd.set_option("display.width", 200)
        pd.set_option("display.float_format", "{:,.2f}".format)
        print(merged.to_string(index=False))

    print(f"\n{'=' * 70}")
    print("  Done")
    print("=" * 70)


if __name__ == "__main__":
    main()
