"""Characterization tests — WebSocket event emission sequence.

Locks down the event channel/type contract that the frontend depends on.
Tests that:
- _emit() pushes correctly shaped payloads to the queue
- _emit_terminal() pushes correctly shaped terminal payloads
- All required fields are present in pipeline events
- Channel names match the frontend subscription contract
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from agent_os.api.websocket import ConnectionManager
from agent_os.config.schema import AgentOSConfig
from agent_os.orchestrator.engine import Orchestrator
from agent_os.storage.models import PipelineStatus


@pytest.fixture()
def config() -> AgentOSConfig:
    return AgentOSConfig(storage={"db_path": ":memory:"})


@pytest.fixture()
def orch(config: AgentOSConfig) -> Orchestrator:
    o = Orchestrator(config)
    o._ws_queue = asyncio.Queue()
    return o


def _drain(queue: asyncio.Queue) -> list[dict[str, Any]]:
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


class TestEmitPipelineEvent:
    def test_emit_pushes_to_queue(self, orch: Orchestrator):
        orch._emit("run_started")
        events = _drain(orch._ws_queue)
        assert len(events) == 1

    def test_event_has_channel_pipeline(self, orch: Orchestrator):
        orch._emit("run_started")
        event = orch._ws_queue.get_nowait()
        assert event["channel"] == "pipeline"

    def test_event_has_sender_orchestrator(self, orch: Orchestrator):
        orch._emit("run_started")
        event = orch._ws_queue.get_nowait()
        assert event["sender"] == "orchestrator"

    def test_event_has_event_type(self, orch: Orchestrator):
        orch._emit("state_changed")
        event = orch._ws_queue.get_nowait()
        assert event["event"] == "state_changed"

    def test_event_has_timestamp(self, orch: Orchestrator):
        orch._emit("run_started")
        event = orch._ws_queue.get_nowait()
        assert "timestamp" in event
        assert event["timestamp"].endswith("Z")

    def test_event_has_pipeline_status(self, orch: Orchestrator):
        orch._emit("run_started")
        event = orch._ws_queue.get_nowait()
        assert "pipeline_status" in event
        assert event["pipeline_status"] == PipelineStatus.IDLE.value

    def test_event_has_current_iteration(self, orch: Orchestrator):
        orch._emit("run_started")
        event = orch._ws_queue.get_nowait()
        assert "current_iteration" in event

    def test_event_includes_extra_data(self, orch: Orchestrator):
        orch._emit("code_generation_started", {"iteration": 3})
        event = orch._ws_queue.get_nowait()
        assert event["iteration"] == 3

    def test_emit_without_queue_is_noop(self, config: AgentOSConfig):
        orch = Orchestrator(config)
        assert orch._ws_queue is None
        orch._emit("run_started")  # should not raise


class TestEmitTerminalEvent:
    def test_terminal_event_has_correct_channel(self, orch: Orchestrator):
        orch._emit_terminal("session_start", "PROMPT_GENERATOR", "pg-1-abc")
        event = orch._ws_queue.get_nowait()
        assert event["channel"] == "terminal:prompt_generator"

    def test_terminal_event_code_gen_channel(self, orch: Orchestrator):
        orch._emit_terminal("line", "CODE_GENERATOR", "cg-1-abc", line="test line")
        event = orch._ws_queue.get_nowait()
        assert event["channel"] == "terminal:code_generator"

    def test_terminal_event_code_reviewer_channel(self, orch: Orchestrator):
        orch._emit_terminal("session_end", "CODE_REVIEWER", "cr-1-abc", exit_code=0)
        event = orch._ws_queue.get_nowait()
        assert event["channel"] == "terminal:code_reviewer"

    def test_terminal_event_has_sender(self, orch: Orchestrator):
        orch._emit_terminal("session_start", "PROMPT_GENERATOR", "pg-1")
        event = orch._ws_queue.get_nowait()
        assert event["sender"] == "prompt_generator"

    def test_terminal_event_has_timestamp(self, orch: Orchestrator):
        orch._emit_terminal("session_start", "CODE_GENERATOR", "cg-1")
        event = orch._ws_queue.get_nowait()
        assert "timestamp" in event

    def test_terminal_payload_has_event_type(self, orch: Orchestrator):
        orch._emit_terminal("session_start", "PROMPT_GENERATOR", "pg-1")
        event = orch._ws_queue.get_nowait()
        assert event["payload"]["event_type"] == "session_start"

    def test_terminal_payload_has_session_id(self, orch: Orchestrator):
        orch._emit_terminal("token", "PROMPT_GENERATOR", "pg-session-123", text="hello")
        event = orch._ws_queue.get_nowait()
        assert event["payload"]["session_id"] == "pg-session-123"

    def test_terminal_payload_kwargs_propagated(self, orch: Orchestrator):
        orch._emit_terminal("line", "CODE_GENERATOR", "cg-1", line="output", stream="stdout")
        event = orch._ws_queue.get_nowait()
        assert event["payload"]["line"] == "output"
        assert event["payload"]["stream"] == "stdout"


class TestConnectionManager:
    def test_connect_and_count(self):
        mgr = ConnectionManager()
        assert mgr.active_count == 0

    def test_disconnect_removes_connection(self):
        mgr = ConnectionManager()
        ws = object()
        mgr._connections.add(ws)
        mgr._subscriptions[ws] = None
        assert mgr.active_count == 1
        mgr.disconnect(ws)
        assert mgr.active_count == 0

    def test_set_filter_subscribes_to_channels(self):
        mgr = ConnectionManager()
        ws = object()
        mgr._connections.add(ws)
        mgr._subscriptions[ws] = None
        mgr.set_filter(ws, ["pipeline", "review"])
        assert mgr._should_deliver(ws, "pipeline") is True
        assert mgr._should_deliver(ws, "terminal:code_generator") is False

    def test_set_filter_wildcard_resets_to_all(self):
        mgr = ConnectionManager()
        ws = object()
        mgr._connections.add(ws)
        mgr._subscriptions[ws] = {"pipeline"}
        mgr.set_filter(ws, ["*"])
        assert mgr._should_deliver(ws, "any_channel") is True

    def test_should_deliver_no_filter(self):
        mgr = ConnectionManager()
        ws = object()
        mgr._connections.add(ws)
        mgr._subscriptions[ws] = None
        assert mgr._should_deliver(ws, "pipeline") is True
        assert mgr._should_deliver(ws, "terminal:anything") is True


class TestEventSequence:
    def test_run_started_is_first_event(self, config: AgentOSConfig):
        orch = Orchestrator(config)
        q: asyncio.Queue = asyncio.Queue()
        orch._ws_queue = q
        # Patch _loop to do nothing so run() only emits run_started without executing steps
        with patch.object(orch, "_loop"):
            orch.run()
        events = _drain(q)
        assert events[0]["event"] == "run_started"
