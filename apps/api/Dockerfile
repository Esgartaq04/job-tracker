# API image. Reads $PORT and runs migrations on boot, so it deploys unchanged to Render,
# Fly, or Cloud Run (README §3, docs/DEPLOYMENT.md).
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so a source-only change doesn't re-resolve the tree.
#
# `anthropic` is a core dependency, so the bare install carries it: every user brings
# their own Claude key, and without the SDK the AI features can't run in the container.
# `[browser]` is deliberately absent — Playwright's download is hundreds of
# megabytes and won't fit a 512 MB instance. Tier 3 gets its own image if it ever ships.
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY scripts ./scripts

# Render, Fly and Cloud Run all set $PORT; the default keeps `docker run` working.
ENV PORT=8000
EXPOSE 8000

# One worker per instance, always. Without Redis the SSE hub and the ingestion thread
# pool live in process memory, so a second worker means a browser connected to worker A
# never sees an ingest running on worker B. Scale by instance, not by worker.
CMD ["sh", "-c", "alembic upgrade head && uvicorn src.main:app --host 0.0.0.0 --port ${PORT}"]
