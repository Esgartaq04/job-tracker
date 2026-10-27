import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.core import crypto, redact
from src.core.config import settings
from src.routers import (
    ai_key,
    applications,
    auth,
    autofill,
    cover_letters,
    events,
    ingest,
    reminders,
    search,
    stats,
)
from src.services.events import hub
from src.services.ingestion import queue

logging.basicConfig(
    level=logging.INFO,
    format='{"level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
)
redact.install()


@asynccontextmanager
async def lifespan(app: FastAPI):
    crypto.check_configured()
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
    # The SPA reads the .docx download's name from here; cross-origin, it's hidden
    # unless exposed.
    expose_headers=["Content-Disposition"],
)

#: What a validation error may carry that quotes the request back: `input` is the value
#: that failed, and `ctx` can repeat it.
_ECHOES = frozenset({"input", "ctx"})


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI's own 422, except on `/ai-key`, where the input that failed to validate
    can be the key itself (`{"api_key": [KEY]}`, `{"apiKey": KEY}`). There each error
    keeps its type, location and message, and loses what echoes the input."""
    if not request.url.path.rstrip("/").endswith("/ai-key"):
        return await request_validation_exception_handler(request, exc)
    errors = [
        {name: value for name, value in error.items() if name not in _ECHOES}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})


for router in (
    auth.router,
    ai_key.router,
    applications.router,
    ingest.router,
    ingest.application_router,
    cover_letters.router,
    autofill.router,
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
