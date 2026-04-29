"""Event system for pipeline state changes — used by API/frontend in later phases."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from ..storage.models import PipelineStatus

logger = logging.getLogger(__name__)


@dataclass
class PipelineEvent:
    """An event emitted on every pipeline state transition."""
    old_status: PipelineStatus
    new_status: PipelineStatus
    module_id: str | None
    iteration: int
    timestamp: datetime = field(default_factory=datetime.utcnow)
    data: dict[str, Any] = field(default_factory=dict)


EventCallback = Callable[[PipelineEvent], None]


class EventBus:
    """Simple synchronous event bus for pipeline events.

    In Phase 5 this will be extended with async WebSocket broadcasting.
    """

    def __init__(self) -> None:
        self._subscribers: list[EventCallback] = []
        self._event_log: list[PipelineEvent] = []

    def subscribe(self, callback: EventCallback) -> None:
        self._subscribers.append(callback)

    def emit(self, event: PipelineEvent) -> None:
        self._event_log.append(event)
        for cb in self._subscribers:
            try:
                cb(event)
            except Exception:
                logger.exception("Error in event subscriber")

    @property
    def history(self) -> list[PipelineEvent]:
        return list(self._event_log)
