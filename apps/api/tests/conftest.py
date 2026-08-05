import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

# Each test session gets a throwaway SQLite file. Must be set before src.core.config
# is imported anywhere, since Settings is cached.
_tmpdir = tempfile.mkdtemp(prefix="job-tracker-tests-")
os.environ.setdefault("DATABASE_URL", f"sqlite+pysqlite:///{_tmpdir}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.pop("REDIS_URL", None)
os.environ.pop("ANTHROPIC_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

from src.core.db import Base, engine  # noqa: E402
from src.main import app  # noqa: E402
from src.models import User  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Iterator[None]:
    """SQLite (the default) builds the schema straight from the models — fast, and the
    generated `search_vector` column doesn't exist there anyway. Point `DATABASE_URL`
    at Postgres and the suite runs the real migration instead, so the tsvector column,
    the enum, and the partial indexes are all covered."""
    from src.core.config import settings

    if settings.is_sqlite:
        Base.metadata.create_all(engine)
        yield
        Base.metadata.drop_all(engine)
        return

    from alembic.config import Config

    from alembic import command

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    if _has_tables():
        command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield
    command.downgrade(config, "base")


def _has_tables() -> bool:
    from sqlalchemy import inspect

    return "applications" in inspect(engine).get_table_names()


@pytest.fixture(autouse=True)
def _clean_tables() -> Iterator[None]:
    yield
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())


@pytest.fixture(autouse=True)
def enqueued(monkeypatch) -> list:
    """Capture ingestion enqueues instead of running them.

    Background ingestion would otherwise outlive the request under test, reach the real
    internet, and race the table cleanup above. Tests that care about the pipeline call
    it directly (`test_tiers.py`); tests that care about the endpoint assert on this list.
    """
    calls: list = []
    monkeypatch.setattr(
        "src.routers.ingest.queue.enqueue_ingest",
        lambda application_id: calls.append(application_id),
    )
    return calls


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_client(client: TestClient) -> TestClient:
    """A client already registered and carrying a bearer token."""
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "esteven@example.com", "password": "correct-horse-battery"},
    )
    assert response.status_code == 201, response.text
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
    return client


@pytest.fixture
def db_session() -> Iterator:
    from src.core.db import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def user(db_session) -> User:
    from src.core.security import hash_password

    row = User(email="worker@example.com", password_hash=hash_password("x" * 12))
    db_session.add(row)
    db_session.commit()
    return row
