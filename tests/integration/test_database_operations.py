"""Integration tests for Database and all repository CRUD operations.

Tests use an in-memory SQLite database so they run fast with no disk I/O.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_os.storage.database import Database
from agent_os.storage.models import (
    PipelineState,
    PipelineStatus,
    RequirementRecord,
    RequirementType,
)
from agent_os.storage.pipeline_repo import PipelineRepository
from agent_os.storage.requirement_repo import RequirementRepository


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def db():
    d = Database(":memory:")
    d.connect()
    yield d
    d.close()


# ---------------------------------------------------------------------------
# Schema initialization
# ---------------------------------------------------------------------------


class TestDatabaseSchema:
    REQUIRED_TABLES = {
        "modules",
        "iterations",
        "requirements",
        "pipeline_state",
        "agent_config",
        "agent_files",
        "story_queue",
    }

    def test_all_expected_tables_created(self, db):
        rows = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        actual = {row[0] for row in rows}
        assert self.REQUIRED_TABLES.issubset(actual)

    def test_pipeline_state_singleton_row_exists(self, db):
        count = db.conn.execute("SELECT COUNT(*) FROM pipeline_state").fetchone()[0]
        assert count == 1

    def test_initial_pipeline_status_is_idle(self, db):
        repo = PipelineRepository(db.conn)
        state = repo.get_state()
        assert state.pipeline_status == PipelineStatus.IDLE

    def test_connect_twice_same_path_is_safe(self, tmp_path):
        """Calling connect() twice on the same path must not raise."""
        d = Database(str(tmp_path / "idempotent.db"))
        d.connect()
        d.connect()  # second call should be a no-op
        d.close()

    def test_database_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c" / "test.db"
        d = Database(str(nested))
        d.connect()
        assert nested.exists()
        d.close()


# ---------------------------------------------------------------------------
# PipelineRepository
# ---------------------------------------------------------------------------


class TestPipelineRepository:
    def test_get_state_returns_idle_by_default(self, db):
        repo = PipelineRepository(db.conn)
        state = repo.get_state()
        assert state.pipeline_status == PipelineStatus.IDLE
        assert state.current_iteration == 0

    def test_save_and_retrieve_status(self, db):
        repo = PipelineRepository(db.conn)
        repo.save_state(PipelineState(pipeline_status=PipelineStatus.CODE_GENERATION))
        assert repo.get_state().pipeline_status == PipelineStatus.CODE_GENERATION

    def test_save_and_retrieve_iteration(self, db):
        repo = PipelineRepository(db.conn)
        repo.save_state(PipelineState(current_iteration=7))
        assert repo.get_state().current_iteration == 7

    def test_save_and_retrieve_metadata(self, db):
        repo = PipelineRepository(db.conn)
        state = PipelineState(metadata={"key": "value", "count": 42})
        repo.save_state(state)
        retrieved = repo.get_state()
        assert retrieved.metadata["key"] == "value"
        assert retrieved.metadata["count"] == 42

    def test_overwrite_replaces_previous_state(self, db):
        repo = PipelineRepository(db.conn)
        repo.save_state(PipelineState(pipeline_status=PipelineStatus.LOADING_REQUIREMENTS))
        repo.save_state(PipelineState(pipeline_status=PipelineStatus.PROMPT_GENERATION))
        assert repo.get_state().pipeline_status == PipelineStatus.PROMPT_GENERATION

    def test_story_context_round_trips(self, db):
        repo = PipelineRepository(db.conn)
        state = PipelineState(
            pipeline_status=PipelineStatus.STORY_CODE_GENERATION,
            current_story_id="STORY-42",
            stories_completed=2,
            stories_total=5,
        )
        repo.save_state(state)
        retrieved = repo.get_state()
        assert retrieved.current_story_id == "STORY-42"
        assert retrieved.stories_completed == 2
        assert retrieved.stories_total == 5

    def test_story_context_does_not_pollute_metadata(self, db):
        """Story fields should be top-level on PipelineState, not in metadata."""
        repo = PipelineRepository(db.conn)
        repo.save_state(
            PipelineState(current_story_id="STORY-1", stories_completed=1, stories_total=3)
        )
        state = repo.get_state()
        # metadata dict must NOT contain the story keys
        assert "current_story_id" not in state.metadata
        assert "stories_completed" not in state.metadata
        assert "stories_total" not in state.metadata


# ---------------------------------------------------------------------------
# RequirementRepository
# ---------------------------------------------------------------------------


class TestRequirementRepository:
    def test_empty_db_returns_empty_list(self, db):
        repo = RequirementRepository(db.conn)
        assert repo.get_all() == []

    def test_upsert_and_get_all(self, db):
        repo = RequirementRepository(db.conn)
        repo.upsert(RequirementRecord(id="E1", type=RequirementType.EPIC, title="Epic 1"))
        all_reqs = repo.get_all()
        assert len(all_reqs) == 1
        assert all_reqs[0].id == "E1"

    def test_upsert_updates_existing_record(self, db):
        repo = RequirementRepository(db.conn)
        repo.upsert(RequirementRecord(id="E1", type=RequirementType.EPIC, title="Old Title"))
        repo.upsert(RequirementRecord(id="E1", type=RequirementType.EPIC, title="New Title"))
        all_reqs = repo.get_all()
        assert len(all_reqs) == 1
        assert all_reqs[0].title == "New Title"

    def test_get_by_type_filters_correctly(self, db):
        repo = RequirementRepository(db.conn)
        repo.upsert(RequirementRecord(id="E1", type=RequirementType.EPIC, title="Epic 1"))
        repo.upsert(
            RequirementRecord(
                id="F1", type=RequirementType.FEATURE, title="Feature 1", parent_id="E1"
            )
        )
        epics = repo.get_by_type("epic")
        features = repo.get_by_type("feature")
        assert len(epics) == 1
        assert len(features) == 1

    def test_get_children_returns_direct_children_only(self, db):
        repo = RequirementRepository(db.conn)
        repo.upsert(RequirementRecord(id="E1", type=RequirementType.EPIC, title="Epic 1"))
        repo.upsert(
            RequirementRecord(
                id="F1", type=RequirementType.FEATURE, title="Feature 1", parent_id="E1"
            )
        )
        repo.upsert(
            RequirementRecord(
                id="F2", type=RequirementType.FEATURE, title="Feature 2", parent_id="E1"
            )
        )
        repo.upsert(
            RequirementRecord(
                id="S1", type=RequirementType.STORY, title="Story 1", parent_id="F1"
            )
        )
        children = repo.get_children("E1")
        assert len(children) == 2
        assert {c.id for c in children} == {"F1", "F2"}

    def test_get_children_returns_empty_for_leaf(self, db):
        repo = RequirementRepository(db.conn)
        repo.upsert(RequirementRecord(id="E1", type=RequirementType.EPIC, title="Epic 1"))
        assert repo.get_children("E1") == []

    def test_description_defaults_to_empty_string(self, db):
        repo = RequirementRepository(db.conn)
        repo.upsert(RequirementRecord(id="E1", type=RequirementType.EPIC, title="No desc"))
        req = repo.get_all()[0]
        assert req.description == ""

    def test_status_defaults_to_active(self, db):
        repo = RequirementRepository(db.conn)
        repo.upsert(RequirementRecord(id="E1", type=RequirementType.EPIC, title="Active Req"))
        req = repo.get_all()[0]
        assert req.status == "active"


# ---------------------------------------------------------------------------
# Database convenience delegates
# ---------------------------------------------------------------------------


class TestDatabaseConvenience:
    def test_get_pipeline_state_delegates_to_repo(self, db):
        state = db.get_pipeline_state()
        assert isinstance(state, PipelineState)
        assert state.pipeline_status == PipelineStatus.IDLE

    def test_save_pipeline_state_delegates_to_repo(self, db):
        db.save_pipeline_state(PipelineState(pipeline_status=PipelineStatus.FAILED))
        assert db.get_pipeline_state().pipeline_status == PipelineStatus.FAILED

    def test_clear_run_data_resets_to_idle(self, db):
        db.save_pipeline_state(PipelineState(pipeline_status=PipelineStatus.CODE_GENERATION))
        db.clear_run_data()
        assert db.get_pipeline_state().pipeline_status == PipelineStatus.IDLE
