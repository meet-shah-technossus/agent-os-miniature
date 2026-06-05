"""Pipeline service — business logic for pipeline start/stop/retry.

Extracted from route handlers to enable testing without HTTP layer.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from ..storage.models import PipelineStatus

logger = logging.getLogger(__name__)

# States that indicate the pipeline is actively running.
RUNNING_STATES = frozenset({
    PipelineStatus.LOADING_REQUIREMENTS,
    PipelineStatus.PROMPT_GENERATION,
    PipelineStatus.CODE_GENERATION,
    PipelineStatus.CODE_REVIEW,
    PipelineStatus.ANALYSING_DEPENDENCIES,
    PipelineStatus.QUEUE_READY,
    PipelineStatus.STORY_PROMPT_GENERATION,
    PipelineStatus.STORY_CODE_GENERATION,
    PipelineStatus.STORY_CODE_REVIEW,
})

_start_lock = threading.Lock()


class PipelineAlreadyRunningError(Exception):
    """Raised when a start is attempted while the pipeline is active."""


class PipelineService:
    """Service layer for pipeline orchestration actions."""

    def __init__(self, orchestrator: Any) -> None:
        self._orch = orchestrator

    def start(self) -> str:
        """Start or resume the pipeline.

        Returns:
            A message describing the action taken.

        Raises:
            PipelineAlreadyRunningError: If pipeline is in a running state.
        """
        with _start_lock:
            status = self._orch.state_mgr.current_status

            if status in RUNNING_STATES:
                raise PipelineAlreadyRunningError("Pipeline is already running")

            if status in (PipelineStatus.PIPELINE_COMPLETE, PipelineStatus.FAILED):
                self._orch.reset()
            elif status == PipelineStatus.CODE_GEN_FAILED:
                ok = self._orch.retry_code_generator()
                if ok:
                    return "Code generation retry started"

            t = threading.Thread(target=self._orch.run, daemon=True, name="orchestrator-start")
            t.start()

        return "Pipeline started"

    def stop(self) -> str:
        """Request pipeline stop."""
        self._orch.stop()
        return "Stop requested"

    def reset(self) -> str:
        """Reset pipeline to IDLE."""
        self._orch.reset()
        return "Pipeline reset"
