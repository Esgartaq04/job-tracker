import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import settings
from src.routers import applications, auth, events, ingest, reminders, search, stats
from src.services.events import hub
from src.services.ingestion import queue

logging.basicConfig(
    level=logging.INFO,
    format='{"level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The SSE hub needs the running loop so background threads can publish into it.
    hub.bind_loop(asyncio.get_running_loop())
    yield
    queue.shutdown()


app = FastAPI(
    title="Job & Internship Application Tracker",
    version="0.1.0",
    description="Paste a posting URL, track the application on a Kanban board.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (
    auth.router,
    applications.router,
    ingest.router,
    ingest.application_router,
    stats.router,
    reminders.router,
    search.router,
    events.router,
):
    app.include_router(router, prefix=settings.api_prefix)


@app.get("/healthz", tags=["ops"])
def healthz() -> dict:
    return {"status": "ok", "environment": settings.environment}


@app.get("/readyz", tags=["ops"])
def readyz() -> dict:
    """Readiness includes the database — a deploy with an unmigrated DB isn't ready."""
    from sqlalchemy import text

    from src.core.db import engine

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ready"}
