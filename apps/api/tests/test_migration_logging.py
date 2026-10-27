"""Running the migrations in-process — which the suite does whenever it points at
Postgres — must not switch off the app's own loggers. Alembic's env.py configures
logging from alembic.ini, and `fileConfig` disables every existing logger by default."""

import logging
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from src.core.config import settings

API_ROOT = Path(__file__).resolve().parents[1]
APP_LOGGERS = ("src.services.ai_keys", "src.services.autofill", "arq.worker")
# alembic.ini configures these; restore them so the rest of the session logs as before.
INI_LOGGERS = ("", "sqlalchemy", "alembic")


@pytest.fixture
def restored_logging():
    loggers = [logging.getLogger(name) for name in (*INI_LOGGERS, *APP_LOGGERS)]
    saved = [(lg, lg.handlers[:], lg.level, lg.propagate, lg.disabled) for lg in loggers]
    yield
    for lg, handlers, level, propagate, disabled in saved:
        lg.handlers[:] = handlers
        lg.setLevel(level)
        lg.propagate = propagate
        lg.disabled = disabled


def test_migrating_in_process_leaves_the_app_loggers_on(tmp_path, monkeypatch, restored_logging):
    for name in APP_LOGGERS:
        logging.getLogger(name)  # exist before the migration, as they do in the suite

    monkeypatch.setattr(settings, "database_url", f"sqlite+pysqlite:///{tmp_path / 'm.db'}")
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    command.upgrade(config, "head")

    assert {name: logging.getLogger(name).disabled for name in APP_LOGGERS} == {
        name: False for name in APP_LOGGERS
    }
