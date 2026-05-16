# Forecast Accuracy Deck Builder — v2

#### Long story short the whole premise of this architecture came from meeting analysts (and me actually working on the team and suffering thr QC production week slog)

It turns out we already have a proof of truth on the QA site which gets QC'd prior to generating these client pptx files.
However these processes were always either treated in isolation or done by different teams.
This whole pipeline was designed to cut out all this waste by hitting the classic sweetspot of when QA is validated but before being pushed to PROD..(I dealt with this many times in my previous role before monthly database refreshes)
----------------------------------------------------------
#### IPO LOGIC
Input: QA and Prod (last quarters non refreshed data)
Process : Pretty much a comparsion in a YoT% metric (more scalable and client friendly)
Generates Outout: PowerPoint forecast vs actuals accuracy decks from live NPD Future of dashboard data.

------------------------------------------------------------
This is an enhancement on a previously 2x production validation pipeline:

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

The frontend hits the URL in `NEXT_PUBLIC_API_BASE` (committed in `web/.env.development` as `http://localhost:8002` — Next.js auto-loads this in dev). The backend opens CORS to whatever's in `ADB_CORS_ORIGINS` from the project-root `.env` (set to `http://localhost:3002` for dev). Both env vars default to empty so production single-port deploy is same-origin with no CORS surface.

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

The `web/kit/` folder holds the shared UI primitives (Button, Card, AppShell, Wordmark, etc.) used across the app. It's a custom-built kit for rapid internal tool builds, shared across a few sibling tools to keep the look and feel consistent — vendored into this repo as plain source, so `git clone` + `npm install` is everything a new contributor needs. No extra fetch, no private package registry, no submodules. Edit files under `web/kit/` directly; treat it like any other source folder. Improvements you make here are welcome to flow back upstream.

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

## Concurrent users

Up to **3 deck builds** can run at the same time — plenty for a small internal tool. Beyond that, runs queue up and the UI shows position + ETA (projected from the rolling median of recent durations) rather than a frozen spinner. Override the cap with `ADB_MAX_RUN_SLOTS` if you ever need to.

Implementation lives in `api/runs.py`: a `BoundedSemaphore` for the slot cap, per-record locks for clean status snapshots, and a 1-hour idle-TTL reaper that cleans up abandoned runs.

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

**Single replica** — sessions and the run registry live in-process. If the deployment scales to multiple replicas behind a load balancer, sessions break (a poll might hit a replica that didn't kick off the run). Swap `api/sessions.py` and `api/runs.py` to a Redis-backed store before scaling out.

**Run artifacts** — pipelines write `.pptx` / `.xlsx` to `tempfile.mkdtemp(prefix="adb_output_")` under `/tmp`. The 60-min idle TTL on `Run` clears the in-memory record but leaves the temp dir on disk. For long-running pods either mount `/tmp` as an `emptyDir` with a size limit, or extend `api/runs.py`'s reaper to `shutil.rmtree(run.artifact.parent)` on eviction.
