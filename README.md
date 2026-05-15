# Forecast Accuracy Deck Builder — v2

Generates PowerPoint forecast vs actuals accuracy decks from live NPD Future of dashboard data.

**v2** = same domain logic as the original [ADB-TOOL](https://github.com/Ciaran-MacDermott/ADB-TOOL), rebuilt on the Circana React + FastAPI shape (matches `data_ingester` and `AIC`). Streamlit replaced with a Next.js frontend served by the FastAPI BFF on a single port.

## Layout

```
api/                 FastAPI backend-for-frontend
  main.py            HTTP surface — kicks off runs, serves web/out at /
  schemas.py         Pydantic request/response models
  runs.py            in-process run registry
src/
  acc_deck_pkg/      ADB pipeline (PPT builder, LLM insights, NPD extractor)
  acc_deck_fs_pkg/   foodservice pipeline variant
pipeline_config/     template.pptx, prompts, runtime config
tests/               pytest suite
web/                 Next.js 15 + React 19 + Tailwind frontend
  kit/               synced from ~/Downloads/kit (don't edit directly)
  app/               routes
  lib/               api client + types
docs/
scripts/
Dockerfile           single-port image: builds web/out then runs uvicorn
```

## Dev

```bash
# Backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn api.main:app --reload --port 8000

# Frontend (separate terminal)
cd web
npm install
npm run dev          # runs predev kit:sync, starts Next on :3000
```

The frontend hits `http://localhost:8000` in dev (CORS-allowed by `api/main.py`).

## Production build

```bash
cd web && npm run build         # produces web/out/
uvicorn api.main:app --port 8000  # serves API + web/out at /
```

Or via Docker:

```bash
docker build -t adb-tool-v2 .
docker run -p 8000:8000 --env-file .env adb-tool-v2
```

## Circana kit

The `web/kit/` folder is a **synced local copy** of `~/Downloads/kit`. Never edit `web/kit/` directly — edit the canonical files in `~/Downloads/kit/` and rerun:

```bash
bash ~/Downloads/kit/sync.sh ~/Downloads/ADB-TOOL-v2
```

The `web` package's `predev` and `prebuild` scripts run this automatically, so a fresh `npm run dev` or `npm run build` always uses the latest kit. See `~/Downloads/kit/README.md` for the full pattern.

## LLM provider — `src/llm/`

Every model invocation goes through `llm.complete(profile, messages, ...)`. The pipeline (`acc_deck_pkg`, `acc_deck_fs_pkg`) never imports `requests`, `groq`, `openai`, or `anthropic` directly — that means swapping the LLM endpoint to internally-hosted models is a one-file change. See `src/llm/README.md` for the 5-minute migration walkthrough.

## Network policy

**Build environment (DMZ host)** — needs egress to:

| Endpoint | Port | Purpose |
|---|---|---|
| `registry-1.docker.io` | 443 | Pull `node:20-bookworm-slim` and `python:3.12-slim` base images |
| `deb.debian.org`, `security.debian.org` | 443 | apt: chromium, chromium-driver, curl |
| `registry.npmjs.org` | 443 | `npm ci` for the Next.js build |
| `pypi.org`, `files.pythonhosted.org` | 443 | `pip install -r requirements.txt` |
| `fonts.googleapis.com`, `fonts.gstatic.com` | 443 | `next/font/google` downloads Inter at build time and inlines it under `web/out/_next/static/media/` — runtime makes ZERO calls to Google Fonts |

For walled-garden CI substitute internal registry mirrors as needed. The image artifact then ships into the walled garden.

**Runtime environment (walled-garden container)** — egress allowlist:

| Endpoint | Port | Required when | Where to swap |
|---|---|---|---|
| `api.groq.com` | 443 | Today (LLM provider for `brief`, `fast_writer`, `total_subheader` profiles) | `src/llm/profiles.py` |
| `api.moonshot.ai` | 443 | Today (Kimi K2.6 — `writer`, `cleanup`, `fs_insight` profiles) | `src/llm/profiles.py` |
| `openrouter.ai` | 443 | Registered as a provider but no profile routes here — safe to omit from the allowlist | `src/llm/providers/__init__.py` |
| `future-of.npd.com` | 443 | NPD External API, prod | env: `NPD_PROD_URL` |
| `future-of-qa.npd.com` | 443 | NPD External API, QA | env: `NPD_QA_URL` |

After the internal-LLM swap (see `src/llm/providers/internal_stub.py`), the three external LLM domains can be dropped from the runtime allowlist.

**Runtime ingress (inbound to the container):**

| Port | Protocol | Purpose |
|---|---|---|
| `8000` | HTTP | FastAPI BFF — `/api/*` JSON + Next.js static export at `/`. Sits behind a TLS-terminating reverse proxy in production. |

**Source-of-truth files** (read these to draft firewall rules — they're the only places network endpoints are declared):

- `src/llm/providers/__init__.py` — every LLM URL the app can reach
- `src/acc_deck_pkg/api_extractor.py` and `src/acc_deck_fs_pkg/api_extractor_v2.py` — NPD endpoints
- `Dockerfile` — build-time + runtime port summary at the top

**Known walled-garden gotcha — `template.pptx` is a Git LFS pointer.** `src/acc_deck_fs_pkg/Templates/template.pptx` is currently a 131-byte LFS pointer file. The pipeline opens it as a binary `.pptx` and will fail on the LFS placeholder. Either install `git-lfs` and pull, or commit the binary directly out of LFS, before deploying into a walled-garden CI that lacks LFS access.

## Migrating from v1

The legacy Streamlit packages (`acc_deck_pkg`, `acc_deck_fs_pkg`) live under `src/`. The FastAPI `POST /api/runs` handler in `api/main.py` is the wiring point — it currently transitions through states without invoking the pipeline. To wire it:

1. Import the relevant pipeline module (`src.acc_deck_pkg.pipeline` or `src.acc_deck_fs_pkg.pipeline`) inside the worker thread.
2. Adapt the function signature to accept the `RunRequest` payload from `api/schemas.py`.
3. Have the pipeline write its PPTX to a temp path and stash it on `Run.artifact` so `GET /api/runs/{id}/download` can serve it.

See `streamlit_app.py` in the v1 repo for the original input → pipeline → download wiring.
