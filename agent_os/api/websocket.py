"""WebSocket bridge — streams AgentCommBus messages to connected clients.

Each WebSocket client receives all CommBus messages as JSON. Clients can
optionally send a JSON payload ``{"subscribe": ["channel1", "channel2"]}``
to filter which channels they receive. By default all channels are forwarded.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..comms.channels import Channel
from ..comms.messages import AgentMessage
from .deps import get_orchestrator

logger = logging.getLogger(__name__)
router = APIRouter()


class ConnectionManager:
    """Manages active WebSocket connections and channel filters."""

    def __init__(self) -> None:
        self._connections: dict[WebSocket, set[str]] = {}

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        # Default: subscribe to all channels
        self._connections[ws] = {ch.value for ch in Channel}

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.pop(ws, None)

    def set_filter(self, ws: WebSocket, channels: list[str]) -> None:
        valid = {ch.value for ch in Channel}
        self._connections[ws] = {c for c in channels if c in valid}

    async def broadcast(self, message: dict[str, Any]) -> None:
        channel = message.get("channel", "")
        dead: list[WebSocket] = []
        for ws, channels in self._connections.items():
            if channel in channels:
                try:
                    await ws.send_json(message)
                except Exception:
                    dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    @property
    def active_count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()

# Asyncio queue for bridging sync CommBus callbacks → async WebSocket sends
_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()


def _bus_callback(message: AgentMessage) -> None:
    """CommBus subscriber callback — pushes message into asyncio queue."""
    data = message.model_dump(mode="json")
    # Convert channel enum to string value
    if hasattr(data.get("channel"), "value"):
        data["channel"] = data["channel"].value
    try:
        _queue.put_nowait(data)
    except Exception:
        logger.warning("WebSocket bridge queue full, dropping message")


def _setup_bus_subscriptions() -> None:
    """Subscribe to all CommBus channels so messages flow into the WS bridge."""
    orch = get_orchestrator()
    for channel in Channel:
        orch.bus.subscribe(channel, _bus_callback)


async def _broadcast_worker() -> None:
    """Background task: drains the queue and broadcasts to WebSocket clients."""
    while True:
        msg = await _queue.get()
        await manager.broadcast(msg)


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            data = await ws.receive_text()
            try:
                parsed = json.loads(data)
                if "subscribe" in parsed and isinstance(parsed["subscribe"], list):
                    manager.set_filter(ws, parsed["subscribe"])
            except (json.JSONDecodeError, KeyError):
                pass
    except WebSocketDisconnect:
        manager.disconnect(ws)
