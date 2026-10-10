# syntax=docker/dockerfile:1.7
# AabFlow images. Targets:
#   dev      Python 3.11 env from uv.lock; source is bind-mounted by compose (api service)
#   web-dev  Node 24 with web/node_modules from package-lock.json (web service)
#   app      frozen demo image: Python env + API source + compiled frontend (demo service)
#   e2e      Playwright browsers + web test deps (e2e service)
# The vision env (Delineate Anything) is separate: docker/vision.Dockerfile.

ARG PYTHON_IMAGE=python:3.11-slim-trixie
ARG NODE_IMAGE=node:24-trixie-slim
ARG PLAYWRIGHT_IMAGE=mcr.microsoft.com/playwright:v1.63.0-noble
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.14

FROM ${UV_IMAGE} AS uv

# ---------------------------------------------------------------- python
FROM ${PYTHON_IMAGE} AS python-base
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=300 \
    UV_PYTHON_DOWNLOADS=never \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app/api \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 make curl git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /uvx /usr/local/bin/
WORKDIR /app

FROM python-base AS python-deps
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    HOME=/root uv sync --frozen --no-install-project --no-dev

FROM python-deps AS dev
RUN --mount=type=cache,target=/root/.cache/uv \
    HOME=/root uv sync --frozen --no-install-project
CMD ["uvicorn", "aabflow.main:app", "--app-dir", "api", "--reload", "--host", "0.0.0.0", "--port", "8000"]

# ---------------------------------------------------------------- web
FROM ${NODE_IMAGE} AS web-dev
ARG HOST_UID=1000
ARG HOST_GID=1000
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci \
 && chown -R ${HOST_UID}:${HOST_GID} /app/web/node_modules
ENV HOME=/tmp
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

FROM web-dev AS web-build
# Optional display-only Esri basemap key (docs/IMAGERY.md); compose passes it from .env.
# It ends up in the browser bundle by design, so restrict it to Basemaps in the ArcGIS dashboard.
ARG VITE_ARCGIS_KEY=
ENV VITE_ARCGIS_KEY=$VITE_ARCGIS_KEY
COPY web/ ./
COPY contracts/ /app/contracts/
RUN npm run build

# ---------------------------------------------------------------- laptop backend (no frontend or source bind mount)
FROM python-deps AS backend
COPY api ./api
COPY scripts ./scripts
COPY vision/configs ./vision/configs
COPY vision/*.py ./vision/
EXPOSE 8000
# Exactly one API process owns the SQLite job dispatcher. No reload during development.
CMD ["uvicorn", "aabflow.main:app", "--app-dir", "api", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

# ---------------------------------------------------------------- demo
FROM python-deps AS app
COPY api ./api
COPY scripts ./scripts
COPY --from=web-build /app/web/dist ./web/dist
EXPOSE 8000
CMD ["uvicorn", "aabflow.main:app", "--app-dir", "api", "--host", "0.0.0.0", "--port", "8000"]

# ---------------------------------------------------------------- e2e
FROM ${PLAYWRIGHT_IMAGE} AS e2e
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
ENV HOME=/tmp
