"""Characterization tests — CodeReviewerRunner flow.

Locks down: diff fetch → LLM streaming → ReviewJSON parse → PR comment posting.
All VCS and OpenAI calls are mocked.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_os.code_reviewer.runner import CodeReviewerRunner
from agent_os.code_reviewer.schema import ReviewJSON, ReviewRunResult
from agent_os.config.schema import AgentOSConfig
from agent_os.vcs.base import VCSResult


_MOCK_REVIEW_JSON_STR = """\
{
  "overall_status": "accepted",
  "overall_score": 85,
  "checklist_scores": {
    "code_correctness": 90,
    "readability": 80,
    "structure_design": 85,
    "performance": 80,
    "security": 90,
    "error_handling": 80,
    "code_standards": 85,
    "testing": 80,
    "documentation": 80,
    "maintainability": 85,
    "dependencies": 90,
    "logging": 80,
    "version_control": 90,
    "ui_ux": 100,
    "overall_impact": 85
  },
  "line_comments": [],
  "global_comments": [],
  "folder_structure_issues": [],
  "architecture_issues": [],
  "file_size_violations": [],
  "summary": "Looks good."
}
"""


@pytest.fixture()
def config(tmp_path: Path) -> AgentOSConfig:
    review_file = tmp_path / "review.json"
    return AgentOSConfig(
        storage={"db_path": ":memory:"},
        project={"review_json_path": str(review_file)},
    )


@pytest.fixture()
def mock_vcs() -> MagicMock:
    vcs = MagicMock()
    vcs.get_pr_diff.return_value = VCSResult(
        success=True,
        data={"diff": "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n+print('hello')\n"},
    )
    vcs.get_pr_files.return_value = VCSResult(success=True, data={"files": []})
    vcs.get_pr_info.return_value = VCSResult(
        success=True, data={"number": 1, "title": "Test PR", "html_url": "https://github.com/test/pull/1"}
    )
    vcs.post_review_comment.return_value = VCSResult(success=True)
    vcs.post_pr_comment.return_value = VCSResult(success=True)
    vcs.merge_pr.return_value = VCSResult(success=True)
    vcs.delete_branch.return_value = VCSResult(success=True)
    return vcs


class TestCodeReviewerRunnerInit:
    def test_runner_instantiates(self, config: AgentOSConfig, mock_vcs: MagicMock):
        runner = CodeReviewerRunner(config, vcs_client=mock_vcs)
        assert runner is not None

    def test_runner_accepts_no_vcs(self, config: AgentOSConfig):
        runner = CodeReviewerRunner(config, vcs_client=None)
        assert runner is not None


class TestCodeReviewerRunnerRun:
    def _run_with_mocked_llm(
        self,
        config: AgentOSConfig,
        mock_vcs: MagicMock,
        review_json_str: str = _MOCK_REVIEW_JSON_STR,
    ) -> ReviewRunResult:
        runner = CodeReviewerRunner(config, vcs_client=mock_vcs)
        # Mock the LLM streaming call to return our canned JSON
        with patch.object(runner, "_stream_review", return_value=review_json_str):
            result = runner.run(
                pr_number=1,
                iteration=1,
                feature_branch="feature/test",
            )
        return result

    def test_run_returns_review_run_result(self, config: AgentOSConfig, mock_vcs: MagicMock):
        result = self._run_with_mocked_llm(config, mock_vcs)
        assert isinstance(result, ReviewRunResult)

    def test_review_is_review_json(self, config: AgentOSConfig, mock_vcs: MagicMock):
        result = self._run_with_mocked_llm(config, mock_vcs)
        assert isinstance(result.review, ReviewJSON)

    def test_accepted_status(self, config: AgentOSConfig, mock_vcs: MagicMock):
        result = self._run_with_mocked_llm(config, mock_vcs)
        assert result.review.overall_status == "accepted"

    def test_overall_score(self, config: AgentOSConfig, mock_vcs: MagicMock):
        result = self._run_with_mocked_llm(config, mock_vcs)
        assert result.review.overall_score == 85

    def test_review_json_path_set(self, config: AgentOSConfig, mock_vcs: MagicMock):
        result = self._run_with_mocked_llm(config, mock_vcs)
        assert result.review_json_path != ""


class TestReviewJSONSchema:
    def test_default_overall_status_is_needs_work(self):
        review = ReviewJSON()
        assert review.overall_status == "needs_work"

    def test_compute_overall_score(self):
        review = ReviewJSON(checklist_scores={"a": 80, "b": 60})
        score = review.compute_overall_score()
        assert score == 70

    def test_has_blocking_issues_false_with_no_comments(self):
        review = ReviewJSON()
        assert review.has_blocking_issues is False

    def test_review_json_serialization(self):
        review = ReviewJSON(overall_status="accepted", overall_score=90)
        data = review.model_dump()
        assert data["overall_status"] == "accepted"
        assert data["overall_score"] == 90

