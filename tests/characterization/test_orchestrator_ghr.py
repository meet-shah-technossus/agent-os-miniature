"""Characterization tests — GitHub Review mode pipeline.

These tests lock down the GHR story-based pipeline behaviour so that
refactoring cannot silently break it.  All external dependencies (LLM, VCS,
ADO, story queue analysis) are mocked.
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_os.code_generator.completion import CompletionResult, CompletionStatus
from agent_os.code_generator.runner import CodeGenResult
from agent_os.code_reviewer.schema import ReviewJSON, ReviewRunResult
from agent_os.codex.session import CodexResult
from agent_os.config.schema import AgentOSConfig
from agent_os.orchestrator.engine import Orchestrator
from agent_os.orchestrator.story_queue import StoryQueueItem, StoryStatus
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


def _make_story_queue_item(story_id: str = "S1", title: str = "Test Story") -> StoryQueueItem:
    return StoryQueueItem(
        story_id=story_id,
        title=title,
        description="",
        acceptance_criteria=["Test AC"],
        position=0,
        status=StoryStatus.QUEUED,
    )


def _make_gen_result() -> CodeGenResult:
    return CodeGenResult(
        completion=CompletionResult(CompletionStatus.COMPLETE),
        codex_result=CodexResult(exit_code=0, stdout="done", stderr=""),
        pr_number=2,
        pr_url="https://github.com/test/repo/pull/2",
    )


def _make_review_result(accepted: bool = True) -> ReviewRunResult:
    review = ReviewJSON(
        overall_status="accepted" if accepted else "needs_work",
        overall_score=90 if accepted else 60,
    )
    return ReviewRunResult(review=review, pr_merged=accepted)


@pytest.fixture()
def ghr_config(tmp_path: Path) -> AgentOSConfig:
    req_file = tmp_path / "requirements.yaml"
    req_file.write_text(SAMPLE_REQUIREMENTS, encoding="utf-8")
    return AgentOSConfig(
        storage={"db_path": ":memory:"},
        requirements={"path": str(req_file)},
        orchestrator={"auto_approve_hitl": True},
        pipeline_mode="github_review",
        project={"root_path": str(tmp_path)},  # skip fork+clone step
    )


def _run_ghr_pipeline(config: AgentOSConfig) -> Orchestrator:
    """Run a full GHR pipeline with all external calls mocked."""
    story_item = _make_story_queue_item()
    orch = Orchestrator(config)

    with (
        patch("agent_os.orchestrator.story_queue.StoryQueueManager") as MockSQM,
        patch("agent_os.prompt_generator.runner.PromptGeneratorRunner") as MockPGR,
        patch("agent_os.code_generator.runner.CodeGeneratorRunner") as MockCGR,
        patch("agent_os.vcs.factory.make_vcs_client", return_value=None),
        patch("agent_os.code_reviewer.runner.CodeReviewerRunner") as MockCRR,
        patch.object(orch, "_close_ado_work_items"),
        patch.object(orch, "_activate_ado_work_items"),
        patch.object(orch, "_fork_and_clone", return_value=True),
    ):
        # StoryQueueManager mocks
        mock_sqm_instance = MockSQM.return_value
        # build_queue returns [story_item], dequeue returns item once then None
        mock_sqm_instance.build_queue = AsyncMock(return_value=[story_item])
        _dequeue_calls = iter([story_item, None])
        mock_sqm_instance.dequeue.side_effect = lambda: next(_dequeue_calls)
        mock_sqm_instance.get_item.return_value = story_item
        mock_sqm_instance.is_complete.return_value = True
        mock_sqm_instance.counts.return_value = {"queued": 0, "in_progress": 0,
                                                   "completed": 1, "failed": 0}
        mock_sqm_instance.mark_complete = MagicMock()
        mock_sqm_instance.increment_iteration = MagicMock()
        mock_sqm_instance.update_branch = MagicMock()

        # Runner mocks
        MockPGR.return_value.run.return_value = "GHR mock prompt"
        mock_cg = MockCGR.return_value
        mock_cg._codex = MagicMock()
        mock_cg.run.return_value = _make_gen_result()
        MockCRR.return_value.run.return_value = _make_review_result(accepted=True)

        orch.run()
    return orch


class TestGHRPipelineReachesComplete:
    def test_final_status_is_pipeline_complete(self, ghr_config: AgentOSConfig):
        orch = _run_ghr_pipeline(ghr_config)
        assert orch.state_mgr.current_status == PipelineStatus.PIPELINE_COMPLETE

    def test_story_context_set(self, ghr_config: AgentOSConfig):
        orch = _run_ghr_pipeline(ghr_config)
        assert orch.state_mgr.state.current_story_id == "S1"

    def test_prompt_content_stored(self, ghr_config: AgentOSConfig):
        orch = _run_ghr_pipeline(ghr_config)
        assert orch.state_mgr.state.metadata.get("prompt_content") == "GHR mock prompt"

    def test_review_accepted(self, ghr_config: AgentOSConfig):
        orch = _run_ghr_pipeline(ghr_config)
        assert orch.state_mgr.state.metadata.get("review_overall_status") == "accepted"


class TestGHRPipelineStartingConditions:
    def test_pipeline_starts_at_idle(self, ghr_config: AgentOSConfig):
        orch = Orchestrator(ghr_config)
        assert orch.state_mgr.current_status == PipelineStatus.IDLE

    def test_pipeline_mode_is_github_review(self, ghr_config: AgentOSConfig):
        assert ghr_config.pipeline_mode == "github_review"
