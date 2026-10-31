# syntax=docker/dockerfile:1
# Build context: repo root.  docker build -f infra/docker/api.Dockerfile .
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
WORKDIR /app

# Dependencies first (cached layer). Production image excludes the dev group.
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY apps/api/ ./
# Shared data (material library, fixtures); Settings.data_dir falls back to /data here.
COPY data/ /data/

RUN useradd --create-home --uid 10001 app
USER app
EXPOSE 8000

# Apply migrations, then serve. (Single replica; move migrations to a release step when scaling.)
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
