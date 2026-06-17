"""Shared fixtures for the Agent OS test suite.

These fixtures are automatically available in all test modules via pytest's
fixture discovery. They provide:
  - db          : fresh in-memory SQLite Database
  - state_mgr   : StateManager backed by in-memory db
  - tmp_config  : AgentOSConfig with a per-test temporary db file
  - app_client  : FastAPI TestClient wired to core orchestrator routes
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Generator

import pytest

from agent_os.config.schema import AgentOSConfig
from agent_os.orchestrator.state import StateManager
from agent_os.storage.database import Database


# ---------------------------------------------------------------------------
# Database / state fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db() -> Generator[Database, None, None]:
    """Fresh in-memory SQLite database, connected and schema-initialised."""
    database = Database(":memory:")
    database.connect()
    yield database
    database.close()


@pytest.fixture()
def state_mgr(db: Database) -> StateManager:
    """StateManager backed by the shared in-memory db fixture."""
    return StateManager(db)


# ---------------------------------------------------------------------------
# Config fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_config(tmp_path: Path) -> AgentOSConfig:
    """AgentOSConfig pointing at a temporary file-based database."""
    db_path = str(tmp_path / "test.db")
    return AgentOSConfig(storage={"db_path": db_path})


# ---------------------------------------------------------------------------
# Database schema-init cache reset (critical for in-memory test isolation)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_db_init_cache():
    """Clear the Database schema-init cache before/after each test.

    The Database class caches which db paths have been schema-initialized in a
    module-level set (_initialized_db_paths). Without clearing this between tests,
    in-memory databases created in subsequent tests skip schema init → empty DB.
    """
    from agent_os.storage import database as db_module
    db_module._initialized_db_paths.clear()
    yield
    db_module._initialized_db_paths.clear()


# ---------------------------------------------------------------------------
# API / HTTP client fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_client(tmp_config: AgentOSConfig):
    """FastAPI TestClient wired to the orchestrator, metrics, and WebSocket routes.

    Yields (client, orchestrator) so tests that need to inspect internal state
    can access the orchestrator directly.

    Ensures the orch_holder is reset before and after each test.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from agent_os.api.deps import orch_holder
    from agent_os.api.routes import metrics, orchestrator, project
    from agent_os.api.websocket import router as ws_router

    # Guarantee a clean slate even if a previous test left the holder dirty.
    orch_holder.shutdown()
    orch = orch_holder.init(tmp_config)

    @asynccontextmanager
    async def noop_lifespan(app):
        yield

    app = FastAPI(lifespan=noop_lifespan)
    app.include_router(orchestrator.router)
    app.include_router(metrics.router)
    app.include_router(project.router)
    app.include_router(ws_router)

    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, orch

    orch_holder.shutdown()
