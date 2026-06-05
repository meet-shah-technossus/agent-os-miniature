"""Unit tests for agent_os.git_ops.manager — GitOpsManager with mocked subprocess."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_os.git_ops.manager import GitOpsManager, GitResult


def _make_proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    """Build a mock subprocess.CompletedProcess."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


@pytest.fixture()
def git(tmp_path):
    return GitOpsManager(working_dir=str(tmp_path))


class TestGitResult:
    def test_success_true_on_zero_exit(self):
        result = GitResult(success=True, command="git status")
        assert result.success is True

    def test_failure_false_on_nonzero_exit(self):
        result = GitResult(success=False, command="git status", return_code=1)
        assert result.success is False


class TestIsRepo:
    def test_returns_true_when_inside_repo(self, git: GitOpsManager):
        with patch("subprocess.run", return_value=_make_proc(0, "true")):
            assert git.is_repo() is True

    def test_returns_false_when_not_repo(self, git: GitOpsManager):
        with patch("subprocess.run", return_value=_make_proc(128, "", "not a repo")):
            assert git.is_repo() is False

    def test_returns_false_when_git_not_found(self, git: GitOpsManager):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert git.is_repo() is False


class TestCurrentBranch:
    def test_returns_branch_name(self, git: GitOpsManager):
        with patch("subprocess.run", return_value=_make_proc(0, "main\n")):
            branch = git.current_branch()
        assert branch == "main"

    def test_returns_none_on_failure(self, git: GitOpsManager):
        with patch("subprocess.run", return_value=_make_proc(128, "", "error")):
            assert git.current_branch() is None

    def test_strips_whitespace(self, git: GitOpsManager):
        with patch("subprocess.run", return_value=_make_proc(0, "  feature/branch  \n")):
            branch = git.current_branch()
        assert branch == "feature/branch"


class TestBranchExists:
    def test_existing_branch_returns_true(self, git: GitOpsManager):
        with patch("subprocess.run", return_value=_make_proc(0)):
            assert git.branch_exists("main") is True

    def test_nonexistent_branch_returns_false(self, git: GitOpsManager):
        with patch("subprocess.run", return_value=_make_proc(128, "", "error")):
            assert git.branch_exists("no-such-branch") is False


class TestCreateBranch:
    def test_creates_new_branch(self, git: GitOpsManager):
        # branch_exists → False, then create → True
        with patch("subprocess.run", side_effect=[
            _make_proc(128, "", "not found"),  # branch_exists check
            _make_proc(0),                     # git branch create
        ]):
            result = git.create_branch("feature/test")
        assert result.success is True

    def test_no_op_if_branch_exists(self, git: GitOpsManager):
        with patch("subprocess.run", return_value=_make_proc(0)):
            result = git.create_branch("main")
        assert result.success is True
        assert result.stdout == "already exists"


class TestCheckout:
    def test_checkout_succeeds(self, git: GitOpsManager):
        with patch("subprocess.run", return_value=_make_proc(0)):
            result = git.checkout("main")
        assert result.success is True

    def test_checkout_fails(self, git: GitOpsManager):
        with patch("subprocess.run", return_value=_make_proc(1, "", "pathspec error")):
            result = git.checkout("nonexistent")
        assert result.success is False


class TestStageAll:
    def test_stage_all_returns_success(self, git: GitOpsManager):
        with patch("subprocess.run", return_value=_make_proc(0)):
            result = git.stage_all()
        assert result.success is True


class TestHasChanges:
    def test_no_changes(self, git: GitOpsManager):
        with patch("subprocess.run", return_value=_make_proc(0, "")):
            assert git.has_changes() is False

    def test_has_changes(self, git: GitOpsManager):
        with patch("subprocess.run", return_value=_make_proc(0, "M  file.py\n")):
            assert git.has_changes() is True


class TestHasStagedChanges:
    def test_no_staged_changes(self, git: GitOpsManager):
        # diff --cached --quiet exits 0 if no staged changes
        with patch("subprocess.run", return_value=_make_proc(0)):
            assert git.has_staged_changes() is False

    def test_has_staged_changes(self, git: GitOpsManager):
        # exits 1 when there are staged changes
        with patch("subprocess.run", return_value=_make_proc(1)):
            assert git.has_staged_changes() is True


class TestCommit:
    def test_commit_with_staged_changes(self, git: GitOpsManager):
        with patch("subprocess.run", side_effect=[
            _make_proc(1),         # has_staged_changes (1 = changes exist)
            _make_proc(0),         # git commit
        ]):
            result = git.commit("test message")
        assert result.success is True

    def test_commit_stages_and_commits_when_nothing_staged(self, git: GitOpsManager):
        with patch("subprocess.run", side_effect=[
            _make_proc(0),         # has_staged_changes → False (0 = no staged changes)
            _make_proc(0),         # stage_all
            _make_proc(0),         # has_staged_changes again → False (0 = nothing staged)
        ]):
            result = git.commit("test message")
        # Nothing to commit — returns success with "nothing to commit"
        assert result.success is True

    def test_git_not_found_returns_failure(self, git: GitOpsManager):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = git._run("status")
        assert result.success is False
        assert "git not found" in result.stderr

    def test_timeout_returns_failure(self, git: GitOpsManager):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 60)):
            result = git._run("push")
        assert result.success is False
        assert "timed out" in result.stderr
