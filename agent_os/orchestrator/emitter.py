"""WebSocket event emitter — extracted from Orchestrator (Phase 8.1).

Handles pushing pipeline and terminal events onto the asyncio broadcast queue
consumed by the WebSocket layer.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
from datetime import timezone as _tz
import logging
from typing import Any, Optional

from ..constants import EventChannel

logger = logging.getLogger(__name__)


class WebSocketEmitter:
    """Pushes pipeline and terminal events to the WS broadcast queue."""

    def __init__(self, state_mgr: Any) -> None:
        self._state_mgr = state_mgr
        self._ws_queue: Optional[asyncio.Queue] = None

    def set_ws_queue(self, queue: asyncio.Queue) -> None:
        """Inject the asyncio broadcast queue from the API layer."""
        self._ws_queue = queue

    @property
    def ws_queue(self) -> Optional[asyncio.Queue]:
        return self._ws_queue

    def emit(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Push a pipeline event onto the WebSocket broadcast queue (non-blocking)."""
        if self._ws_queue is None:
            return
        payload = {
            "channel": EventChannel.PIPELINE,
            "sender": "orchestrator",
            "event": event_type,
            "timestamp": _dt.datetime.now(_tz.utc).isoformat() + "Z",
            "pipeline_status": self._state_mgr.current_status.value,
            "current_iteration": self._state_mgr.state.current_iteration,
            **(data or {}),
        }
        try:
            self._ws_queue.put_nowait(payload)
        except Exception:
            logger.warning("WS pipeline event dropped (queue full/closed): %s", event_type)

    def emit_terminal(
        self,
        event_type: str,
        agent_post: str,
        session_id: str,
        **kwargs: Any,
    ) -> None:
        """Push a terminal_output channel event so the frontend terminal grid
        receives structured session_start / line / session_end events."""
        if self._ws_queue is None:
            return
        payload = {
            "channel": f"terminal:{agent_post.lower()}",
            "sender": agent_post.lower(),
            "timestamp": _dt.datetime.now(_tz.utc).isoformat() + "Z",
            "payload": {
                "event_type": event_type,
                "agent_post": agent_post,
                "session_id": session_id,
                **kwargs,
            },
        }
        try:
            self._ws_queue.put_nowait(payload)
        except Exception:
            logger.warning(
                "WS terminal event dropped (queue full/closed): %s/%s",
                agent_post,
                event_type,
            )
