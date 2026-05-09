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

## Migrating from v1

The legacy Streamlit packages (`acc_deck_pkg`, `acc_deck_fs_pkg`) live under `src/`. The FastAPI `POST /api/runs` handler in `api/main.py` is the wiring point — it currently transitions through states without invoking the pipeline. To wire it:

1. Import the relevant pipeline module (`src.acc_deck_pkg.pipeline` or `src.acc_deck_fs_pkg.pipeline`) inside the worker thread.
2. Adapt the function signature to accept the `RunRequest` payload from `api/schemas.py`.
3. Have the pipeline write its PPTX to a temp path and stash it on `Run.artifact` so `GET /api/runs/{id}/download` can serve it.

See `streamlit_app.py` in the v1 repo for the original input → pipeline → download wiring.
