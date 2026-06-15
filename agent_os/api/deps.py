"""Dependency injection for the Agent OS API.

Provides a shared Orchestrator instance and derived helpers.
"""

from __future__ import annotations

import threading
from pathlib import Path

from ..config.schema import AgentOSConfig
from ..orchestrator.engine import Orchestrator


class _OrchestratorHolder:
    """Singleton container for the Orchestrator instance."""

    def __init__(self) -> None:
        self._orch: Orchestrator | None = None
        self._lock = threading.Lock()
        # Absolute path to the config.yaml that was loaded at startup.
        # None when the orchestrator was initialised in-memory (e.g. tests).
        self.config_path: Path | None = None

    def init(self, config: AgentOSConfig) -> Orchestrator:
        with self._lock:
            if self._orch is None:
                self._orch = Orchestrator(config)
            return self._orch

    @property
    def orchestrator(self) -> Orchestrator:
        with self._lock:
            orch = self._orch
        if orch is None:
            raise RuntimeError("Orchestrator not initialised — call init() first")
        return orch

    def shutdown(self) -> None:
        with self._lock:
            if self._orch is not None:
                self._orch.shutdown()
                self._orch = None
            self.config_path = None


orch_holder = _OrchestratorHolder()


def get_orchestrator() -> Orchestrator:
    """FastAPI dependency — returns the shared Orchestrator."""
    return orch_holder.orchestrator
