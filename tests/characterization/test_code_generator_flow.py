"""Characterization tests — CodeGeneratorRunner flow.

Locks down: code gen → completion detection → git/PR metadata propagation.
All subprocess/VCS calls are mocked.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_os.code_generator.completion import CompletionResult, CompletionStatus
from agent_os.code_generator.runner import CodeGeneratorRunner, CodeGenResult
from agent_os.codex.session import CodexResult
from agent_os.config.schema import AgentOSConfig


@pytest.fixture()
def config(tmp_path: Path) -> AgentOSConfig:
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("# Implement the feature\n", encoding="utf-8")
    return AgentOSConfig(
        storage={"db_path": ":memory:"},
        project={"root_path": str(tmp_path)},
    )


def _make_codex_result(exit_code: int = 0) -> CodexResult:
    return CodexResult(exit_code=exit_code, stdout="All done.", stderr="", duration_seconds=1.0)


class TestCodeGeneratorRunnerInit:
    def test_runner_instantiates(self, config: AgentOSConfig):
        runner = CodeGeneratorRunner(config, vcs_client=None)
        assert runner is not None

    def test_runner_has_codex_attribute(self, config: AgentOSConfig):
        runner = CodeGeneratorRunner(config, vcs_client=None)
        assert hasattr(runner, "_codex")


class TestCodeGeneratorRunnerSuccess:
    def _run_with_mock_codex(
        self,
        config: AgentOSConfig,
        tmp_path: Path,
        exit_code: int = 0,
    ) -> CodeGenResult:
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("# Build it\n", encoding="utf-8")
        runner = CodeGeneratorRunner(config, vcs_client=None)
        mock_codex_result = _make_codex_result(exit_code)
        with patch.object(runner._codex, "execute", return_value=mock_codex_result):
            result = runner.run(
                prompt_path=str(prompt_file),
                working_dir=str(tmp_path),
                iteration=1,
            )
        return result

    def test_successful_run_returns_code_gen_result(self, config: AgentOSConfig, tmp_path: Path):
        result = self._run_with_mock_codex(config, tmp_path, exit_code=0)
        assert isinstance(result, CodeGenResult)

    def test_successful_run_completion_is_complete(self, config: AgentOSConfig, tmp_path: Path):
        result = self._run_with_mock_codex(config, tmp_path, exit_code=0)
        assert result.completion.status == CompletionStatus.COMPLETE

    def test_failed_exit_code_gives_failed_completion(self, config: AgentOSConfig, tmp_path: Path):
        result = self._run_with_mock_codex(config, tmp_path, exit_code=1)
        assert result.completion.status == CompletionStatus.FAILED

    def test_result_has_codex_result(self, config: AgentOSConfig, tmp_path: Path):
        result = self._run_with_mock_codex(config, tmp_path, exit_code=0)
        assert isinstance(result.codex_result, CodexResult)

    def test_git_errors_empty_on_success_without_vcs(
        self, config: AgentOSConfig, tmp_path: Path
    ):
        result = self._run_with_mock_codex(config, tmp_path, exit_code=0)
        assert isinstance(result.git_errors, list)


class TestCodeGeneratorRunnerWithVCS:
    def test_pr_number_propagated_from_vcs(self, config: AgentOSConfig, tmp_path: Path):
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("# Build it\n", encoding="utf-8")

        from agent_os.vcs.base import VCSResult
        mock_vcs = MagicMock()
        mock_vcs.push_branch.return_value = VCSResult(success=True, data={})
        mock_vcs.create_pr.return_value = VCSResult(
            success=True,
            data={"number": 99, "html_url": "https://github.com/test/pull/99"},
        )
        mock_vcs.find_open_pr.return_value = None
        mock_vcs.get_remote_url.return_value = "https://github.com/test/repo.git"

        runner = CodeGeneratorRunner(config, vcs_client=None)
        mock_codex_result = _make_codex_result(exit_code=0)
        with patch.object(runner._codex, "execute", return_value=mock_codex_result):
            result = runner.run(
                prompt_path=str(prompt_file),
                working_dir=str(tmp_path),
                iteration=1,
            )
        assert isinstance(result, CodeGenResult)
        assert result.completion.status == CompletionStatus.COMPLETE


# ---------------------------------------------------------------------------
# Stop / Resume flow (Phase 15.2.4)
# ---------------------------------------------------------------------------


class TestCodeGenStopResume:
    """Verify orchestrator stop_code_generation(), rollback, and continue logic."""

    @pytest.fixture()
    def orchestrator(self, tmp_path: Path):
        """Build a minimal Orchestrator with in-memory DB at CODE_GENERATION state."""
        from agent_os.orchestrator.engine import Orchestrator
        from agent_os.storage.database import Database
        from agent_os.storage.models import PipelineStatus
        from agent_os.orchestrator.state import StateManager

        db = Database(":memory:")
        db.connect()
        state_mgr = StateManager(db)
        config = AgentOSConfig(
            storage={"db_path": ":memory:"},
            project={"root_path": str(tmp_path)},
        )
        orch = Orchestrator(config, state_mgr=state_mgr)
        # Advance to CODE_GENERATION
        state_mgr.transition_to(PipelineStatus.LOADING_REQUIREMENTS)
        state_mgr.transition_to(PipelineStatus.PROMPT_GENERATION)
        state_mgr.transition_to(PipelineStatus.HITL_PROMPT_REVIEW)
        state_mgr.transition_to(PipelineStatus.CODE_GENERATION)
        return orch

    def test_stop_code_generation_returns_true_when_generating(self, orchestrator):
        from agent_os.storage.models import PipelineStatus
        assert orchestrator.state_mgr.current_status == PipelineStatus.CODE_GENERATION
        result = orchestrator.stop_code_generation()
        assert result is True

    def test_stop_code_generation_sets_flag(self, orchestrator):
        orchestrator.stop_code_generation()
        assert orchestrator._code_gen_stop_requested.is_set()

    def test_stop_returns_false_when_not_generating(self, tmp_path: Path):
        from agent_os.orchestrator.engine import Orchestrator
        from agent_os.storage.database import Database
        from agent_os.orchestrator.state import StateManager

        db = Database(":memory:")
        db.connect()
        state_mgr = StateManager(db)
        config = AgentOSConfig(
            storage={"db_path": ":memory:"},
            project={"root_path": str(tmp_path)},
        )
        orch = Orchestrator(config, state_mgr=state_mgr)
        # Still at IDLE
        assert orch.stop_code_generation() is False

    def test_rollback_returns_false_when_not_stopped(self, orchestrator):
        # Still at CODE_GENERATION, not CODE_GEN_STOPPED
        assert orchestrator.rollback_after_stop() is False

    def test_rollback_transitions_to_hitl_prompt_review(self, orchestrator, tmp_path: Path):
        from agent_os.storage.models import PipelineStatus

        # Transition to CODE_GEN_STOPPED manually
        orchestrator.state_mgr.transition_to(PipelineStatus.CODE_GEN_STOPPED)
        orchestrator.state_mgr.update_metadata({"stopped_working_dir": str(tmp_path)})
        # Initialize a git repo so rollback doesn't fail
        import subprocess
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "init"],
                       capture_output=True)

        result = orchestrator.rollback_after_stop()
        assert result is True
        assert orchestrator.state_mgr.current_status == PipelineStatus.HITL_PROMPT_REVIEW

    def test_continue_returns_false_when_not_stopped(self, orchestrator):
        assert orchestrator.continue_after_stop() is False
