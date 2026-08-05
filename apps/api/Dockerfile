# Cloud Run image for the API (README §3).
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so a source-only change doesn't re-resolve the tree.
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY scripts ./scripts

# Cloud Run sets $PORT; default keeps `docker run` working.
ENV PORT=8000
EXPOSE 8000

# One worker per instance: Cloud Run scales by instance, and the SSE hub is per-process.
CMD ["sh", "-c", "alembic upgrade head && uvicorn src.main:app --host 0.0.0.0 --port ${PORT}"]
