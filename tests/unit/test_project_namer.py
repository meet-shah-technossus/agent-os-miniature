"""Unit tests for agent_os.services.project_namer — derive_name() logic."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from agent_os.services.project_namer import derive_name


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def req_file(tmp_path):
    """Factory that writes a YAML string to a temp file and returns its path."""
    def _write(content: str, suffix: str = ".yaml") -> Path:
        f = tmp_path / f"requirements{suffix}"
        f.write_text(content, encoding="utf-8")
        return f
    return _write


# ---------------------------------------------------------------------------
# Basic derivation from epic title
# ---------------------------------------------------------------------------


class TestDeriveNameFromEpicTitle:
    def test_uses_first_epic_title_as_name(self, req_file):
        yaml_content = textwrap.dedent("""\
            epics:
              - id: E1
                title: My Awesome Project
                features: []
        """)
        title, slug = derive_name(req_file(yaml_content))
        assert title == "My Awesome Project"
        assert slug == "my-awesome-project"

    def test_slug_replaces_special_chars(self, req_file):
        yaml_content = textwrap.dedent("""\
            epics:
              - id: E1
                title: "Hello World! (v2.0)"
                features: []
        """)
        _, slug = derive_name(req_file(yaml_content))
        assert slug == "hello-world-v2-0"

    def test_strips_leading_trailing_hyphens_from_slug(self, req_file):
        yaml_content = textwrap.dedent("""\
            epics:
              - id: E1
                title: "---Test---"
                features: []
        """)
        _, slug = derive_name(req_file(yaml_content))
        assert not slug.startswith("-")
        assert not slug.endswith("-")


# ---------------------------------------------------------------------------
# Fallback derivation from story titles (generic epic title)
# ---------------------------------------------------------------------------


class TestDeriveNameFromStoryTitles:
    def test_uses_word_frequency_when_epic_is_generic(self, req_file):
        yaml_content = textwrap.dedent("""\
            epics:
              - id: E1
                title: "Imported Requirements"
                features:
                  - id: F1
                    title: Feature
                    stories:
                      - id: S1
                        title: "Implement dashboard widget"
                      - id: S2
                        title: "Dashboard layout component"
                      - id: S3
                        title: "Dashboard performance metrics"
        """)
        title, slug = derive_name(req_file(yaml_content))
        # "dashboard" should be the most frequent meaningful word
        assert "dashboard" in title.lower()
        assert "dashboard" in slug

    def test_filters_stop_words(self, req_file):
        yaml_content = textwrap.dedent("""\
            epics:
              - id: E1
                title: "General"
                features:
                  - id: F1
                    title: Feature
                    stories:
                      - id: S1
                        title: "The authentication service module"
                      - id: S2
                        title: "Add authentication for the API"
        """)
        title, _ = derive_name(req_file(yaml_content))
        # "the" should be filtered out; "authentication" should appear
        assert "the" not in title.lower().split()
        assert "authentication" in title.lower()


# ---------------------------------------------------------------------------
# Fallback on failure
# ---------------------------------------------------------------------------


class TestDeriveNameFallback:
    def test_returns_default_for_missing_file(self):
        title, slug = derive_name("/nonexistent/path/requirements.yaml")
        assert title == "Agent OS Project"
        assert slug == "agent-os-project"

    def test_returns_default_for_empty_yaml(self, req_file):
        title, slug = derive_name(req_file(""))
        assert title == "Agent OS Project"
        assert slug == "agent-os-project"

    def test_returns_default_for_no_epics(self, req_file):
        yaml_content = "epics: []\n"
        title, slug = derive_name(req_file(yaml_content))
        assert title == "Agent OS Project"
        assert slug == "agent-os-project"

    def test_returns_default_for_invalid_yaml(self, req_file):
        title, slug = derive_name(req_file("{{{{invalid yaml!@#$"))
        assert title == "Agent OS Project"
        assert slug == "agent-os-project"


# ---------------------------------------------------------------------------
# Markdown-embedded YAML
# ---------------------------------------------------------------------------


class TestMarkdownParsing:
    def test_extracts_yaml_from_markdown_fence(self, req_file):
        md_content = textwrap.dedent("""\
            # Requirements

            ```yaml
            epics:
              - id: E1
                title: Markdown Project
                features: []
            ```
        """)
        title, slug = derive_name(req_file(md_content, suffix=".md"))
        assert title == "Markdown Project"
        assert slug == "markdown-project"
