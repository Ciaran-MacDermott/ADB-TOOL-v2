# Forecast Accuracy Deck Builder — v2

> Long story short, the whole premise of this architecture came from meeting analysts (and me actually working on the team and suffering the QC production week slog).

It turns out we already have a proof of truth on the QA site which gets QC'd prior to generating these client `.pptx` files. However, these processes were always either treated in isolation or done by different teams. This whole pipeline was designed to cut out all this waste by hitting the classic sweet spot of when QA is validated but before being pushed to PROD. (I dealt with this many times in my previous role before monthly database refreshes.)

Also similarly to other analytics automation initiatives I've led, this started as an exe based local solution, ingesting csv/excel files. As ther future of project covers over 25 industries across the globe there were all sorts of formatting inconsistencies to deal with in this pipeline.. It turns out in a similar vein, the web development dashboard team had already dealt with this hurdle years ago, where through cooperating witht hem to develop a pretty sikmple API flow we avoided this data ingestion hurdle and avoided (post-facto) redundant workflows.

---

### IPO logic

- **Input** — QA and Prod (last quarter's non-refreshed data)
- **Process** — pretty much a comparison on a YoT% metric (more scalable and client-friendly)
- **Output** — PowerPoint forecast-vs-actuals accuracy decks from live NPD Future-of dashboard data

---

This is an enhancement on a previously 2x production validation pipeline:

**v2** = same domain logic as the original [ADB-TOOL](https://github.com/Ciaran-MacDermott/ADB-TOOL), rebuilt on a Next.js + FastAPI shape. Streamlit replaced with a Next.js frontend served by the FastAPI BFF on a single port.

## Layout

Standard micro-web-app split: a Python **backend** (FastAPI BFF + pipeline code + tests) and a Next.js **frontend** that static-exports to `frontend/out/`. The Dockerfile bundles both into a single-port image, so production is one process behind one reverse proxy.

```
backend/                Python — FastAPI BFF + pipelines, one process
  api/                  HTTP surface — route handlers, run registry, sessions
  src/
    acc_deck_pkg/       ADB pipeline (general industries)
    acc_deck_fs_pkg/    Foodservice pipeline (food-service-{us,canada,australia})
    llm/                unified LLM client — single seam for every model call
  config/               ADB pipeline assets (template.pptx, prompts, config.json)
  tests/                pytest suite
frontend/               Next.js 15 + React 19 + Tailwind, static-exports to out/
  app/                  Next routes (App Router)
  kit/                  in-tree UI kit (Button, Card, AppShell, …)
  lib/                  BFF client (api.ts)
  public/               static assets (logo)
Dockerfile              two-stage build: frontend/out + backend → single-port image
```

Foodservice keeps its own templates / prompts / images inside `acc_deck_fs_pkg/` rather than under `backend/config/` — see [Two pipelines](#two-pipelines--why-the-adb--foodservice-split) for why. Per-file pointers for common edits are in [Where to refactor X?](#where-to-refactor-x).

## Two pipelines — why the ADB / Foodservice split?

The repo ships **two pipeline packages** because the two decks are
structurally different products that happen to share data plumbing.

| | `acc_deck_pkg` (**ADB**) | `acc_deck_fs_pkg` (**Foodservice**) |
|---|---|---|
| Covers | every industry **except** food-service | `food-service`, `food-service-canada`, `food-service-australia` |
| Slide structure | one accuracy table + per-level rows + LLM narrative | Total / Segments / Dayparts / Service Modes / Food & Bev — country-specific layouts |
| Origin | original ADB-TOOL Streamlit app | separate `dashboard_download_foodservice` Streamlit app, merged in |
| Bundled assets | `backend/config/` (template + prompts) | `acc_deck_fs_pkg/{templates,images,prompts}/` (kept in-package) |
| Entry point | `acc_deck_pkg.main_meta_modes.main(...)` | `acc_deck_fs_pkg.pipeline.run_full_pipeline(...)` |

**Routing** — `backend/api/main.py` dispatches based on industry slug:
`FS_INDUSTRY_IDS` (the three supported foodservice markets) → FS pipeline,
everything else → ADB. Other `food-service-*` slugs (UK, Mexico, …) are
filtered out of the dropdown — they have their own pipelines this app
doesn't implement yet.

**What they share** (so a fix in one place lands in both):

- `acc_deck_pkg.ppt_builder` — chart-drawing primitives, used by both
- `acc_deck_pkg.yoy_transformers` — YoY math (`excel_round`, `yoy_total_from_l2_sum`, …)
- `backend/src/llm/` — the LLM client (see below)

**What they don't share**: NPD data extraction, slide layout, prompts,
templates. A change to FS slide structure does not touch ADB and vice
versa — that's intentional.

## LLM client — `backend/src/llm/`

**One seam for every LLM call in the project.** The pipeline code never
imports `groq`, `requests`, `openai`, or `anthropic` directly — it calls
`llm.complete(profile, messages, ...)` and the `llm` package picks the
provider and applies retries/error mapping.

```
backend/src/llm/
  __init__.py        public surface — `complete()`, `list_profiles()`, etc.
  profiles.py        Profile registry — maps profile name → provider + model + params
  providers/         provider adapters (one file per backend)
    base.py          Provider protocol
    openai_compat.py shared HTTP client for OpenAI-compatible APIs (Groq, Moonshot, OpenRouter)
    moonshot.py      Moonshot-specific wiring (Kimi K2.6)
    internal_stub.py placeholder for the internal-hosting endpoint (not yet wired)
    __init__.py      provider registry — register a new provider here
  retries.py         shared retry policy (`with_retries`)
  errors.py          provider error hierarchy (`ProviderRateLimited`, `ProviderUnavailable`, …)
```

**Profiles currently in use** (see `profiles.py` for the canonical list):

| Profile | Provider | Used by |
|---|---|---|
| `brief`, `fast_writer`, `total_subheader` | Groq | ADB pipeline narrative + summaries |
| `writer`, `cleanup` | Moonshot (Kimi K2.6) | ADB pipeline writer + grammar pass |
| `fs_insight` | Moonshot (Kimi K2.6) | FS pipeline per-slide insights |

**Migrating to an internal LLM endpoint** is a single-file change: wire
`providers/internal_stub.py` to the internal HTTP surface, then point the
relevant profiles at it in `profiles.py`. No pipeline code changes.
Walkthrough in `backend/src/llm/README.md`.

## Where to refactor X?

| To change… | Edit… |
|---|---|
| Add / remove an industry from the dropdown | `backend/api/main.py` (`FS_INDUSTRY_IDS`, `_industry_supported`, `_industry_pipeline`) |
| ADB deck layout / slide structure | `backend/src/acc_deck_pkg/ppt_builder.py` + `slide_insight_adder.py` |
| FS deck layout / slide structure | `backend/src/acc_deck_fs_pkg/pipeline.py` (uses `acc_deck_pkg.ppt_builder`) |
| YoY math (shared) | `backend/src/acc_deck_pkg/yoy_transformers.py` |
| ADB prompts | `backend/config/prompts/*.md` |
| FS prompts | `backend/src/acc_deck_fs_pkg/prompts/*.md` |
| ADB deck template | `backend/config/template.pptx` |
| FS deck template | `backend/src/acc_deck_fs_pkg/templates/template.pptx` |
| Add / edit an LLM profile (model, params) | `backend/src/llm/profiles.py` |
| Add a new LLM provider | drop a file in `backend/src/llm/providers/`, register in `providers/__init__.py` |
| Swap to an internal LLM | wire `backend/src/llm/providers/internal_stub.py`, repoint profiles |
| NPD endpoints / auth | ADB → `backend/src/acc_deck_pkg/api_extractor.py`; FS → `backend/src/acc_deck_fs_pkg/api_extractor_v2.py`; URLs via `NPD_PROD_URL` / `NPD_QA_URL` env |
| Concurrent run cap | env `ADB_MAX_RUN_SLOTS` (default 3); logic in `backend/api/runs.py` |
| UI components (Button, Card, …) | `frontend/kit/components/` |
| Main page / form | `frontend/app/page.tsx` |
| BFF client (fetch wrapper) | `frontend/lib/api.ts` |
| Dev API base URL | `frontend/.env.development` |

## Dev

```bash
# Backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.api.main:app --reload --port 8002

# Frontend (separate terminal)
cd frontend
npm install
npm run dev          # Next on :3002
```

The frontend hits the URL in `NEXT_PUBLIC_API_BASE` (committed in `frontend/.env.development` as `http://localhost:8002` — Next.js auto-loads this in dev). The backend opens CORS to whatever's in `ADB_CORS_ORIGINS` from the project-root `.env` (set to `http://localhost:3002` for dev). Both env vars default to empty so production single-port deploy is same-origin with no CORS surface.

Ports 3002 / 8002 are chosen to avoid clashing with other local Next + FastAPI projects that run on the defaults 3000 / 8000.

Copy `.env.example` to `.env` and fill in the values you need (NPD credentials, LLM provider keys). `.env` is gitignored — never commit real secrets.

## Production build

```bash
cd frontend && npm run build              # produces frontend/out/
uvicorn backend.api.main:app --port 8002  # serves API + frontend/out at /
```

Or via Docker:

```bash
docker build -t adb-tool-v2 .
docker run -p 8002:8002 --env-file .env adb-tool-v2
```

## UI components — `frontend/kit/`

The `frontend/kit/` folder holds the shared UI primitives (Button, Card, AppShell, Wordmark, etc.) used across the app. It's a custom-built kit for rapid internal tool builds, shared across a few sibling tools to keep the look and feel consistent — vendored into this repo as plain source, so `git clone` + `npm install` is everything a new contributor needs. No extra fetch, no private package registry, no submodules. Edit files under `frontend/kit/` directly; treat it like any other source folder. Improvements you make here are welcome to flow back upstream.

The kit currently carries Circana branding — the logo (`frontend/public/Circana_logo.png`), the brand palette in `frontend/kit/tailwind-preset.ts`, and the design tokens in `frontend/kit/styles/circana.css` and `primitives.css`. The `Wordmark` component defaults to the Circana logo, and the generated deck output is intentionally Circana-styled. If you ever want a brand-neutral fork, the swap surface is small: replace the logo asset, retheme the Tailwind preset, and the two CSS token files.

## Network policy

**Build environment** — needs egress to:

| Endpoint | Port | Purpose |
|---|---|---|
| `registry-1.docker.io` | 443 | Pull `node:20-bookworm-slim` and `python:3.12-slim` base images |
| `deb.debian.org`, `security.debian.org` | 443 | apt: chromium, chromium-driver, curl |
| `registry.npmjs.org` | 443 | `npm ci` for the Next.js build |
| `pypi.org`, `files.pythonhosted.org` | 443 | `pip install -r requirements.txt` |
| `fonts.googleapis.com`, `fonts.gstatic.com` | 443 | `next/font/google` downloads Inter at build time and inlines it under `frontend/out/_next/static/media/` — runtime makes ZERO calls to Google Fonts |

CI behind a restricted network can substitute internal registry mirrors as needed.

**Runtime egress** (the container must be able to reach):

| Endpoint | Port | Required when | Where to swap |
|---|---|---|---|
| `api.groq.com` | 443 | Today (LLM provider for `brief`, `fast_writer`, `total_subheader` profiles) | `backend/src/llm/profiles.py` |
| `api.moonshot.ai` | 443 | Today (Kimi K2.6 — `writer`, `cleanup`, `fs_insight` profiles) | `backend/src/llm/profiles.py` |
| `openrouter.ai` | 443 | Registered as a provider but no profile routes here — safe to omit | `backend/src/llm/providers/__init__.py` |
| `future-of.npd.com` | 443 | NPD External API, prod | env: `NPD_PROD_URL` |
| `future-of-qa.npd.com` | 443 | NPD External API, QA | env: `NPD_QA_URL` |

If `backend/src/llm/providers/internal_stub.py` is later wired to an internal LLM endpoint, the three external LLM domains can be dropped from the runtime allowlist.

**Runtime ingress (inbound to the container):**

| Port | Protocol | Purpose |
|---|---|---|
| `8002` | HTTP | FastAPI BFF — `/api/*` JSON + Next.js static export at `/`. Sits behind a TLS-terminating reverse proxy in production. |

**Source-of-truth files** (read these to draft firewall rules — they're the only places network endpoints are declared):

- `backend/src/llm/providers/__init__.py` — every LLM URL the app can reach
- `backend/src/acc_deck_pkg/api_extractor.py` and `backend/src/acc_deck_fs_pkg/api_extractor_v2.py` — NPD endpoints
- `Dockerfile` — build-time + runtime port summary at the top

**Templates are committed as regular binaries**, not LFS — both `backend/src/acc_deck_fs_pkg/templates/template.pptx` and `backend/config/template.pptx` ship as real `.pptx` blobs in the git tree. CI without `git-lfs` access can clone and build without setup. If you ever re-add LFS tracking, restore those two files as regular blobs before pushing or the pipeline will fail at deck-generation time.

## Concurrent users

Up to **3 deck builds** can run at the same time — plenty for a small internal tool. Beyond that, runs queue up and the UI shows position + ETA (projected from the rolling median of recent durations) rather than a frozen spinner. Override the cap with `ADB_MAX_RUN_SLOTS` if you ever need to.

Implementation lives in `backend/api/runs.py`: a `BoundedSemaphore` for the slot cap, per-record locks for clean status snapshots, and a 1-hour idle-TTL reaper that cleans up abandoned runs.

## How a run flows end-to-end

`POST /api/connect` runs Selenium SSO against prod + qa in parallel (cached cookies short-circuit when fresh), pulls the industry list from `/api/ext/industries`, and stashes both `requests.Session` objects + the industries on an in-memory `Session` keyed by an opaque token. `GET /api/industries` returns that list filtered to supported markets and tagged `pipeline: "adb" | "fs"`. `GET /api/industries/{slug}/levels` does a single forecast fetch to derive level1 filter values + level columns for the ADB pipeline (foodservice skips this).

`POST /api/runs` returns a `run_id` immediately and spawns a worker thread that acquires one of `RUN_SLOTS` (default 3) and dispatches to `acc_deck_pkg.main_meta_modes.main(...)` or `acc_deck_fs_pkg.pipeline.run_full_pipeline(...)` based on the industry's pipeline tag. The worker installs a per-thread stdout tee so every `print()` from inside the pipeline (Selenium login lines, NPD HTTP responses, GPT-brief / Kimi-write banners, per-category insights) appends to `Run.logs`. The frontend polls `GET /api/runs/{id}` every 1s — the response includes the last 200 log lines, current step, queue position+ETA when queued, and elapsed time. When state turns `done`, `GET /api/runs/{id}/download` serves the `.pptx` and (for ADB) `/download/xlsx` serves the insights workbook. `POST /api/runs/{id}/cancel` sets a `threading.Event` the pipeline checks at safe points.

### Session isolation

State splits across three places so each is scoped where it makes sense:

- **`sessionStorage`** — `{token, username}`, browser-window-local. Surviving a Cmd+R in the same tab keeps a 10–15 min run alive, but a **fresh tab / window / browser** opens to the Connect form. Closes the "Bob walks up to the URL on a shared machine and sees Alice's session" hole. (AIC's URL-token pattern is the other end of this dial — shareable, but the token rides in every link; this app doesn't need that, only `?run=<id>` does.)
- **URL `?run=<id>`** — per-tab. Two tabs = two independent runs, each refresh-safe.
- **Server** — per-user Selenium cookie cache (`npd_cookies_<env>_<sha256(username)[:12]>.pkl`) so a second user can't short-circuit SSO and inherit the first user's NPD session.

A 15-min idle timer revokes the server session and clears the stash if there's no input — paused while a run is queued/running so a long build never gets killed by silence.

## Walled-garden deploy

The image is self-contained — `docker build` once, ship the resulting artifact into the walled garden, run with env injection. The runtime knobs:

| Env var | Purpose | Default |
|---|---|---|
| `NPD_PROD_URL`, `NPD_QA_URL` | NPD External API base URLs | (must set) |
| `NPD_API_PATH_INDUSTRIES`, `NPD_API_PATH_FORECAST` | Endpoint suffixes | sensible literals — leave alone |
| `GROQ_API_KEY`, `MOONSHOT_API_KEY` | LLM providers (until the internal-LLM stub is wired) | (must set) |
| `CHROME_BIN`, `CHROMEDRIVER_PATH` | Chromium + chromedriver paths inside the container | set by Dockerfile |
| `NPD_COOKIES_DIR` | Where the Selenium 50-min cookie pickle is cached. Must be writable by the container user | `/app/Cookies` (Dockerfile) |
| `ADB_MAX_RUN_SLOTS` | Concurrent-deck cap (BoundedSemaphore) | `3` |
| `ADB_CORS_ORIGINS` | Comma-separated CORS allow-list. Empty in prod (same-origin); set to `http://localhost:3002` in dev | empty |
| `NEXT_PUBLIC_API_BASE` | Frontend API base. Empty in prod (relative URLs, same-origin); `http://localhost:8002` in dev | empty (build-time) |

The Dockerfile starts uvicorn with `--proxy-headers --forwarded-allow-ips=*` so the cluster's TLS-terminating reverse proxy can pass `X-Forwarded-*` headers (scheme/host) for correct URL generation. Restrict the allowed IPs from `*` to the proxy's CIDR in stricter environments.

**Single replica** — sessions and the run registry live in-process. If the deployment scales to multiple replicas behind a load balancer, sessions break (a poll might hit a replica that didn't kick off the run). Swap `backend/api/sessions.py` and `backend/api/runs.py` to a Redis-backed store before scaling out.

**Run artifacts** — pipelines write `.pptx` / `.xlsx` to `tempfile.mkdtemp(prefix="adb_output_")` under `/tmp`. The 60-min idle TTL on `Run` clears the in-memory record but leaves the temp dir on disk. For long-running pods either mount `/tmp` as an `emptyDir` with a size limit, or extend `backend/api/runs.py`'s reaper to `shutil.rmtree(run.artifact.parent)` on eviction.
