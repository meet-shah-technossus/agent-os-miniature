"""Characterization tests — standard pipeline mode (IDLE → PIPELINE_COMPLETE).

These tests lock down the happy-path behaviour of the standard pipeline so
that refactoring in later phases cannot silently break it.

All external dependencies (LLM runners, VCS, ADO) are mocked.
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_os.code_generator.completion import CompletionResult, CompletionStatus
from agent_os.code_generator.runner import CodeGenResult
from agent_os.code_reviewer.schema import ReviewJSON, ReviewRunResult
from agent_os.codex.session import CodexResult
from agent_os.config.schema import AgentOSConfig
from agent_os.orchestrator.engine import Orchestrator
from agent_os.storage.models import PipelineStatus


SAMPLE_REQUIREMENTS = textwrap.dedent("""\
    epics:
      - id: E1
        title: Test Epic
        features:
          - id: F1
            title: Test Feature
            stories:
              - id: S1
                title: Test Story
                acceptance_criteria:
                  - id: AC1
                    title: Test AC
""")


@pytest.fixture()
def standard_config(tmp_path: Path) -> AgentOSConfig:
    req_file = tmp_path / "requirements.yaml"
    req_file.write_text(SAMPLE_REQUIREMENTS, encoding="utf-8")
    return AgentOSConfig(
        storage={"db_path": ":memory:"},
        requirements={"path": str(req_file)},
        orchestrator={"auto_approve_hitl": True},
        pipeline_mode="standard",
    )


def _make_gen_result() -> CodeGenResult:
    return CodeGenResult(
        completion=CompletionResult(CompletionStatus.COMPLETE),
        codex_result=CodexResult(exit_code=0, stdout="done", stderr=""),
        pr_number=1,
        pr_url="https://github.com/test/repo/pull/1",
    )


def _make_review_result(accepted: bool = True) -> ReviewRunResult:
    review = ReviewJSON(
        overall_status="accepted" if accepted else "needs_work",
        overall_score=90 if accepted else 60,
        checklist_scores={k: 90 for k in ["code_correctness", "readability"]},
    )
    return ReviewRunResult(review=review, pr_merged=accepted)


def _run_standard_pipeline(config: AgentOSConfig) -> Orchestrator:
    """Run a full standard pipeline with all external calls mocked."""
    orch = Orchestrator(config)
    with (
        patch("agent_os.prompt_generator.runner.PromptGeneratorRunner") as MockPGR,
        patch("agent_os.code_generator.runner.CodeGeneratorRunner") as MockCGR,
        patch("agent_os.vcs.factory.make_vcs_client", return_value=None),
        patch("agent_os.code_reviewer.runner.CodeReviewerRunner") as MockCRR,
        patch.object(orch, "_close_ado_work_items"),
        patch.object(orch, "_activate_ado_work_items"),
    ):
        MockPGR.return_value.run.return_value = "Mock generated prompt for iteration 1"
        mock_cg = MockCGR.return_value
        mock_cg._codex = MagicMock()
        mock_cg.run.return_value = _make_gen_result()
        MockCRR.return_value.run.return_value = _make_review_result(accepted=True)
        orch.run()
    return orch


class TestStandardPipelineReachesComplete:
    def test_final_status_is_pipeline_complete(self, standard_config: AgentOSConfig):
        orch = _run_standard_pipeline(standard_config)
        assert orch.state_mgr.current_status == PipelineStatus.PIPELINE_COMPLETE

    def test_iteration_is_1_on_completion(self, standard_config: AgentOSConfig):
        orch = _run_standard_pipeline(standard_config)
        assert orch.state_mgr.state.current_iteration == 1

    def test_prompt_content_stored_in_metadata(self, standard_config: AgentOSConfig):
        orch = _run_standard_pipeline(standard_config)
        assert orch.state_mgr.state.metadata.get("prompt_content") == (
            "Mock generated prompt for iteration 1"
        )

    def test_pr_number_stored_in_metadata(self, standard_config: AgentOSConfig):
        orch = _run_standard_pipeline(standard_config)
        assert orch.state_mgr.state.metadata.get("pr_number") == 1

    def test_review_status_accepted_in_metadata(self, standard_config: AgentOSConfig):
        orch = _run_standard_pipeline(standard_config)
        assert orch.state_mgr.state.metadata.get("review_overall_status") == "accepted"

    def test_completion_status_stored(self, standard_config: AgentOSConfig):
        orch = _run_standard_pipeline(standard_config)
        assert orch.state_mgr.state.metadata.get("completion_status") == "complete"


class TestStandardPipelineIterationRow:
    def test_iteration_row_created_in_db(self, standard_config: AgentOSConfig):
        orch = _run_standard_pipeline(standard_config)
        row = orch.db.conn.execute(
            "SELECT status FROM iterations WHERE iteration_number = 1"
        ).fetchone()
        assert row is not None

    def test_iteration_row_status_completed(self, standard_config: AgentOSConfig):
        orch = _run_standard_pipeline(standard_config)
        row = orch.db.conn.execute(
            "SELECT status FROM iterations WHERE iteration_number = 1"
        ).fetchone()
        assert row["status"] == "completed"


class TestStandardPipelineStartingConditions:
    def test_pipeline_starts_at_idle(self, standard_config: AgentOSConfig):
        orch = Orchestrator(standard_config)
        assert orch.state_mgr.current_status == PipelineStatus.IDLE

    def test_stop_event_exits_loop_immediately(self, standard_config: AgentOSConfig):
        orch = Orchestrator(standard_config)
        orch._stop_event.set()
        orch._loop()
        # Loop exits without transitioning — still IDLE
        assert orch.state_mgr.current_status == PipelineStatus.IDLE


class TestStandardPipelineFailurePath:
    def test_runner_exception_transitions_to_failed(self, standard_config: AgentOSConfig):
        orch = Orchestrator(standard_config)
        with (
            patch("agent_os.prompt_generator.runner.PromptGeneratorRunner") as MockPGR,
            patch("agent_os.code_generator.runner.CodeGeneratorRunner") as MockCGR,
            patch("agent_os.vcs.factory.make_vcs_client", return_value=None),
            patch.object(orch, "_activate_ado_work_items"),
        ):
            MockPGR.return_value.run.return_value = "prompt"
            mock_cg = MockCGR.return_value
            mock_cg._codex = MagicMock()
            mock_cg.run.side_effect = RuntimeError("Codex crashed")
            orch.run()
        # Unhandled exception in a step transitions to FAILED or CODE_GEN_FAILED
        assert orch.state_mgr.current_status in (
            PipelineStatus.FAILED, PipelineStatus.CODE_GEN_FAILED
        )
