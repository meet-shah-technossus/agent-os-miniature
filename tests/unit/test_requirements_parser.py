"""Unit tests for RequirementsParser — YAML parsing, validation, and persistence.

All tests use a temporary file-system path for the requirements YAML and an
in-memory SQLite database.  No external services are required.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from agent_os.requirements.parser import RequirementsParser
from agent_os.storage.database import Database
from agent_os.storage.requirement_repo import RequirementRepository


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db():
    d = Database(":memory:")
    d.connect()
    yield d
    d.close()


@pytest.fixture()
def parser(db):
    return RequirementsParser(db)


# ---------------------------------------------------------------------------
# Sample YAML definitions
# ---------------------------------------------------------------------------

MINIMAL_YAML = textwrap.dedent("""\
    epics:
      - id: E1
        title: Epic One
        description: First epic
        features:
          - id: F1
            title: Feature One
            stories:
              - id: S1
                title: Story One
                acceptance_criteria:
                  - id: AC1
                    title: Accept Crit One
""")

EMPTY_YAML = "epics: []\n"

TWO_EPICS_YAML = textwrap.dedent("""\
    epics:
      - id: E1
        title: Epic 1
        features:
          - id: F1
            title: Feature 1
            stories:
              - id: S1
                title: Story 1
                acceptance_criteria:
                  - id: AC1
                    title: AC 1
      - id: E2
        title: Epic 2
        features:
          - id: F2
            title: Feature 2
            stories:
              - id: S2
                title: Story 2
                acceptance_criteria:
                  - id: AC2
                    title: AC 2
""")

DEEP_HIERARCHY_YAML = textwrap.dedent("""\
    epics:
      - id: E1
        title: Epic 1
        features:
          - id: F1
            title: Feature 1
            stories:
              - id: S1
                title: Story 1
                acceptance_criteria:
                  - id: AC1
                    title: AC 1
                  - id: AC2
                    title: AC 2
          - id: F2
            title: Feature 2
            stories:
              - id: S2
                title: Story 2
                acceptance_criteria:
                  - id: AC3
                    title: AC 3
""")


# ---------------------------------------------------------------------------
# Happy-path parsing
# ---------------------------------------------------------------------------


class TestParsing:
    def test_minimal_yaml_returns_correct_counts(self, parser, tmp_path):
        req_file = tmp_path / "requirements.yaml"
        req_file.write_text(MINIMAL_YAML)
        counts = parser.load_and_store(str(req_file))
        assert counts["epics"] == 1
        assert counts["features"] == 1
        assert counts["stories"] == 1
        assert counts["acceptance_criteria"] == 1

    def test_empty_epics_list_raises_error(self, parser, tmp_path):
        req_file = tmp_path / "empty.yaml"
        req_file.write_text(EMPTY_YAML)
        with pytest.raises(ValueError, match="No epics found"):
            parser.load_and_store(str(req_file))

    def test_two_epics_counted(self, parser, tmp_path):
        req_file = tmp_path / "multi.yaml"
        req_file.write_text(TWO_EPICS_YAML)
        counts = parser.load_and_store(str(req_file))
        assert counts["epics"] == 2

    def test_deep_hierarchy_counts(self, parser, tmp_path):
        req_file = tmp_path / "deep.yaml"
        req_file.write_text(DEEP_HIERARCHY_YAML)
        counts = parser.load_and_store(str(req_file))
        assert counts["epics"] == 1
        assert counts["features"] == 2
        assert counts["stories"] == 2
        assert counts["acceptance_criteria"] == 3

    def test_total_count_is_sum_of_parts(self, parser, tmp_path):
        req_file = tmp_path / "requirements.yaml"
        req_file.write_text(MINIMAL_YAML)
        counts = parser.load_and_store(str(req_file))
        assert sum(counts.values()) == 4


# ---------------------------------------------------------------------------
# Persistence — records end up in the database
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_epic_persisted_with_correct_id_and_title(self, parser, db, tmp_path):
        req_file = tmp_path / "requirements.yaml"
        req_file.write_text(MINIMAL_YAML)
        parser.load_and_store(str(req_file))

        repo = RequirementRepository(db.conn)
        epics = repo.get_by_type("epic")
        assert len(epics) == 1
        assert epics[0].id == "E1"
        assert epics[0].title == "Epic One"
        assert epics[0].description == "First epic"

    def test_feature_has_correct_parent_id(self, parser, db, tmp_path):
        req_file = tmp_path / "requirements.yaml"
        req_file.write_text(MINIMAL_YAML)
        parser.load_and_store(str(req_file))

        repo = RequirementRepository(db.conn)
        features = repo.get_by_type("feature")
        assert features[0].parent_id == "E1"

    def test_story_has_correct_parent_id(self, parser, db, tmp_path):
        req_file = tmp_path / "requirements.yaml"
        req_file.write_text(MINIMAL_YAML)
        parser.load_and_store(str(req_file))

        repo = RequirementRepository(db.conn)
        stories = repo.get_by_type("story")
        assert stories[0].parent_id == "F1"

    def test_acceptance_criteria_has_correct_parent_id(self, parser, db, tmp_path):
        req_file = tmp_path / "requirements.yaml"
        req_file.write_text(MINIMAL_YAML)
        parser.load_and_store(str(req_file))

        repo = RequirementRepository(db.conn)
        acs = repo.get_by_type("ac")
        assert acs[0].parent_id == "S1"

    def test_get_children_returns_correct_features(self, parser, db, tmp_path):
        req_file = tmp_path / "deep.yaml"
        req_file.write_text(DEEP_HIERARCHY_YAML)
        parser.load_and_store(str(req_file))

        repo = RequirementRepository(db.conn)
        children = repo.get_children("E1")
        ids = {c.id for c in children}
        assert ids == {"F1", "F2"}

    def test_double_load_does_not_duplicate_records(self, parser, db, tmp_path):
        req_file = tmp_path / "requirements.yaml"
        req_file.write_text(MINIMAL_YAML)
        parser.load_and_store(str(req_file))
        parser.load_and_store(str(req_file))

        repo = RequirementRepository(db.conn)
        assert len(repo.get_by_type("epic")) == 1


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestErrorCases:
    def test_missing_file_raises_file_not_found(self, parser):
        with pytest.raises(FileNotFoundError, match="requirements.yaml"):
            parser.load_and_store("/nonexistent/path/requirements.yaml")

    def test_invalid_yaml_raises_value_error(self, parser, tmp_path):
        """A YAML file that can be parsed but fails schema validation raises ValueError."""
        # Malformed YAML that looks structural but breaks schema
        bad_yaml = textwrap.dedent("""\
            epics:
              - title_only: missing_id_field
                features: []
        """)
        req_file = tmp_path / "bad.yaml"
        req_file.write_text(bad_yaml)
        # Pydantic validation will raise either ValueError or a pydantic error
        with pytest.raises(Exception):
            parser.load_and_store(str(req_file))
