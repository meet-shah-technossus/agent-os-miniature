"""Unit tests for StateManager — transitions, listeners, reset, and TRANSITIONS map.

These tests exercise pure state-machine logic with an in-memory SQLite
database.  No external processes or network calls are made.
"""

from __future__ import annotations

import pytest

from agent_os.orchestrator.state import TRANSITIONS, InvalidTransitionError, StateManager
from agent_os.storage.database import Database
from agent_os.storage.models import PipelineStatus


# ---------------------------------------------------------------------------
# Local fixtures (keep tests self-contained; conftest.py fixtures also work)
# ---------------------------------------------------------------------------


@pytest.fixture()
def sm():
    """StateManager backed by a fresh in-memory database."""
    d = Database(":memory:")
    d.connect()
    mgr = StateManager(d)
    yield mgr
    d.close()


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------


class TestInitialState:
    def test_initial_status_is_idle(self, sm):
        assert sm.current_status == PipelineStatus.IDLE

    def test_initial_iteration_is_zero(self, sm):
        assert sm.state.current_iteration == 0

    def test_initial_metadata_is_empty(self, sm):
        assert sm.state.metadata == {}

    def test_is_hitl_gate_false_at_idle(self, sm):
        assert sm.is_hitl_gate() is False


# ---------------------------------------------------------------------------
# Valid transitions — standard pipeline path
# ---------------------------------------------------------------------------


class TestValidTransitions:
    def test_idle_to_loading_requirements(self, sm):
        state = sm.transition_to(PipelineStatus.LOADING_REQUIREMENTS)
        assert state.pipeline_status == PipelineStatus.LOADING_REQUIREMENTS
        assert sm.current_status == PipelineStatus.LOADING_REQUIREMENTS

    def test_loading_to_prompt_generation(self, sm):
        sm.transition_to(PipelineStatus.LOADING_REQUIREMENTS)
        sm.transition_to(PipelineStatus.PROMPT_GENERATION)
        assert sm.current_status == PipelineStatus.PROMPT_GENERATION

    def test_standard_happy_path_to_complete(self, sm):
        """Walk the full IDLE → PIPELINE_COMPLETE standard-mode path."""
        path = [
            PipelineStatus.LOADING_REQUIREMENTS,
            PipelineStatus.PROMPT_GENERATION,
            PipelineStatus.HITL_PROMPT_REVIEW,
            PipelineStatus.CODE_GENERATION,
            PipelineStatus.CODE_REVIEW,
            PipelineStatus.PIPELINE_COMPLETE,
        ]
        for status in path:
            sm.transition_to(status)
        assert sm.current_status == PipelineStatus.PIPELINE_COMPLETE

    def test_idle_to_failed(self, sm):
        sm.transition_to(PipelineStatus.FAILED)
        assert sm.current_status == PipelineStatus.FAILED

    def test_failed_can_reset_to_idle(self, sm):
        sm.transition_to(PipelineStatus.FAILED)
        sm.transition_to(PipelineStatus.IDLE)
        assert sm.current_status == PipelineStatus.IDLE

    def test_code_gen_failed_can_retry(self, sm):
        sm.transition_to(PipelineStatus.LOADING_REQUIREMENTS)
        sm.transition_to(PipelineStatus.PROMPT_GENERATION)
        sm.transition_to(PipelineStatus.HITL_PROMPT_REVIEW)
        sm.transition_to(PipelineStatus.CODE_GENERATION)
        sm.transition_to(PipelineStatus.CODE_GEN_FAILED)
        sm.transition_to(PipelineStatus.CODE_GENERATION)
        assert sm.current_status == PipelineStatus.CODE_GENERATION

    def test_code_gen_failed_can_go_idle(self, sm):
        sm.transition_to(PipelineStatus.LOADING_REQUIREMENTS)
        sm.transition_to(PipelineStatus.PROMPT_GENERATION)
        sm.transition_to(PipelineStatus.HITL_PROMPT_REVIEW)
        sm.transition_to(PipelineStatus.CODE_GENERATION)
        sm.transition_to(PipelineStatus.CODE_GEN_FAILED)
        sm.transition_to(PipelineStatus.IDLE)
        assert sm.current_status == PipelineStatus.IDLE

    def test_code_review_to_hitl_decision(self, sm):
        sm.transition_to(PipelineStatus.LOADING_REQUIREMENTS)
        sm.transition_to(PipelineStatus.PROMPT_GENERATION)
        sm.transition_to(PipelineStatus.HITL_PROMPT_REVIEW)
        sm.transition_to(PipelineStatus.CODE_GENERATION)
        sm.transition_to(PipelineStatus.CODE_REVIEW)
        sm.transition_to(PipelineStatus.HITL_REVIEW_DECISION)
        assert sm.is_hitl_gate() is True

    def test_hitl_review_decision_to_pipeline_complete(self, sm):
        sm.transition_to(PipelineStatus.LOADING_REQUIREMENTS)
        sm.transition_to(PipelineStatus.PROMPT_GENERATION)
        sm.transition_to(PipelineStatus.HITL_PROMPT_REVIEW)
        sm.transition_to(PipelineStatus.CODE_GENERATION)
        sm.transition_to(PipelineStatus.CODE_REVIEW)
        sm.transition_to(PipelineStatus.HITL_REVIEW_DECISION)
        sm.transition_to(PipelineStatus.PIPELINE_COMPLETE)
        assert sm.current_status == PipelineStatus.PIPELINE_COMPLETE


# ---------------------------------------------------------------------------
# Valid transitions — GitHub Review (GHR) pipeline path
# ---------------------------------------------------------------------------


class TestGHRTransitions:
    def test_loading_to_analysing_dependencies(self, sm):
        sm.transition_to(PipelineStatus.LOADING_REQUIREMENTS)
        sm.transition_to(PipelineStatus.ANALYSING_DEPENDENCIES)
        assert sm.current_status == PipelineStatus.ANALYSING_DEPENDENCIES

    def test_analysing_to_queue_ready(self, sm):
        sm.transition_to(PipelineStatus.LOADING_REQUIREMENTS)
        sm.transition_to(PipelineStatus.ANALYSING_DEPENDENCIES)
        sm.transition_to(PipelineStatus.QUEUE_READY)
        assert sm.current_status == PipelineStatus.QUEUE_READY

    def test_queue_ready_to_story_prompt_gen(self, sm):
        sm.transition_to(PipelineStatus.LOADING_REQUIREMENTS)
        sm.transition_to(PipelineStatus.ANALYSING_DEPENDENCIES)
        sm.transition_to(PipelineStatus.QUEUE_READY)
        sm.transition_to(PipelineStatus.STORY_PROMPT_GENERATION)
        assert sm.current_status == PipelineStatus.STORY_PROMPT_GENERATION

    def test_story_complete_to_queue_ready_loops(self, sm):
        sm.transition_to(PipelineStatus.LOADING_REQUIREMENTS)
        sm.transition_to(PipelineStatus.ANALYSING_DEPENDENCIES)
        sm.transition_to(PipelineStatus.QUEUE_READY)
        sm.transition_to(PipelineStatus.STORY_PROMPT_GENERATION)
        sm.transition_to(PipelineStatus.STORY_CODE_GENERATION)
        sm.transition_to(PipelineStatus.STORY_CODE_REVIEW)
        sm.transition_to(PipelineStatus.STORY_COMPLETE)
        sm.transition_to(PipelineStatus.QUEUE_READY)
        assert sm.current_status == PipelineStatus.QUEUE_READY

    def test_queue_ready_to_pipeline_complete(self, sm):
        sm.transition_to(PipelineStatus.LOADING_REQUIREMENTS)
        sm.transition_to(PipelineStatus.ANALYSING_DEPENDENCIES)
        sm.transition_to(PipelineStatus.QUEUE_READY)
        sm.transition_to(PipelineStatus.PIPELINE_COMPLETE)
        assert sm.current_status == PipelineStatus.PIPELINE_COMPLETE


# ---------------------------------------------------------------------------
# Invalid transitions
# ---------------------------------------------------------------------------


class TestInvalidTransitions:
    def test_idle_to_code_generation_raises(self, sm):
        with pytest.raises(InvalidTransitionError):
            sm.transition_to(PipelineStatus.CODE_GENERATION)

    def test_idle_to_pipeline_complete_raises(self, sm):
        with pytest.raises(InvalidTransitionError):
            sm.transition_to(PipelineStatus.PIPELINE_COMPLETE)

    def test_pipeline_complete_to_idle_raises(self, sm):
        sm.transition_to(PipelineStatus.LOADING_REQUIREMENTS)
        sm.transition_to(PipelineStatus.PROMPT_GENERATION)
        sm.transition_to(PipelineStatus.HITL_PROMPT_REVIEW)
        sm.transition_to(PipelineStatus.CODE_GENERATION)
        sm.transition_to(PipelineStatus.CODE_REVIEW)
        sm.transition_to(PipelineStatus.PIPELINE_COMPLETE)
        with pytest.raises(InvalidTransitionError):
            sm.transition_to(PipelineStatus.IDLE)

    def test_error_message_names_both_states(self, sm):
        with pytest.raises(
            InvalidTransitionError,
            match="Cannot transition from IDLE to CODE_GENERATION",
        ):
            sm.transition_to(PipelineStatus.CODE_GENERATION)

    def test_prompt_gen_to_code_review_raises(self, sm):
        sm.transition_to(PipelineStatus.LOADING_REQUIREMENTS)
        sm.transition_to(PipelineStatus.PROMPT_GENERATION)
        with pytest.raises(InvalidTransitionError):
            sm.transition_to(PipelineStatus.CODE_REVIEW)


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_transition_stores_supplied_metadata(self, sm):
        sm.transition_to(PipelineStatus.LOADING_REQUIREMENTS, metadata={"source": "test"})
        assert sm.state.metadata["source"] == "test"

    def test_failed_transition_stores_pre_failure_status(self, sm):
        sm.transition_to(PipelineStatus.LOADING_REQUIREMENTS)
        sm.transition_to(PipelineStatus.FAILED)
        assert sm.state.metadata["pre_failure_status"] == "LOADING_REQUIREMENTS"

    def test_metadata_is_cumulative_across_transitions(self, sm):
        sm.transition_to(PipelineStatus.LOADING_REQUIREMENTS, metadata={"a": 1})
        sm.transition_to(PipelineStatus.PROMPT_GENERATION, metadata={"b": 2})
        meta = sm.state.metadata
        assert meta["a"] == 1
        assert meta["b"] == 2

    def test_update_metadata_merges_non_destructively(self, sm):
        sm.transition_to(PipelineStatus.LOADING_REQUIREMENTS, metadata={"a": 1})
        sm.update_metadata({"b": 2})
        meta = sm.state.metadata
        assert meta["a"] == 1
        assert meta["b"] == 2

    def test_iteration_stored_in_transition(self, sm):
        sm.transition_to(PipelineStatus.LOADING_REQUIREMENTS, iteration=5)
        assert sm.state.current_iteration == 5


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_returns_to_idle(self, sm):
        sm.transition_to(PipelineStatus.LOADING_REQUIREMENTS)
        sm.reset()
        assert sm.current_status == PipelineStatus.IDLE

    def test_reset_clears_iteration(self, sm):
        sm.transition_to(PipelineStatus.LOADING_REQUIREMENTS, iteration=7)
        sm.reset()
        assert sm.state.current_iteration == 0

    def test_reset_clears_metadata(self, sm):
        sm.transition_to(PipelineStatus.LOADING_REQUIREMENTS, metadata={"x": 1})
        sm.reset()
        assert sm.state.metadata == {}

    def test_can_transition_after_reset(self, sm):
        sm.transition_to(PipelineStatus.FAILED)
        sm.reset()
        sm.transition_to(PipelineStatus.LOADING_REQUIREMENTS)
        assert sm.current_status == PipelineStatus.LOADING_REQUIREMENTS


# ---------------------------------------------------------------------------
# Story context
# ---------------------------------------------------------------------------


class TestStoryContext:
    def test_update_story_context_sets_fields(self, sm):
        sm.update_story_context(
            current_story_id="STORY-1",
            stories_completed=1,
            stories_total=3,
        )
        state = sm.state
        assert state.current_story_id == "STORY-1"
        assert state.stories_completed == 1
        assert state.stories_total == 3

    def test_partial_story_context_update(self, sm):
        sm.update_story_context(stories_total=5)
        assert sm.state.stories_total == 5


# ---------------------------------------------------------------------------
# Listeners
# ---------------------------------------------------------------------------


class TestListeners:
    def test_listener_called_on_transition(self, sm):
        events: list = []
        sm.on_transition(lambda old, new, state: events.append((old, new)))
        sm.transition_to(PipelineStatus.LOADING_REQUIREMENTS)
        assert len(events) == 1
        assert events[0] == (PipelineStatus.IDLE, PipelineStatus.LOADING_REQUIREMENTS)

    def test_multiple_listeners_all_called(self, sm):
        a: list = []
        b: list = []
        sm.on_transition(lambda old, new, state: a.append(new))
        sm.on_transition(lambda old, new, state: b.append(new))
        sm.transition_to(PipelineStatus.LOADING_REQUIREMENTS)
        assert a == [PipelineStatus.LOADING_REQUIREMENTS]
        assert b == [PipelineStatus.LOADING_REQUIREMENTS]

    def test_listener_exception_does_not_abort_transition(self, sm):
        def bad_listener(old, new, state):
            raise RuntimeError("listener failure")

        sm.on_transition(bad_listener)
        # Must not raise — the transition should succeed even if listener fails
        sm.transition_to(PipelineStatus.LOADING_REQUIREMENTS)
        assert sm.current_status == PipelineStatus.LOADING_REQUIREMENTS


# ---------------------------------------------------------------------------
# TRANSITIONS map coverage
# ---------------------------------------------------------------------------


class TestTransitionsCoverage:
    def test_all_pipeline_statuses_present_in_transitions(self):
        """Every PipelineStatus value must appear as a key in TRANSITIONS."""
        for status in PipelineStatus:
            assert status in TRANSITIONS, (
                f"PipelineStatus.{status.name} is missing from TRANSITIONS dict"
            )
