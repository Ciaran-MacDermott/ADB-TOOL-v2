# Forecast Accuracy Deck Builder v2 — single-port Docker build.
#
# Build context expected: project root (~/Downloads/ADB-TOOL-v2).
# Two-stage build: Node compiles the Next.js frontend to web/out/, then
# the Python image copies it in alongside the FastAPI BFF and serves the
# whole app on port 8002.
#
# ─── Deployment model ──────────────────────────────────────────────────
# Build can run on any host with normal egress; the resulting image is
# self-contained and only needs the runtime egress endpoints below.
#
# Build-time egress:
#   - registry-1.docker.io           pulling node:20-bookworm-slim and python:3.12-slim
#   - deb.debian.org / security.*    apt-get for chromium + chromium-driver + curl
#   - registry.npmjs.org             npm ci  (Next.js, React, Tailwind, etc.)
#   - pypi.org / files.pythonhosted  pip install -r requirements.txt
#   - fonts.googleapis.com / gstatic next/font/google downloads Inter at build time
#                                    and inlines it under web/out/_next/static/media/
#                                    so the running container makes ZERO calls to
#                                    Google Fonts.
#
# Runtime egress (must be reachable from the container):
#   - api.groq.com:443      (HTTPS) — LLM provider for brief / fast_writer /
#                                     total_subheader profiles. See
#                                     src/llm/providers/__init__.py.
#   - api.moonshot.ai:443   (HTTPS) — LLM provider for writer / cleanup /
#                                     fs_insight profiles (Kimi K2.6).
#   - openrouter.ai:443     (HTTPS) — registered as a provider but no profile
#                                     currently routes to it; safe to omit.
#   - future-of.npd.com:443     (HTTPS) — NPD External API, prod environment.
#   - future-of-qa.npd.com:443  (HTTPS) — NPD External API, QA environment.
#
# Runtime ingress (inbound to the container):
#   - :8002 (HTTP) — FastAPI BFF + static frontend. Typically sits behind
#                    a TLS-terminating reverse proxy at the cluster edge.

# ── Stage 1: build frontend ───────────────────────────────────────────────
FROM node:20-bookworm-slim AS web

WORKDIR /work
COPY web/package.json web/package-lock.json* ./
# `npm ci` enforces strict lockfile use for reproducible builds.
# Do NOT replace with `npm install`; install can silently update
# transitive versions.
RUN npm ci --no-audit --no-fund

COPY web ./
RUN npm run build

# ── Stage 2: runtime ──────────────────────────────────────────────────────
FROM python:3.12-slim

# System deps: Chromium for Selenium SSO (NPD login). chromium-driver
# is installed via apt so Selenium does not attempt a runtime
# webdriver-manager download (no inbound network needed at runtime).
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    curl \
    && rm -rf /var/lib/apt/lists/*

ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver
# Cookies cache dir — Selenium pickles the 50-min session cookie here so
# subsequent /api/connect calls skip the full SSO flow. Must be writable
# by the container user. Pointed to the dir created + chowned below.
ENV NPD_COOKIES_DIR=/app/Cookies

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

EXPOSE 8002

# --proxy-headers + --forwarded-allow-ips lets uvicorn trust the cluster
# reverse proxy (which terminates TLS) for X-Forwarded-* so the FastAPI
# request.url reflects the public scheme/host. Restrict to internal
# proxy IPs in stricter environments by replacing "*" with that CIDR.
CMD ["uvicorn", "api.main:app", \
     "--host", "0.0.0.0", "--port", "8002", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
