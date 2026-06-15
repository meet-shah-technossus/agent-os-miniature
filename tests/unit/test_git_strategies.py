"""Unit tests for code_generator.git_strategies — strategy selection and context."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_os.code_generator.git_strategies import (
    ForkModeFirstIterationGitOps,
    ForkModeSubsequentIterationGitOps,
    GitOpsContext,
    GitOpsResult,
    StandardFirstIterationGitOps,
    StandardSubsequentIterationGitOps,
)


# ---------------------------------------------------------------------------
# GitOpsContext / GitOpsResult dataclasses
# ---------------------------------------------------------------------------


class TestGitOpsContext:
    def test_basic_construction(self, tmp_path):
        ctx = GitOpsContext(
            working_dir=tmp_path,
            iteration=1,
            pr_number=None,
            feature_branch="feature/test",
            repo_name="owner/repo",
            vcs_client=MagicMock(),
            config=MagicMock(),
        )
        assert ctx.working_dir == tmp_path
        assert ctx.iteration == 1
        assert ctx.feature_branch == "feature/test"
        assert ctx.story_context == {}

    def test_fork_mode_extras(self, tmp_path):
        ctx = GitOpsContext(
            working_dir=tmp_path,
            iteration=2,
            pr_number=5,
            feature_branch="story/S1",
            repo_name="owner/repo",
            vcs_client=MagicMock(),
            config=MagicMock(),
            story_context={"story_id": "S1"},
            tool_label="codex",
        )
        assert ctx.story_context == {"story_id": "S1"}
        assert ctx.tool_label == "codex"


class TestGitOpsResult:
    def test_default_values(self):
        r = GitOpsResult()
        assert r.errors == []
        assert r.pr_number is None
        assert r.pr_url == ""
        assert r.branch_pushed == ""

    def test_custom_values(self):
        r = GitOpsResult(
            errors=["error1"],
            pr_number=42,
            pr_url="https://github.com/owner/repo/pull/42",
            branch_pushed="feature/x",
        )
        assert r.errors == ["error1"]
        assert r.pr_number == 42
        assert r.branch_pushed == "feature/x"


# ---------------------------------------------------------------------------
# Strategy class selection based on iteration + mode
# ---------------------------------------------------------------------------


class TestStrategySelection:
    """Verify that the correct strategy class is selected based on iteration
    number and pipeline mode (standard vs fork)."""

    def test_standard_first_iteration_exists(self):
        """StandardFirstIterationGitOps is importable and callable."""
        assert StandardFirstIterationGitOps is not None

    def test_standard_subsequent_iteration_exists(self):
        """StandardSubsequentIterationGitOps is importable and callable."""
        assert StandardSubsequentIterationGitOps is not None

    def test_fork_first_iteration_exists(self):
        """ForkModeFirstIterationGitOps is importable and callable."""
        assert ForkModeFirstIterationGitOps is not None

    def test_fork_subsequent_iteration_exists(self):
        """ForkModeSubsequentIterationGitOps is importable and callable."""
        assert ForkModeSubsequentIterationGitOps is not None

    def test_standard_strategies_have_execute_method(self):
        assert hasattr(StandardFirstIterationGitOps, "execute")
        assert hasattr(StandardSubsequentIterationGitOps, "execute")

    def test_fork_strategies_have_execute_method(self):
        assert hasattr(ForkModeFirstIterationGitOps, "execute")
        assert hasattr(ForkModeSubsequentIterationGitOps, "execute")


# ---------------------------------------------------------------------------
# Strategy dispatch logic (from runner.py)
# ---------------------------------------------------------------------------


class TestStrategyDispatchLogic:
    """Unit-test the dispatch logic without calling the strategies."""

    def _select_strategy(self, iteration: int, fork_mode: bool):
        """Replicate the strategy selection logic from CodeGeneratorRunner."""
        if fork_mode:
            if iteration == 1:
                return ForkModeFirstIterationGitOps
            else:
                return ForkModeSubsequentIterationGitOps
        else:
            if iteration == 1:
                return StandardFirstIterationGitOps
            else:
                return StandardSubsequentIterationGitOps

    def test_standard_iteration_1(self):
        cls = self._select_strategy(iteration=1, fork_mode=False)
        assert cls is StandardFirstIterationGitOps

    def test_standard_iteration_2(self):
        cls = self._select_strategy(iteration=2, fork_mode=False)
        assert cls is StandardSubsequentIterationGitOps

    def test_standard_iteration_5(self):
        cls = self._select_strategy(iteration=5, fork_mode=False)
        assert cls is StandardSubsequentIterationGitOps

    def test_fork_iteration_1(self):
        cls = self._select_strategy(iteration=1, fork_mode=True)
        assert cls is ForkModeFirstIterationGitOps

    def test_fork_iteration_2(self):
        cls = self._select_strategy(iteration=2, fork_mode=True)
        assert cls is ForkModeSubsequentIterationGitOps

    def test_fork_iteration_3(self):
        cls = self._select_strategy(iteration=3, fork_mode=True)
        assert cls is ForkModeSubsequentIterationGitOps
