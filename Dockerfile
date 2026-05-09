# Forecast Accuracy Deck Builder v2 — single-port Docker build.
#
# Build context expected: project root (~/Downloads/ADB-TOOL-v2).
# Two-stage build: Node compiles the Next.js frontend to web/out/, then
# the Python image copies it in alongside the FastAPI BFF and serves the
# whole app on port 8000.

# ── Stage 1: build frontend ───────────────────────────────────────────────
FROM node:20-bookworm-slim AS web

WORKDIR /work
COPY web/package.json web/package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY web ./
# kit/ is already synced into web/kit/ by the host before docker build
# (or run kit/sync.sh inside the image — see ../kit/README.md option 2).
RUN npm run build

# ── Stage 2: runtime ──────────────────────────────────────────────────────
FROM python:3.12-slim

# System deps: Chromium for Selenium SSO (NPD login)
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    curl \
    && rm -rf /var/lib/apt/lists/*

ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api            ./api
COPY src            ./src
COPY pipeline_config ./pipeline_config

# Built frontend lives at /app/web/out/ — api/main.py mounts it at /.
COPY --from=web /work/out ./web/out

RUN mkdir -p /app/Cookies \
    && useradd -m -u 1000 user \
    && chown -R user:user /app
USER user

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
