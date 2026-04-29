"""Handler context — shared dependencies injected into all step handlers."""

from __future__ import annotations

from dataclasses import dataclass

from ..comms.bus import AgentCommBus
from ..config.schema import AgentOSConfig
from ..storage.database import Database
from .state import StateManager


@dataclass
class HandlerContext:
    """Shared context passed to every step handler."""
    state_mgr: StateManager
    db: Database
    config: AgentOSConfig
    bus: AgentCommBus
