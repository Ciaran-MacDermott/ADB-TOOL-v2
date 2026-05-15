"""
FastAPI BFF for the Forecast Accuracy Deck Builder (v2).

Mirrors the data_ingester / AIC shape:
  - Dev: Next runs on :3002 and hits this on :8002 (CORS allows it).
  - Prod: `npm run build` produces web/out/, FastAPI serves it at /,
    the whole app runs on a single port.

The deck-building engine lives in src/acc_deck_pkg and src/acc_deck_fs_pkg
(ported from the original Streamlit app). This BFF provides a thin REST
surface over it: kick off runs, poll status, download the PPTX.

──────────────────────────────────────────────────────────────────────────
NETWORK POLICY
──────────────────────────────────────────────────────────────────────────
Ingress (inbound to this process):
  :8002 (HTTP) — /api/* JSON + the static frontend mounted at /. Sits
                 behind a TLS-terminating reverse proxy in production.
  :3002 (HTTP) — only in dev (Next.js dev server with CORS allow).

Egress (outbound — must be reachable from the runtime environment):
  - LLM providers: see src/llm/providers/__init__.py for the current
    URLs (api.groq.com, api.moonshot.ai). Once the internal endpoint in
    src/llm/providers/internal_stub.py is wired, these can be removed
    from the allowlist.
  - NPD External API:
      * future-of.npd.com:443     (prod)   — overridable via NPD_PROD_URL
      * future-of-qa.npd.com:443  (QA)     — overridable via NPD_QA_URL
"""

from __future__ import annotations

import concurrent.futures
import io
import json
import os
import sys
import tempfile
import threading
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Load .env early so GROQ/Moonshot/NPD keys are visible to the pipeline.
# override=True is critical on Windows + Git Bash: MSYS mangles Unix-style
# paths like NPD_API_PATH_INDUSTRIES=/api/ext/industries to a Windows path
# (C:/Users/.../Git/api/ext/industries) before Python ever runs. The .env
# file holds the correct literal value; override=True forces it to win.
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except Exception:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
# The pipeline package imports its sub-modules as ``from acc_deck_pkg.X``
# rather than ``from src.acc_deck_pkg.X``, so we also need ``src/`` on the
# path. Same reason ``src/llm/`` works without a ``src.`` prefix.
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from api import runs as run_registry
from api import sessions as session_registry
from api.schemas import (
    ConnectRequest,
    ConnectResponse,
    IndustryOut,
    LevelsOut,
    RunRequest,
    RunResponse,
    RunStatus,
)

# Install the stdout tee once, so pipeline print() lines get routed to
# the right Run.logs based on the current thread.
run_registry.install_stdout_tee()


# ── Pipeline routing ──────────────────────────────────────────────────
# Industries whose slug starts here route to acc_deck_fs_pkg. Everything
# else routes to acc_deck_pkg. Any other ``food-service-*`` slug (UK,
# Mexico, etc.) is excluded from the dropdown — they run on a separate
# pipeline this app doesn't implement.
FS_INDUSTRY_IDS: frozenset[str] = frozenset({
    "food-service",
    "food-service-canada",
    "food-service-australia",
})


def _industry_supported(slug: str) -> bool:
    if slug.startswith("food-service"):
        return slug in FS_INDUSTRY_IDS
    return True


def _industry_pipeline(slug: str) -> str:
    return "fs" if slug in FS_INDUSTRY_IDS else "adb"


# ── Pipeline config (ADB) ─────────────────────────────────────────────
_PIPELINE_CONFIG_DIR = PROJECT_ROOT / "pipeline_config" / "pipeline_config"
_TEMPLATE_PPTX       = _PIPELINE_CONFIG_DIR / "template.pptx"
_CONFIG_JSON         = _PIPELINE_CONFIG_DIR / "config.json"


def _load_adb_config() -> dict:
    if not _CONFIG_JSON.exists():
        raise RuntimeError(f"Bundled config not found: {_CONFIG_JSON}")
    with open(_CONFIG_JSON, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["_config_dir"] = str(_PIPELINE_CONFIG_DIR)
    # Normalise key names so older configs still work.
    if "column_mapping" in cfg and "column_map" not in cfg:
        cfg["column_map"] = cfg["column_mapping"]
    if "sheet_name_forecast" not in cfg:
        cfg["sheet_name_forecast"] = "DATA"
    if "sheet_name_actual" not in cfg:
        cfg["sheet_name_actual"] = "DATA"
    return cfg


def _read_prompts(cfg: dict) -> tuple[str, str, str, str]:
    base = Path(cfg["_config_dir"])
    prompts = cfg["prompts"]
    def _read(key: str) -> str:
        return (base / prompts[key]).read_text(encoding="utf-8")
    return (
        _read("system_prompt_file"),
        _read("user_meta_prompt_file"),
        _read("total_slide_prompt_file"),
        _read("row_prompt_template_file"),
    )


def _build_runtime_config(
    cfg: dict,
    *,
    input_level1: str,
    year: int,
    quarter: int,
    release: str,
    deck_path: str,
    xlsx_path: str,
) -> dict:
    system_prompt, meta_prompt, total_prompt, row_prompt = _read_prompts(cfg)
    return {
        "api":                     cfg.get("api", {}),
        "input_level1":            input_level1,
        "input_year":              year,
        "input_quarter":           quarter,
        "release":                 release,
        "ppt_template":            str(_TEMPLATE_PPTX),
        "paths":                   {"actual": "", "forecast": ""},
        "deck_path":               deck_path,
        "out_xlsx":                xlsx_path,
        "_config_dir":             cfg["_config_dir"],
        "prompts":                 cfg.get("prompts", {}),
        "prompt_data_dir":         str(_PIPELINE_CONFIG_DIR / "prompt_data"),
        "prompt_sampling":         cfg.get("prompt_sampling", {}),
        "api_key":                 "",
        "groq_api_key":            os.getenv("GROQ_API_KEY", ""),
        "moonshot_api_key":        os.getenv("MOONSHOT_API_KEY", ""),
        "column_map":              cfg.get("column_map"),
        "sheet_name_forecast":     cfg.get("sheet_name_forecast", "DATA"),
        "sheet_name_actual":       cfg.get("sheet_name_actual", "DATA"),
        "llm_column_aliases":      cfg.get("llm_column_aliases"),
        "SYSTEM_PROMPT":           system_prompt,
        "USER_META_PROMPT":        meta_prompt,
        "USER_TOTAL_SLIDE_PROMPT": total_prompt,
        "ROW_PROMPT_TEMPLATE":     row_prompt,
        "model_params":            cfg.get("model_params", {}),
        "narrative_analysis":      cfg.get("narrative_analysis", {}),
        "post_processing":         cfg.get("post_processing", {}),
        "llm_provider":            cfg.get("llm_provider", "free"),
        "free_llm":                cfg.get("free_llm", {}),
        "industry_rules":          cfg.get("industry_rules", {}),
    }


app = FastAPI(title="ADB Deck Builder API")

# CORS allow-list — env-driven so the dev origin only opens in dev.
# Production single-port deploy serves the frontend from the same origin
# as the API, so this list is empty and no CORS headers are added.
_cors_origins = [
    o.strip() for o in os.getenv("ADB_CORS_ORIGINS", "").split(",") if o.strip()
]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )


def _require_session(token: str | None) -> session_registry.Session:
    """Auth dependency for endpoints that need an NPD session."""
    if not token:
        raise HTTPException(status_code=401, detail="Connect first.")
    sess = session_registry.get(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Session expired or invalid.")
    return sess


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ── /api/connect ──────────────────────────────────────────────────────
@app.post("/api/connect", response_model=ConnectResponse)
def connect(req: ConnectRequest):
    """Authenticate against the NPD Future of dashboard.

    Runs Selenium SSO against prod + qa in parallel (cached cookies are
    reused if still valid). On success returns the bearer token and the
    industries list count. Selenium output is tee'd to a buffer so the
    frontend can show the connect log even though the SSO itself runs in
    a worker thread.
    """
    from acc_deck_pkg.api_extractor import connect as adb_connect, fetch_industries

    captured = io.StringIO()
    error: Optional[str] = None
    prod = None
    qa   = None
    industries: list[dict] = []

    def _do_connect():
        nonlocal prod, qa, industries, error
        with redirect_stdout(captured), redirect_stderr(captured):
            try:
                print("Starting parallel login to PROD and QA environments...")
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    f_prod = pool.submit(adb_connect, req.username, req.password, "prod")
                    f_qa   = pool.submit(adb_connect, req.username, req.password, "qa")
                    prod   = f_prod.result()
                    qa     = f_qa.result()
                if not prod:
                    error = "Production login failed — check credentials and NPD_PROD_URL."
                    return
                if not qa:
                    error = "QA login failed — check credentials and NPD_QA_URL."
                    return
                print("Both environments authenticated — fetching industries...")
                industries = fetch_industries(prod)
                print(f"Fetched {len(industries)} industries.")
            except Exception as exc:
                error = f"{exc}\n{traceback.format_exc()}"

    _do_connect()
    log_lines = [l for l in captured.getvalue().splitlines() if l.strip()]

    if error:
        # Surface the captured Selenium output so the frontend has a
        # diagnosable trail even on failure.
        raise HTTPException(
            status_code=401,
            detail={"message": error.splitlines()[0], "logs": log_lines},
        )

    sess = session_registry.new_session(
        username=req.username,
        prod_session=prod,
        qa_session=qa,
        industries=industries,
        connect_logs=log_lines,
    )
    return ConnectResponse(
        session_token=sess.token,
        username=sess.username,
        expires_at=sess.expires_at,
        industries_count=len(industries),
        logs=log_lines,
    )


@app.post("/api/disconnect")
def disconnect(x_session_token: str | None = Header(default=None)):
    if x_session_token:
        session_registry.revoke(x_session_token)
    return {"status": "ok"}


# ── /api/industries ───────────────────────────────────────────────────
@app.get("/api/industries", response_model=list[IndustryOut])
def list_industries(x_session_token: str | None = Header(default=None)):
    """Return the industries discovered during /api/connect, filtered to
    those this app supports and tagged with their pipeline routing."""
    sess = _require_session(x_session_token)
    out: list[IndustryOut] = []
    for item in sess.industries:
        slug = str(item["id"])
        if not _industry_supported(slug):
            continue
        out.append(IndustryOut(
            slug=slug,
            label=str(item["label"]),
            pipeline=_industry_pipeline(slug),
        ))
    return out


@app.get("/api/industries/{slug}/levels", response_model=LevelsOut)
def get_industry_levels(
    slug: str,
    x_session_token: str | None = Header(default=None),
):
    """For an ADB industry, fetch the level1 filter values and the list of
    level* columns (level2, level3, …) available. Foodservice industries
    skip this step — return empty lists."""
    sess = _require_session(x_session_token)
    if not _industry_supported(slug):
        raise HTTPException(status_code=404, detail=f"Unsupported industry: {slug}")
    if _industry_pipeline(slug) == "fs":
        return LevelsOut()

    from acc_deck_pkg.api_extractor import get_industry_forecast
    try:
        df = get_industry_forecast(sess.prod_session, "prod", slug, "yyyyq")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"NPD forecast fetch failed: {exc}")

    level1_vals = sorted(df["level1"].dropna().unique().tolist()) if "level1" in df.columns else []
    level_cols  = [c for c in sorted(df.columns) if c.startswith("level") and c != "level1"]
    return LevelsOut(
        level1_options=[str(x) for x in level1_vals],
        level_cols=level_cols,
    )


# ── /api/runs ─────────────────────────────────────────────────────────
@app.post("/api/runs", response_model=RunResponse)
def start_run(req: RunRequest, x_session_token: str | None = Header(default=None)):
    """Kick off a deck build. Returns immediately with a run_id; the client
    polls /api/runs/{id} for progress and downloads via
    /api/runs/{id}/download once state == 'done'.

    The worker acquires one of ``RUN_SLOTS`` before flipping state to
    'running'; if all slots are taken the run sits at state='queued'
    until a slot frees up.
    """
    sess = _require_session(x_session_token)

    if not _industry_supported(req.industry):
        raise HTTPException(status_code=400, detail=f"Unknown industry: {req.industry}")

    # Find the industry label from the session list so we can name the deck.
    industry_label = next(
        (i["label"] for i in sess.industries if i["id"] == req.industry),
        req.industry,
    )

    run = run_registry.new_run()

    # Per-run output dir (cleaned up by the OS or on TTL eviction).
    tmp_dir   = Path(tempfile.mkdtemp(prefix="adb_output_"))
    safe_name = industry_label.strip().replace(" ", "_")
    deck_name = f"{req.release_date.replace('/', '-')}_{safe_name}_Accuracy_Deck.pptx"
    xlsx_name = deck_name.replace(".pptx", "_Insights.xlsx")
    deck_path = tmp_dir / deck_name
    xlsx_path = tmp_dir / xlsx_name

    # Snapshot what the worker needs so it doesn't touch the session dict
    # after the HTTP handler returns.
    prod_session = sess.prod_session
    qa_session   = sess.qa_session
    int_quarter  = int(req.quarter[1])  # "Q3" -> 3
    pipeline_kind = _industry_pipeline(req.industry)

    def _worker():
        with run_registry.RUN_SLOTS:
            run_registry.set_state(run, state="running", step="extracting")
            run_registry.set_run_for_thread(run)
            t0 = time.time()
            try:
                if pipeline_kind == "fs":
                    _run_fs_pipeline(
                        run=run,
                        prod_session=prod_session,
                        qa_session=qa_session,
                        industry_id=req.industry,
                        industry_label=industry_label,
                        year=req.year,
                        quarter=int_quarter,
                        release=req.release_date,
                        deck_path=deck_path,
                    )
                    run.artifact = deck_path if deck_path.exists() else None
                else:
                    _run_adb_pipeline(
                        run=run,
                        prod_session=prod_session,
                        qa_session=qa_session,
                        industry_id=req.industry,
                        industry_label=industry_label,
                        year=req.year,
                        quarter=int_quarter,
                        release=req.release_date,
                        category_order=req.category_order,
                        level1_filter=req.level1_filter,
                        analysis_level=req.analysis_level or "level2",
                        deck_path=deck_path,
                        xlsx_path=xlsx_path,
                    )
                    run.artifact      = deck_path if deck_path.exists() else None
                    run.artifact_xlsx = xlsx_path if xlsx_path.exists() else None

                if run.cancel_event.is_set():
                    run_registry.set_state(run, state="cancelled", step="cancelled")
                else:
                    run_registry.set_state(run, state="done", step="finished")
                    run_registry.record_run_duration(time.time() - t0)
            except Exception as exc:
                tb = traceback.format_exc()
                run_registry.append_log(run, f"ERROR: {exc}")
                for line in tb.splitlines():
                    run_registry.append_log(run, line)
                run_registry.set_state(run, state="error", message=str(exc))
            finally:
                run_registry.clear_run_for_thread()

    threading.Thread(target=_worker, daemon=True).start()
    return RunResponse(run_id=run.run_id)


def _run_adb_pipeline(
    *,
    run,
    prod_session, qa_session,
    industry_id: str, industry_label: str,
    year: int, quarter: int, release: str,
    category_order: str,
    level1_filter: Optional[str],
    analysis_level: str,
    deck_path: Path, xlsx_path: Path,
) -> None:
    from acc_deck_pkg.data_io import load_data_from_api
    from acc_deck_pkg.main_meta_modes import main as pipeline_main

    cfg = _load_adb_config()
    runtime_cfg = _build_runtime_config(
        cfg,
        input_level1=industry_label.strip(),
        year=year,
        quarter=quarter,
        release=release,
        deck_path=str(deck_path),
        xlsx_path=str(xlsx_path),
    )

    print(f"[Extracting] Fetching forecast + actuals for {industry_label}...")
    run_registry.set_state(run, step="extracting")
    df = load_data_from_api(
        prod_session, qa_session, industry_id,
        level1_filter=level1_filter,
        analysis_level=analysis_level,
    )
    if run.cancel_event.is_set():
        return

    print("[Building] Running ADB pipeline...")
    run_registry.set_state(run, step="building deck")
    pipeline_main(
        runtime_config=runtime_cfg,
        category_order=category_order,
        df=df,
        cancel_check=run.cancel_event.is_set,
    )


def _run_fs_pipeline(
    *,
    run,
    prod_session, qa_session,
    industry_id: str, industry_label: str,
    year: int, quarter: int, release: str,
    deck_path: Path,
) -> None:
    # Direct CSV side-effects to the per-run output dir.
    os.environ["FS_WRITABLE_DIR"] = str(deck_path.parent)
    from acc_deck_fs_pkg import pipeline as fs_pipeline

    # Normalise "Food Service" → "Foodservice" for cover/footers.
    project_display = industry_label.replace("Food Service", "Foodservice")

    fs_pipeline.PIPELINE_CONFIG["input_year"]       = year
    fs_pipeline.PIPELINE_CONFIG["input_quarter"]    = quarter
    fs_pipeline.PIPELINE_CONFIG["groq_api_key"]     = os.getenv("GROQ_API_KEY", "")
    fs_pipeline.PIPELINE_CONFIG["moonshot_api_key"] = os.getenv("MOONSHOT_API_KEY", "")
    fs_pipeline.PIPELINE_CONFIG["output_path"]      = str(deck_path)
    fs_pipeline.PIPELINE_CONFIG["project_display"]  = project_display

    if run.cancel_event.is_set():
        return

    print(f"[Extracting] Foodservice pipeline for {industry_label}...")
    run_registry.set_state(run, step="extracting")
    fs_pipeline.run_full_pipeline(
        prod_session=prod_session,
        qa_session=qa_session,
        industry_id=industry_id,
        extract=True,
    )


@app.get("/api/runs/{run_id}", response_model=RunStatus)
def get_run(run_id: str):
    run = run_registry.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return RunStatus(**run_registry.snapshot(run))


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    run = run_registry.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    run.cancel_event.set()
    return {"status": "ok"}


@app.get("/api/runs/{run_id}/download")
def download_run(run_id: str):
    run = run_registry.get(run_id)
    if not run or not run.artifact or not run.artifact.exists():
        raise HTTPException(status_code=404, detail="artifact not ready")
    return FileResponse(
        run.artifact,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=run.artifact.name,
    )


@app.get("/api/runs/{run_id}/download/xlsx")
def download_xlsx(run_id: str):
    run = run_registry.get(run_id)
    if not run or not run.artifact_xlsx or not run.artifact_xlsx.exists():
        raise HTTPException(status_code=404, detail="xlsx not ready")
    return FileResponse(
        run.artifact_xlsx,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=run.artifact_xlsx.name,
    )


# ── Static frontend (prod only) ───────────────────────────────────────────
# In dev this directory may not exist — Next is serving on :3002.
WEB_OUT = PROJECT_ROOT / "web" / "out"
if WEB_OUT.exists():
    app.mount("/", StaticFiles(directory=str(WEB_OUT), html=True), name="web")
