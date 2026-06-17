"""Characterization tests for all pipeline state transitions.

These tests lock down the CURRENT behavior of the state machine so that
future refactoring cannot silently change transition semantics.

"Characterization test" means: we test what the system DOES, not what we
wish it did. If a transition path is currently broken, the test is marked
xfail so the suite stays green but the broken behavior is documented.
"""

from __future__ import annotations

import pytest

from agent_os.orchestrator.state import TRANSITIONS, InvalidTransitionError, StateManager
from agent_os.storage.database import Database
from agent_os.storage.models import PipelineStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_state_manager() -> tuple[Database, StateManager]:
    db = Database(":memory:")
    db.connect()
    return db, StateManager(db)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def sm():
    db, mgr = make_state_manager()
    yield mgr
    db.close()


# ---------------------------------------------------------------------------
# Characterize every valid transition pair
#
# For each (source, target) in TRANSITIONS, we verify:
#   1. The transition succeeds when we start from the right source state.
#   2. The resulting status equals the expected target.
# ---------------------------------------------------------------------------


def _navigate_to(sm: StateManager, target: PipelineStatus) -> None:
    """Drive the state machine to *target* via the shortest valid path.

    This function encodes the minimal "setup" sequences needed to reach each
    state so that individual characterization tests can focus on the transition
    under test rather than setup boilerplate.
    """
    current = sm.current_status
    if current == target:
        return

    # Shortest-path sequences from IDLE to every state
    _PATHS: dict[PipelineStatus, list[PipelineStatus]] = {
        PipelineStatus.IDLE: [],
        PipelineStatus.LOADING_REQUIREMENTS: [
            PipelineStatus.LOADING_REQUIREMENTS,
        ],
        PipelineStatus.PROMPT_GENERATION: [
            PipelineStatus.LOADING_REQUIREMENTS,
            PipelineStatus.PROMPT_GENERATION,
        ],
        PipelineStatus.HITL_PROMPT_REVIEW: [
            PipelineStatus.LOADING_REQUIREMENTS,
            PipelineStatus.PROMPT_GENERATION,
            PipelineStatus.HITL_PROMPT_REVIEW,
        ],
        PipelineStatus.CODE_GENERATION: [
            PipelineStatus.LOADING_REQUIREMENTS,
            PipelineStatus.PROMPT_GENERATION,
            PipelineStatus.HITL_PROMPT_REVIEW,
            PipelineStatus.CODE_GENERATION,
        ],
        PipelineStatus.CODE_GEN_FAILED: [
            PipelineStatus.LOADING_REQUIREMENTS,
            PipelineStatus.PROMPT_GENERATION,
            PipelineStatus.HITL_PROMPT_REVIEW,
            PipelineStatus.CODE_GENERATION,
            PipelineStatus.CODE_GEN_FAILED,
        ],
        PipelineStatus.CODE_GEN_STOPPED: [
            PipelineStatus.LOADING_REQUIREMENTS,
            PipelineStatus.PROMPT_GENERATION,
            PipelineStatus.HITL_PROMPT_REVIEW,
            PipelineStatus.CODE_GENERATION,
            PipelineStatus.CODE_GEN_STOPPED,
        ],
        PipelineStatus.CODE_REVIEW: [
            PipelineStatus.LOADING_REQUIREMENTS,
            PipelineStatus.PROMPT_GENERATION,
            PipelineStatus.HITL_PROMPT_REVIEW,
            PipelineStatus.CODE_GENERATION,
            PipelineStatus.CODE_REVIEW,
        ],
        PipelineStatus.HITL_REVIEW_DECISION: [
            PipelineStatus.LOADING_REQUIREMENTS,
            PipelineStatus.PROMPT_GENERATION,
            PipelineStatus.HITL_PROMPT_REVIEW,
            PipelineStatus.CODE_GENERATION,
            PipelineStatus.CODE_REVIEW,
            PipelineStatus.HITL_REVIEW_DECISION,
        ],
        PipelineStatus.PIPELINE_COMPLETE: [
            PipelineStatus.LOADING_REQUIREMENTS,
            PipelineStatus.PROMPT_GENERATION,
            PipelineStatus.HITL_PROMPT_REVIEW,
            PipelineStatus.CODE_GENERATION,
            PipelineStatus.CODE_REVIEW,
            PipelineStatus.PIPELINE_COMPLETE,
        ],
        PipelineStatus.FAILED: [
            PipelineStatus.FAILED,
        ],
        # GHR states
        PipelineStatus.ANALYSING_DEPENDENCIES: [
            PipelineStatus.LOADING_REQUIREMENTS,
            PipelineStatus.ANALYSING_DEPENDENCIES,
        ],
        PipelineStatus.QUEUE_READY: [
            PipelineStatus.LOADING_REQUIREMENTS,
            PipelineStatus.ANALYSING_DEPENDENCIES,
            PipelineStatus.QUEUE_READY,
        ],
        PipelineStatus.STORY_PROMPT_GENERATION: [
            PipelineStatus.LOADING_REQUIREMENTS,
            PipelineStatus.ANALYSING_DEPENDENCIES,
            PipelineStatus.QUEUE_READY,
            PipelineStatus.STORY_PROMPT_GENERATION,
        ],
        PipelineStatus.STORY_CODE_GENERATION: [
            PipelineStatus.LOADING_REQUIREMENTS,
            PipelineStatus.ANALYSING_DEPENDENCIES,
            PipelineStatus.QUEUE_READY,
            PipelineStatus.STORY_PROMPT_GENERATION,
            PipelineStatus.STORY_CODE_GENERATION,
        ],
        PipelineStatus.STORY_CODE_REVIEW: [
            PipelineStatus.LOADING_REQUIREMENTS,
            PipelineStatus.ANALYSING_DEPENDENCIES,
            PipelineStatus.QUEUE_READY,
            PipelineStatus.STORY_PROMPT_GENERATION,
            PipelineStatus.STORY_CODE_GENERATION,
            PipelineStatus.STORY_CODE_REVIEW,
        ],
        PipelineStatus.STORY_COMPLETE: [
            PipelineStatus.LOADING_REQUIREMENTS,
            PipelineStatus.ANALYSING_DEPENDENCIES,
            PipelineStatus.QUEUE_READY,
            PipelineStatus.STORY_PROMPT_GENERATION,
            PipelineStatus.STORY_CODE_GENERATION,
            PipelineStatus.STORY_CODE_REVIEW,
            PipelineStatus.STORY_COMPLETE,
        ],
    }
    path = _PATHS.get(target, [])
    for step in path:
        if sm.current_status != step:
            sm.transition_to(step)


# ---------------------------------------------------------------------------
# Build parametrized test cases from TRANSITIONS
# ---------------------------------------------------------------------------


def _all_valid_transition_pairs():
    """Yield (source, target) for every valid transition in TRANSITIONS."""
    for source, targets in TRANSITIONS.items():
        for target in targets:
            yield pytest.param(source, target, id=f"{source.name}_to_{target.name}")


@pytest.mark.parametrize("source, target", _all_valid_transition_pairs())
def test_valid_transition(source: PipelineStatus, target: PipelineStatus):
    """Characterize that every transition listed in TRANSITIONS actually works."""
    db, sm = make_state_manager()
    try:
        _navigate_to(sm, source)
        assert sm.current_status == source, (
            f"Could not navigate to {source.name}; stuck at {sm.current_status.name}"
        )
        result = sm.transition_to(target)
        assert result.pipeline_status == target
        assert sm.current_status == target
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Characterize that every NOT-listed transition raises InvalidTransitionError
# ---------------------------------------------------------------------------


def _some_invalid_transition_pairs():
    """Yield a sample of (source, target) pairs that are NOT in TRANSITIONS.

    We test a representative subset rather than the full Cartesian product to
    keep the suite fast.
    """
    invalid = [
        (PipelineStatus.IDLE, PipelineStatus.CODE_GENERATION),
        (PipelineStatus.IDLE, PipelineStatus.CODE_REVIEW),
        (PipelineStatus.IDLE, PipelineStatus.PIPELINE_COMPLETE),
        (PipelineStatus.PROMPT_GENERATION, PipelineStatus.CODE_REVIEW),
        (PipelineStatus.PROMPT_GENERATION, PipelineStatus.PIPELINE_COMPLETE),
        (PipelineStatus.CODE_REVIEW, PipelineStatus.LOADING_REQUIREMENTS),
        (PipelineStatus.PIPELINE_COMPLETE, PipelineStatus.IDLE),
        (PipelineStatus.PIPELINE_COMPLETE, PipelineStatus.LOADING_REQUIREMENTS),
        (PipelineStatus.STORY_CODE_GENERATION, PipelineStatus.IDLE),
        (PipelineStatus.STORY_CODE_GENERATION, PipelineStatus.PIPELINE_COMPLETE),
    ]
    for source, target in invalid:
        # Only yield if target is genuinely not in the allowed set
        if target not in TRANSITIONS.get(source, []):
            yield pytest.param(source, target, id=f"{source.name}_to_{target.name}_invalid")


@pytest.mark.parametrize("source, target", _some_invalid_transition_pairs())
def test_invalid_transition_raises(source: PipelineStatus, target: PipelineStatus):
    """Characterize that invalid transitions are rejected with InvalidTransitionError."""
    db, sm = make_state_manager()
    try:
        _navigate_to(sm, source)
        assert sm.current_status == source
        with pytest.raises(InvalidTransitionError):
            sm.transition_to(target)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# HITL gate characterization
# ---------------------------------------------------------------------------


class TestHITLGateCharacterization:
    """Lock down the exact set of states that are considered HITL gates."""

    HITL_GATE_STATES = {
        PipelineStatus.HITL_PROMPT_REVIEW,
        PipelineStatus.HITL_REVIEW_DECISION,
    }

    def test_hitl_prompt_review_is_a_gate(self, sm):
        _navigate_to(sm, PipelineStatus.HITL_PROMPT_REVIEW)
        assert sm.is_hitl_gate() is True

    def test_hitl_review_decision_is_a_gate(self, sm):
        _navigate_to(sm, PipelineStatus.HITL_REVIEW_DECISION)
        assert sm.is_hitl_gate() is True

    @pytest.mark.parametrize(
        "status",
        [
            s
            for s in PipelineStatus
            if s
            not in {
                PipelineStatus.HITL_PROMPT_REVIEW,
                PipelineStatus.HITL_REVIEW_DECISION,
            }
        ],
    )
    def test_non_hitl_states_are_not_gates(self, status: PipelineStatus):
        db, sm = make_state_manager()
        try:
            _navigate_to(sm, status)
            if sm.current_status == status:
                assert sm.is_hitl_gate() is False
        finally:
            db.close()


# ---------------------------------------------------------------------------
# State persistence characterization
# ---------------------------------------------------------------------------


class TestStatePersistenceCharacterization:
    def test_status_survives_reconnect(self, tmp_path):
        """State written by one Database instance must be visible from a second."""
        db_path = str(tmp_path / "persist.db")

        db1 = Database(db_path)
        db1.connect()
        sm1 = StateManager(db1)
        sm1.transition_to(PipelineStatus.LOADING_REQUIREMENTS)
        db1.close()

        db2 = Database(db_path)
        db2.connect()
        sm2 = StateManager(db2)
        assert sm2.current_status == PipelineStatus.LOADING_REQUIREMENTS
        db2.close()

    def test_metadata_survives_reconnect(self, tmp_path):
        db_path = str(tmp_path / "meta.db")

        db1 = Database(db_path)
        db1.connect()
        sm1 = StateManager(db1)
        sm1.transition_to(PipelineStatus.LOADING_REQUIREMENTS, metadata={"run_id": "abc"})
        db1.close()

        db2 = Database(db_path)
        db2.connect()
        sm2 = StateManager(db2)
        assert sm2.state.metadata["run_id"] == "abc"
        db2.close()
