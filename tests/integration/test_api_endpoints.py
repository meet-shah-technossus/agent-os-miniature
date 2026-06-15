"""Integration tests for the Agent OS REST API endpoints.

Uses FastAPI's TestClient to exercise the real route handlers against a
fresh in-memory database. No subprocesses or external services are started.
"""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_os.api.deps import orch_holder
from agent_os.api.routes import metrics, orchestrator, project
from agent_os.api.websocket import router as ws_router
from agent_os.config.schema import AgentOSConfig
from agent_os.storage.models import PipelineStatus


# ---------------------------------------------------------------------------
# Fixture — isolated FastAPI app per test
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path):
    """TestClient wired to orchestrator + metrics + project routes."""
    db_path = str(tmp_path / "test.db")
    config = AgentOSConfig(storage={"db_path": db_path})

    orch_holder.shutdown()
    orch_holder.init(config)

    @asynccontextmanager
    async def noop_lifespan(app):
        yield

    app = FastAPI(lifespan=noop_lifespan)
    app.include_router(orchestrator.router)
    app.include_router(metrics.router)
    app.include_router(project.router)
    app.include_router(ws_router)

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    orch_holder.shutdown()


# ---------------------------------------------------------------------------
# Orchestrator status
# ---------------------------------------------------------------------------


class TestOrchestratorStatus:
    def test_get_status_returns_200(self, client):
        resp = client.get("/api/orchestrator/status")
        assert resp.status_code == 200

    def test_initial_status_is_idle(self, client):
        data = client.get("/api/orchestrator/status").json()
        assert data["pipeline_status"] == "IDLE"

    def test_status_has_required_fields(self, client):
        data = client.get("/api/orchestrator/status").json()
        assert "pipeline_status" in data
        assert "current_iteration" in data
        assert "is_hitl_gate" in data
        assert "last_checkpoint" in data

    def test_initial_is_not_hitl_gate(self, client):
        data = client.get("/api/orchestrator/status").json()
        assert data["is_hitl_gate"] is False

    def test_initial_iteration_is_zero(self, client):
        data = client.get("/api/orchestrator/status").json()
        assert data["current_iteration"] == 0


# ---------------------------------------------------------------------------
# Pipeline start
# ---------------------------------------------------------------------------


class TestPipelineStart:
    def test_start_returns_200(self, client):
        with patch("agent_os.services.pipeline_service.threading.Thread") as mock_thread:
            mock_thread.return_value.start = lambda: None
            resp = client.post("/api/orchestrator/start")
        assert resp.status_code == 200

    def test_start_response_has_approved_true(self, client):
        with patch("agent_os.services.pipeline_service.threading.Thread") as mock_thread:
            mock_thread.return_value.start = lambda: None
            data = client.post("/api/orchestrator/start").json()
        assert data["approved"] is True

    def test_start_after_complete_resets_pipeline(self, client):
        """Starting from PIPELINE_COMPLETE should reset and re-start."""
        orch = orch_holder.orchestrator
        # Manually drive state to PIPELINE_COMPLETE via state_mgr
        orch.state_mgr.transition_to(PipelineStatus.LOADING_REQUIREMENTS)
        orch.state_mgr.transition_to(PipelineStatus.PROMPT_GENERATION)
        orch.state_mgr.transition_to(PipelineStatus.HITL_PROMPT_REVIEW)
        orch.state_mgr.transition_to(PipelineStatus.CODE_GENERATION)
        orch.state_mgr.transition_to(PipelineStatus.CODE_REVIEW)
        orch.state_mgr.transition_to(PipelineStatus.PIPELINE_COMPLETE)

        with patch("agent_os.services.pipeline_service.threading.Thread") as mock_thread:
            mock_thread.return_value.start = lambda: None
            resp = client.post("/api/orchestrator/start")
        assert resp.status_code == 200
        # After reset + start the state should be back to IDLE (reset happened)
        # The thread was mocked so it didn't advance the state further
        status = orch.state_mgr.current_status
        assert status == PipelineStatus.IDLE


# ---------------------------------------------------------------------------
# Approve prompt
# ---------------------------------------------------------------------------


class TestApprovePrompt:
    def test_approve_prompt_when_not_at_gate_returns_409(self, client):
        """approve-prompt must return 409 when not at HITL_PROMPT_REVIEW."""
        resp = client.post("/api/orchestrator/approve-prompt", json={})
        assert resp.status_code == 409

    def test_approve_prompt_body_is_optional(self, client):
        """Sending no body should not raise a 422."""
        resp = client.post("/api/orchestrator/approve-prompt", json={})
        # 409 is expected (not at gate) not 422 (validation error)
        assert resp.status_code != 422


# ---------------------------------------------------------------------------
# Approve review
# ---------------------------------------------------------------------------


class TestApproveReview:
    def test_approve_review_when_not_at_gate_returns_409(self, client):
        resp = client.post("/api/orchestrator/approve-review")
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Pause / stop (smoke tests)
# ---------------------------------------------------------------------------


class TestPipelineControl:
    def test_pause_returns_200(self, client):
        resp = client.post("/api/orchestrator/pause")
        assert resp.status_code == 200

    def test_stop_when_not_in_codegen_returns_409(self, client):
        resp = client.post("/api/orchestrator/stop")
        assert resp.status_code == 409

    def test_stop_rollback_when_not_stopped_returns_409(self, client):
        resp = client.post("/api/orchestrator/stop-rollback")
        assert resp.status_code == 409

    def test_stop_continue_when_not_stopped_returns_409(self, client):
        resp = client.post("/api/orchestrator/stop-continue")
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Iterations endpoint
# ---------------------------------------------------------------------------


class TestIterations:
    def test_get_iterations_returns_200(self, client):
        resp = client.get("/api/orchestrator/iterations")
        assert resp.status_code == 200

    def test_initial_iterations_list_is_empty(self, client):
        data = client.get("/api/orchestrator/iterations").json()
        assert "iterations" in data
        assert data["iterations"] == []


# ---------------------------------------------------------------------------
# Metrics endpoint
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_metrics_returns_200(self, client):
        resp = client.get("/api/metrics")
        assert resp.status_code == 200

    def test_metrics_has_required_fields(self, client):
        data = client.get("/api/metrics").json()
        assert "total_iterations" in data
        assert "pipeline_status" in data

    def test_initial_total_iterations_is_zero(self, client):
        data = client.get("/api/metrics").json()
        assert data["total_iterations"] == 0


# ---------------------------------------------------------------------------
# Project info endpoint
# ---------------------------------------------------------------------------


class TestProjectInfo:
    def test_project_info_returns_200(self, client):
        resp = client.get("/api/project/info")
        assert resp.status_code == 200

    def test_project_info_has_expected_fields(self, client):
        data = client.get("/api/project/info").json()
        assert "name" in data
        assert "exists" in data


# ---------------------------------------------------------------------------
# Approve-gate (backward-compat endpoint)
# ---------------------------------------------------------------------------


class TestApproveGate:
    def test_approve_gate_not_at_gate_returns_409(self, client):
        resp = client.post("/api/orchestrator/approve-gate", json={})
        assert resp.status_code == 409
