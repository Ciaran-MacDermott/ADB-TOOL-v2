"""
FastAPI BFF for the Forecast Accuracy Deck Builder (v2).

Mirrors the data_ingester / AIC shape:
  - Dev: Next runs on :3000 and hits this on :8000 (CORS allows it).
  - Prod: `npm run build` produces web/out/, FastAPI serves it at /,
    the whole app runs on a single port.

The deck-building engine lives in src/acc_deck_pkg and src/acc_deck_fs_pkg
(ported from the original Streamlit app). This BFF provides a thin REST
surface over it: kick off runs, poll status, download the PPTX.

──────────────────────────────────────────────────────────────────────────
NETWORK POLICY
──────────────────────────────────────────────────────────────────────────
Ingress (inbound to this process):
  :8000 (HTTP) — /api/* JSON + the static frontend mounted at /. Sits
                 behind a TLS-terminating reverse proxy in production.
  :3000 (HTTP) — only in dev (Next.js dev server with CORS allow).

Egress (outbound — must be on the walled-garden allowlist):
  - LLM providers: see src/llm/providers/__init__.py for the current
    URLs (api.groq.com, api.moonshot.ai). Once the internal endpoint in
    src/llm/providers/internal_stub.py is wired, these can be removed
    from the allowlist.
  - NPD External API:
      * future-of.npd.com:443     (prod)   — overridable via NPD_PROD_URL
      * future-of-qa.npd.com:443  (QA)     — overridable via NPD_QA_URL
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from api import runs as run_registry
from api import sessions as session_registry
from api.schemas import (
    ConnectRequest,
    ConnectResponse,
    IndustryOut,
    RunRequest,
    RunResponse,
    RunStatus,
)

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
    IndustryOut(slug="b2b",                    label="B2B",                       pipeline="adb"),
    IndustryOut(slug="beauty",                 label="Beauty",                    pipeline="adb"),
    IndustryOut(slug="consumer-tech",          label="Consumer Tech",             pipeline="adb"),
]

app = FastAPI(title="ADB Deck Builder API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


def _require_session(token: str | None) -> session_registry.Session:
    """Auth dependency for endpoints that need an NPD session. Mirrors v1
    Streamlit semantics where you can't list industries (or run) before
    completing the Connect step."""
    if not token:
        raise HTTPException(status_code=401, detail="Connect first.")
    sess = session_registry.get(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Session expired or invalid.")
    return sess


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/connect", response_model=ConnectResponse)
def connect(req: ConnectRequest):
    """Authenticate against the NPD Future of dashboard.

    Scaffold behaviour: any non-empty username/password mints a session.
    Wire the real SSO call (src.acc_deck_pkg.api_extractor.sso_login or
    src.acc_deck_fs_pkg.api_extractor_v2 — both use Selenium + Chromium)
    here, and stash the resulting cookies / requests.Session on
    sess.npd_handle for the run worker to reuse.
    """
    # TODO: invoke NPD SSO login. Map credential failures to HTTPException(401).
    sess = session_registry.new_session(username=req.username)
    return ConnectResponse(
        session_token=sess.token,
        username=sess.username,
        expires_at=sess.expires_at,
    )


@app.post("/api/disconnect")
def disconnect(x_session_token: str | None = Header(default=None)):
    if x_session_token:
        session_registry.revoke(x_session_token)
    return {"status": "ok"}


@app.get("/api/industries", response_model=list[IndustryOut])
def list_industries(x_session_token: str | None = Header(default=None)):
    """Authenticated. v1 fetches industries from NPD post-connect; for the
    scaffold we return the static catalogue, but only after a valid session
    exists — matches the v1 UX where the dropdown is empty until Connect
    succeeds."""
    _require_session(x_session_token)
    return INDUSTRIES


@app.post("/api/runs", response_model=RunResponse)
def start_run(req: RunRequest, x_session_token: str | None = Header(default=None)):
    """Kick off a deck build. Returns immediately with a run_id; the client
    polls /api/runs/{id} for progress and downloads via /api/runs/{id}/download
    once state == 'done'."""
    sess = _require_session(x_session_token)

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
