# Forecast Accuracy Deck Builder — v2

Generates PowerPoint forecast vs actuals accuracy decks from live NPD Future of dashboard data.

**v2** = same domain logic as the original [ADB-TOOL](https://github.com/Ciaran-MacDermott/ADB-TOOL), rebuilt on a Next.js + FastAPI shape. Streamlit replaced with a Next.js frontend served by the FastAPI BFF on a single port.

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
  kit/               shared UI components (committed in-tree)
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
uvicorn api.main:app --reload --port 8002

# Frontend (separate terminal)
cd web
npm install
npm run dev          # Next on :3002
```

The frontend hits `http://localhost:8002` in dev (CORS-allowed by `api/main.py`).

Ports 3002 / 8002 are chosen to avoid clashing with other local Next + FastAPI projects that run on the defaults 3000 / 8000.

Copy `.env.example` to `.env` and fill in the values you need (NPD credentials, LLM provider keys). `.env` is gitignored — never commit real secrets.

## Production build

```bash
cd web && npm run build           # produces web/out/
uvicorn api.main:app --port 8002  # serves API + web/out at /
```

Or via Docker:

```bash
docker build -t adb-tool-v2 .
docker run -p 8002:8002 --env-file .env adb-tool-v2
```

## UI components — `web/kit/`

The `web/kit/` folder holds the shared UI primitives (Button, Card, AppShell, Wordmark, etc.) used across the app. It's a small in-house toolkit shared across a few sibling tools to keep the look and feel consistent — but it's vendored into this repo as plain source, so `git clone` + `npm install` is everything a new contributor needs. No extra fetch, no private package registry, no submodules. Edit files under `web/kit/` directly; treat it like any other source folder. Improvements you make here are welcome to flow back upstream.

The kit currently carries Circana branding — the logo (`web/public/Circana_logo.png`), the brand palette in `web/kit/tailwind-preset.ts`, and the design tokens in `web/kit/styles/circana.css` and `primitives.css`. The `Wordmark` component defaults to the Circana logo, and the generated deck output is intentionally Circana-styled. If you ever want a brand-neutral fork, the swap surface is small: replace the logo asset, retheme the Tailwind preset, and the two CSS token files.

## LLM provider — `src/llm/`

Every model invocation goes through `llm.complete(profile, messages, ...)`. The pipeline (`acc_deck_pkg`, `acc_deck_fs_pkg`) never imports `requests`, `groq`, `openai`, or `anthropic` directly — that means swapping the LLM endpoint to internally-hosted models is a one-file change. See `src/llm/README.md` for the migration walkthrough.

## Network policy

**Build environment** — needs egress to:

| Endpoint | Port | Purpose |
|---|---|---|
| `registry-1.docker.io` | 443 | Pull `node:20-bookworm-slim` and `python:3.12-slim` base images |
| `deb.debian.org`, `security.debian.org` | 443 | apt: chromium, chromium-driver, curl |
| `registry.npmjs.org` | 443 | `npm ci` for the Next.js build |
| `pypi.org`, `files.pythonhosted.org` | 443 | `pip install -r requirements.txt` |
| `fonts.googleapis.com`, `fonts.gstatic.com` | 443 | `next/font/google` downloads Inter at build time and inlines it under `web/out/_next/static/media/` — runtime makes ZERO calls to Google Fonts |

CI behind a restricted network can substitute internal registry mirrors as needed.

**Runtime egress** (the container must be able to reach):

| Endpoint | Port | Required when | Where to swap |
|---|---|---|---|
| `api.groq.com` | 443 | Today (LLM provider for `brief`, `fast_writer`, `total_subheader` profiles) | `src/llm/profiles.py` |
| `api.moonshot.ai` | 443 | Today (Kimi K2.6 — `writer`, `cleanup`, `fs_insight` profiles) | `src/llm/profiles.py` |
| `openrouter.ai` | 443 | Registered as a provider but no profile routes here — safe to omit | `src/llm/providers/__init__.py` |
| `future-of.npd.com` | 443 | NPD External API, prod | env: `NPD_PROD_URL` |
| `future-of-qa.npd.com` | 443 | NPD External API, QA | env: `NPD_QA_URL` |

If `src/llm/providers/internal_stub.py` is later wired to an internal LLM endpoint, the three external LLM domains can be dropped from the runtime allowlist.

**Runtime ingress (inbound to the container):**

| Port | Protocol | Purpose |
|---|---|---|
| `8002` | HTTP | FastAPI BFF — `/api/*` JSON + Next.js static export at `/`. Sits behind a TLS-terminating reverse proxy in production. |

**Source-of-truth files** (read these to draft firewall rules — they're the only places network endpoints are declared):

- `src/llm/providers/__init__.py` — every LLM URL the app can reach
- `src/acc_deck_pkg/api_extractor.py` and `src/acc_deck_fs_pkg/api_extractor_v2.py` — NPD endpoints
- `Dockerfile` — build-time + runtime port summary at the top

**Templates are committed as regular binaries**, not LFS — both `src/acc_deck_fs_pkg/Templates/template.pptx` and `pipeline_config/pipeline_config/template.pptx` ship as real `.pptx` blobs in the git tree. CI without `git-lfs` access can clone and build without setup. If you ever re-add LFS tracking, restore those two files as regular blobs before pushing or the pipeline will fail at deck-generation time.

## Migrating from v1

The legacy Streamlit packages (`acc_deck_pkg`, `acc_deck_fs_pkg`) live under `src/`. The FastAPI `POST /api/runs` handler in `api/main.py` is the wiring point — it currently transitions through states without invoking the pipeline. To wire it:

1. Import the relevant pipeline module (`src.acc_deck_pkg.pipeline` or `src.acc_deck_fs_pkg.pipeline`) inside the worker thread.
2. Adapt the function signature to accept the `RunRequest` payload from `api/schemas.py`.
3. Have the pipeline write its PPTX to a temp path and stash it on `Run.artifact` so `GET /api/runs/{id}/download` can serve it.

See `streamlit_app.py` in the v1 repo for the original input → pipeline → download wiring.
