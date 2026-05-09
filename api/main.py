"""
FastAPI BFF for the Forecast Accuracy Deck Builder (v2).

Mirrors the data_ingester / AIC shape:
  - Dev: Next runs on :3000 and hits this on :8000 (CORS allows it).
  - Prod: `npm run build` produces web/out/, FastAPI serves it at /,
    the whole app runs on a single port.

The deck-building engine lives in src/acc_deck_pkg and src/acc_deck_fs_pkg
(ported from the original Streamlit app). This BFF provides a thin REST
surface over it: kick off runs, poll status, download the PPTX.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from api import runs as run_registry
from api.schemas import IndustryOut, RunRequest, RunResponse, RunStatus

# ── Industry catalogue ────────────────────────────────────────────────────
# Hard-coded for v2 scaffold; move to config/industries.yaml when the front-end
# stabilises. The fs/* slugs route to acc_deck_fs_pkg; everything else routes
# to acc_deck_pkg. Same split as the original Streamlit app.
INDUSTRIES: list[IndustryOut] = [
    IndustryOut(slug="food-service",           label="Food Service (US)",         pipeline="fs"),
    IndustryOut(slug="food-service-canada",    label="Food Service (Canada)",     pipeline="fs"),
    IndustryOut(slug="food-service-australia", label="Food Service (Australia)",  pipeline="fs"),
    # ADB pipeline industries — extend as needed.
    IndustryOut(slug="apparel",                label="Apparel",                   pipeline="adb"),
    IndustryOut(slug="beauty",                 label="Beauty",                    pipeline="adb"),
    IndustryOut(slug="consumer-tech",          label="Consumer Tech",             pipeline="adb"),
]

app = FastAPI(title="ADB Deck Builder API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/industries", response_model=list[IndustryOut])
def list_industries():
    return INDUSTRIES


@app.post("/api/runs", response_model=RunResponse)
def start_run(req: RunRequest):
    """Kick off a deck build. Returns immediately with a run_id; the client
    polls /api/runs/{id} for progress and downloads via /api/runs/{id}/download
    once state == 'done'."""
    industry = next((i for i in INDUSTRIES if i.slug == req.industry), None)
    if industry is None:
        raise HTTPException(status_code=400, detail=f"Unknown industry: {req.industry}")

    run = run_registry.new_run()

    def _worker():
        # TODO: wire to src/acc_deck_pkg.pipeline or src/acc_deck_fs_pkg.pipeline
        # depending on industry.pipeline. For scaffold purposes we just
        # transition through the states.
        try:
            run_registry.update(run.run_id, state="running", step="extracting")
            # ... actual pipeline call goes here ...
            run_registry.update(run.run_id, state="done", step="finished")
        except Exception as exc:  # pragma: no cover — placeholder
            run_registry.update(run.run_id, state="error", message=str(exc))

    threading.Thread(target=_worker, daemon=True).start()
    return RunResponse(run_id=run.run_id)


@app.get("/api/runs/{run_id}", response_model=RunStatus)
def get_run(run_id: str):
    run = run_registry.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return RunStatus(
        run_id=run.run_id,
        state=run.state,
        step=run.step or None,
        message=run.message or None,
        elapsed_s=run.elapsed_s,
    )


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


# ── Static frontend (prod only) ───────────────────────────────────────────
# In dev this directory may not exist — Next is serving on :3000.
WEB_OUT = PROJECT_ROOT / "web" / "out"
if WEB_OUT.exists():
    app.mount("/", StaticFiles(directory=str(WEB_OUT), html=True), name="web")
