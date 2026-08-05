# Ingestion worker. Same source tree as the API, different entrypoint (README §3).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY apps/api/pyproject.toml ./apps/api/
RUN pip install --upgrade pip && pip install ./apps/api

COPY apps/api/src ./apps/api/src
COPY apps/api/alembic.ini ./apps/api/
COPY apps/api/alembic ./apps/api/alembic
COPY apps/worker ./apps/worker

WORKDIR /app/apps/worker
CMD ["arq", "worker.WorkerSettings"]
