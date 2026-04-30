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
    ],
    PipelineStatus.LOADING_REQUIREMENTS: [
        PipelineStatus.MODULE_PLANNING,
        PipelineStatus.FAILED,
    ],
    PipelineStatus.MODULE_PLANNING: [
        PipelineStatus.HITL_1_MODULE_REVIEW,
        PipelineStatus.NEXT_MODULE,   # guard: modules already planned, skip re-generation
        PipelineStatus.FAILED,
    ],
    PipelineStatus.HITL_1_MODULE_REVIEW: [
        PipelineStatus.NEXT_MODULE,               # approve → pick first module
        PipelineStatus.PROMPT_GENERATION,          # (legacy / direct)
        PipelineStatus.MODULE_PLANNING,            # retry generation
        PipelineStatus.FAILED,
    ],
    PipelineStatus.PROMPT_GENERATION: [
        PipelineStatus.HITL_2_PROMPT_REVIEW,
        PipelineStatus.FAILED,
    ],
    PipelineStatus.HITL_2_PROMPT_REVIEW: [
        PipelineStatus.CODE_GENERATION,
        PipelineStatus.PROMPT_GENERATION,         # retry generation
        PipelineStatus.FAILED,
    ],
    PipelineStatus.CODE_GENERATION: [
        PipelineStatus.VALIDATION,
        PipelineStatus.FAILED,
    ],
    PipelineStatus.VALIDATION: [
        PipelineStatus.CODE_REVIEW,
        PipelineStatus.CODE_GENERATION,  # retry code gen from validation
        PipelineStatus.FAILED,
    ],
    PipelineStatus.CODE_REVIEW: [
        PipelineStatus.HITL_3_REVIEW_DECISION,
        PipelineStatus.CODE_GENERATION,  # retry code gen from review
        PipelineStatus.FAILED,
    ],
    PipelineStatus.HITL_3_REVIEW_DECISION: [
        PipelineStatus.DECISION,
        PipelineStatus.CODE_GENERATION,  # retry code gen from review decision
        PipelineStatus.CODE_REVIEW,      # retry code reviewer from review decision
        PipelineStatus.GIT_COMMIT,       # user skip → accept current code, move on
        PipelineStatus.NEXT_MODULE,      # user skip → go directly to next module
        PipelineStatus.FAILED,
    ],
    PipelineStatus.DECISION: [
        PipelineStatus.PROMPT_GENERATION,       # iterate
        PipelineStatus.GIT_COMMIT,              # accept
        PipelineStatus.HITL_4_MAX_ITERATIONS,   # max reached
        PipelineStatus.FAILED,
    ],
    PipelineStatus.GIT_COMMIT: [
        PipelineStatus.MODULE_COMPLETE,
        PipelineStatus.FAILED,
    ],
    PipelineStatus.MODULE_COMPLETE: [
        PipelineStatus.HITL_5_PR_REVIEW,
        PipelineStatus.FAILED,
    ],
    PipelineStatus.HITL_4_MAX_ITERATIONS: [
        PipelineStatus.GIT_COMMIT,              # force-accept (with git commit)
        PipelineStatus.NEXT_MODULE,             # force-accept (skip git commit)
        PipelineStatus.PROMPT_GENERATION,       # allow more iterations
        PipelineStatus.FAILED,                  # abort
    ],
    PipelineStatus.HITL_5_PR_REVIEW: [
        PipelineStatus.INTEGRATION_TEST,
        PipelineStatus.FAILED,
    ],
    PipelineStatus.INTEGRATION_TEST: [
        PipelineStatus.NEXT_MODULE,
        PipelineStatus.PROMPT_GENERATION,  # integration failure → fix
        PipelineStatus.FAILED,
    ],
    PipelineStatus.NEXT_MODULE: [
        PipelineStatus.PROMPT_GENERATION,       # next module starts
        PipelineStatus.MODULE_PLANNING,         # need to re-plan (module deps changed)
        PipelineStatus.PIPELINE_COMPLETE,
        PipelineStatus.FAILED,
    ],
    PipelineStatus.MODULE_COMPLETE: [
        PipelineStatus.HITL_5_PR_REVIEW,
        PipelineStatus.NEXT_MODULE,             # skip PR review when no PR created
        PipelineStatus.FAILED,
    ],
    PipelineStatus.PIPELINE_COMPLETE: [],
    PipelineStatus.FAILED: [
        PipelineStatus.IDLE,             # full reset
        PipelineStatus.MODULE_PLANNING,   # retry module maker after failure
        PipelineStatus.PROMPT_GENERATION, # retry prompt generator after failure
        PipelineStatus.CODE_GENERATION,   # retry code gen after failure
        PipelineStatus.CODE_REVIEW,       # retry code reviewer after failure
        PipelineStatus.GIT_COMMIT,        # retry git commit after failure
        PipelineStatus.NEXT_MODULE,       # skip failed step, go to next module
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
        module_id: Optional[str] = None,
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

        # Build new state — if transitioning to FAILED, record where we came from
        extra_meta: dict = {}
        if new_status == PipelineStatus.FAILED:
            extra_meta["pre_failure_status"] = old_status.value
        new_state = PipelineState(
            current_module_id=module_id if module_id is not None else current.current_module_id,
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
            PipelineStatus.HITL_1_MODULE_REVIEW,
            PipelineStatus.HITL_2_PROMPT_REVIEW,
            PipelineStatus.HITL_3_REVIEW_DECISION,
            PipelineStatus.HITL_4_MAX_ITERATIONS,
            PipelineStatus.HITL_5_PR_REVIEW,
        }

    def can_resume_from(self, status: PipelineStatus) -> bool:
        """Check if the given status is one we can resume from after a crash."""
        # We can resume from any non-terminal state
        return status not in {PipelineStatus.PIPELINE_COMPLETE, PipelineStatus.IDLE}
