"""Orchestrator state management — persistence, transitions, and recovery."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable, Optional

from ..storage.database import Database
from ..storage.models import PipelineState, PipelineStatus

logger = logging.getLogger(__name__)

# Valid state transitions: {current_state: [allowed_next_states]}
TRANSITIONS: dict[PipelineStatus, list[PipelineStatus]] = {
    PipelineStatus.IDLE: [
        PipelineStatus.LOADING_REQUIREMENTS,
        PipelineStatus.FAILED,
    ],
    PipelineStatus.LOADING_REQUIREMENTS: [
        PipelineStatus.PROMPT_GENERATION,
        PipelineStatus.FAILED,
    ],
    PipelineStatus.PROMPT_GENERATION: [
        PipelineStatus.HITL_PROMPT_REVIEW,
        PipelineStatus.FAILED,
    ],
    PipelineStatus.HITL_PROMPT_REVIEW: [
        PipelineStatus.CODE_GENERATION,
        PipelineStatus.PROMPT_GENERATION,
        PipelineStatus.FAILED,
    ],
    PipelineStatus.CODE_GENERATION: [
        PipelineStatus.CODE_REVIEW,
        PipelineStatus.FAILED,
    ],
    PipelineStatus.CODE_REVIEW: [
        PipelineStatus.HITL_REVIEW_DECISION,
        PipelineStatus.CODE_GENERATION,
        PipelineStatus.FAILED,
    ],
    PipelineStatus.HITL_REVIEW_DECISION: [
        PipelineStatus.PROMPT_GENERATION,
        PipelineStatus.PIPELINE_COMPLETE,
        PipelineStatus.FAILED,
    ],
    # --- stub entries for removed states kept here temporarily ---
    PipelineStatus.PIPELINE_COMPLETE: [
    ],
    PipelineStatus.FAILED: [
        PipelineStatus.IDLE,
        PipelineStatus.PROMPT_GENERATION,
        PipelineStatus.CODE_GENERATION,
        PipelineStatus.CODE_REVIEW,
    ],
}


class InvalidTransitionError(Exception):
    pass


class StateManager:
    """Manages pipeline state transitions with persistence and validation."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._listeners: list[Callable[[PipelineStatus, PipelineStatus, PipelineState], None]] = []

    @property
    def state(self) -> PipelineState:
        return self._db.get_pipeline_state()

    @property
    def current_status(self) -> PipelineStatus:
        return self.state.pipeline_status

    def on_transition(
        self, callback: Callable[[PipelineStatus, PipelineStatus, PipelineState], None]
    ) -> None:
        """Register a listener called on every state transition."""
        self._listeners.append(callback)

    def transition_to(
        self,
        new_status: PipelineStatus,
        iteration: Optional[int] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> PipelineState:
        """Transition the pipeline to a new state. Validates the transition is allowed."""
        current = self.state
        old_status = current.pipeline_status

        allowed = TRANSITIONS.get(old_status, [])
        if new_status not in allowed:
            raise InvalidTransitionError(
                f"Cannot transition from {old_status.value} to {new_status.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )

        extra_meta: dict = {}
        if new_status == PipelineStatus.FAILED:
            extra_meta["pre_failure_status"] = old_status.value
        new_state = PipelineState(
            current_iteration=iteration if iteration is not None else current.current_iteration,
            pipeline_status=new_status,
            last_checkpoint=datetime.utcnow(),
            metadata={**current.metadata, **(metadata or {}), **extra_meta},
        )

        self._db.save_pipeline_state(new_state)

        logger.info("State transition: %s → %s", old_status.value, new_status.value)

        for listener in self._listeners:
            try:
                listener(old_status, new_status, new_state)
            except Exception:
                logger.exception("Error in state transition listener")

        return new_state

    def reset(self) -> PipelineState:
        """Reset pipeline to IDLE state."""
        new_state = PipelineState()
        self._db.save_pipeline_state(new_state)
        logger.info("Pipeline state reset to IDLE")
        return new_state

    def update_metadata(self, metadata: dict[str, Any]) -> None:
        """Update pipeline metadata without changing state."""
        current = self.state
        new_state = current.model_copy(update={"metadata": metadata})
        self._db.save_pipeline_state(new_state)

    def is_hitl_gate(self) -> bool:
        """Check if the current state is a human-in-the-loop gate."""
        return self.current_status in {
            PipelineStatus.HITL_PROMPT_REVIEW,
            PipelineStatus.HITL_REVIEW_DECISION,
        }

    def can_resume_from(self, status: PipelineStatus) -> bool:
        """Check if the given status is one we can resume from after a crash."""
        # We can resume from any non-terminal state
        return status not in {PipelineStatus.PIPELINE_COMPLETE, PipelineStatus.IDLE}
