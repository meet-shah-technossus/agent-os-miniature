"""Orchestrator engine — simple linear iteration loop for the POC pipeline.

State machine:
  IDLE → LOADING_REQUIREMENTS → PROMPT_GENERATION → HITL_PROMPT_REVIEW
       → CODE_GENERATION → CODE_REVIEW → HITL_REVIEW_DECISION
       → PROMPT_GENERATION (loop) ... → PIPELINE_COMPLETE

Phase 3 will wire in the real prompt-generator, code-generator, and
code-reviewer components. For now those steps are stubs.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from rich.console import Console

from ..config.schema import AgentOSConfig
from ..constants import EventChannel, EventType, PipelineMode, TerminalEvent, PROJECT_NAME_STOP_WORDS
from ..storage.database import Database
from ..storage.models import PipelineState, PipelineStatus
from .emitter import WebSocketEmitter
from .state import StateManager

logger = logging.getLogger(__name__)
console = Console()


class Orchestrator:
    """Autonomous SDLC pipeline orchestrator — POC linear loop."""

    def __init__(
        self,
        config: AgentOSConfig,
        db: Any | None = None,
        state_mgr: Any | None = None,
    ) -> None:
        self.config = config

        # Allow dependency injection for testing; default to real implementations.
        if db is not None:
            self.db = db
        else:
            self.db = Database(config.storage.db_path)
            self.db.connect()

        if state_mgr is not None:
            self.state_mgr = state_mgr
        else:
            self.state_mgr = StateManager(self.db)

        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        # Stop-code-generation support
        self._code_gen_stop_requested = threading.Event()
        self._active_codex_wrapper = None  # CodexWrapper instance during code gen steps
        self._wrapper_lock = threading.Lock()  # Protects _active_codex_wrapper
        self._loop_thread: Optional[threading.Thread] = None

        # WebSocket emitter — delegates event broadcasting
        self._emitter = WebSocketEmitter(self.state_mgr)

        # Register state transition listener for auto-marking iterations complete/failed
        self.state_mgr.on_transition(self._on_state_transition)

    def _on_state_transition(
        self,
        old_status: PipelineStatus,
        new_status: PipelineStatus,
        new_state: Any,
    ) -> None:
        """Auto-update iteration row status when pipeline enters terminal states."""
        iter_num: int = new_state.current_iteration
        if not iter_num:
            return
        if new_status == PipelineStatus.FAILED:
            self._upsert_iteration(iter_num, status="failed",
                                   completed_at=datetime.now(timezone.utc).isoformat())
        elif new_status == PipelineStatus.PIPELINE_COMPLETE:
            self._upsert_iteration(iter_num, status="completed",
                                   completed_at=datetime.now(timezone.utc).isoformat())

    def _upsert_iteration(self, iteration_number: int, **kwargs: Any) -> None:
        """Create or update an iteration row in the iterations table.

        On first call for a given iteration_number an INSERT is performed.
        Subsequent calls only SET the provided columns.

        The SELECT + INSERT/UPDATE is wrapped in an explicit transaction to
        prevent TOCTOU races between concurrent threads.
        """
        try:
            conn = self.db.conn
            conn.execute("BEGIN IMMEDIATE")
            try:
                count = conn.execute(
                    "SELECT COUNT(*) FROM iterations WHERE iteration_number = ?",
                    (iteration_number,),
                ).fetchone()[0]
                if count == 0:
                    cols = ["iteration_number", "status", "started_at"] + list(kwargs.keys())
                    vals: list[Any] = [
                        iteration_number,
                        kwargs.pop("status", "in_progress"),
                        kwargs.pop("started_at", datetime.now(timezone.utc).isoformat()),
                        *kwargs.values(),
                    ]
                    placeholders = ", ".join("?" for _ in vals)
                    conn.execute(
                        f"INSERT INTO iterations ({', '.join(cols)}) VALUES ({placeholders})",
                        vals,
                    )
                else:
                    if not kwargs:
                        conn.execute("COMMIT")
                        return
                    set_clause = ", ".join(f"{k} = ?" for k in kwargs)
                    conn.execute(
                        f"UPDATE iterations SET {set_clause} WHERE iteration_number = ?",
                        [*kwargs.values(), iteration_number],
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        except Exception:
            logger.debug("_upsert_iteration(%d) failed", iteration_number, exc_info=True)

    # ── WebSocket integration ──────────────────────────────────────────────────

    def set_ws_queue(self, queue: asyncio.Queue) -> None:
        """Inject the asyncio broadcast queue from the API layer."""
        self._emitter.set_ws_queue(queue)

    @property
    def _ws_queue(self) -> Optional[asyncio.Queue]:
        """Backward-compat property — delegates to emitter."""
        return self._emitter.ws_queue

    @_ws_queue.setter
    def _ws_queue(self, queue: Optional[asyncio.Queue]) -> None:
        """Backward-compat setter — delegates to emitter."""
        self._emitter.set_ws_queue(queue)

    def _emit(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Push a pipeline event onto the WebSocket broadcast queue (non-blocking)."""
        self._emitter.emit(event_type, data)

    def _emit_terminal(
        self,
        event_type: str,
        agent_post: str,
        session_id: str,
        **kwargs: Any,
    ) -> None:
        """Push a terminal_output channel event so the frontend terminal grid
        receives structured session_start / line / session_end events."""
        self._emitter.emit_terminal(event_type, agent_post, session_id, **kwargs)

    # ── Main run loop ──────────────────────────────────────────────────────────

    def run(self) -> None:
        """Run the pipeline from current state to completion or HITL pause.

        Called in a background thread by the API /start route.
        """
        self._stop_event.clear()
        self._pause_event.clear()
        state = self.state_mgr.state
        logger.info("Pipeline run() called — current status: %s", state.pipeline_status.value)
        self._emit(EventType.RUN_STARTED)
        self._loop()

    def _loop(self) -> None:
        """Execute the state machine until paused, complete, HITL, or error.

        Dispatches on ``config.pipeline_mode``:
        - ``"standard"``      → original linear loop (unchanged).
        - ``"github_review"`` → story-aware queue loop (Phase 2).
        """
        from .pipeline_runner import StandardPipelineRunner

        _std_runner = StandardPipelineRunner(self)
        _STANDARD_DISPATCH = {
            PipelineStatus.IDLE:                  self._step_idle,
            PipelineStatus.LOADING_REQUIREMENTS:  self._step_load_requirements,
            PipelineStatus.PROMPT_GENERATION:     _std_runner.step_prompt_generation,
            PipelineStatus.CODE_GENERATION:       _std_runner.step_code_generation,
            PipelineStatus.CODE_REVIEW:           _std_runner.step_code_review,
            PipelineStatus.STORY_COMPLETE:        self._step_story_complete,
        }
        _GHR_DISPATCH = {
            PipelineStatus.IDLE:                      self._step_idle,
            PipelineStatus.LOADING_REQUIREMENTS:      self._step_load_requirements,
            PipelineStatus.ANALYSING_DEPENDENCIES:    self._step_analyse_dependencies,
            PipelineStatus.QUEUE_READY:               self._step_queue_ready,
            PipelineStatus.STORY_PROMPT_GENERATION:   self._step_story_prompt_generation,
            PipelineStatus.STORY_CODE_GENERATION:     self._step_story_code_generation,
            PipelineStatus.STORY_CODE_REVIEW:         self._step_story_code_review,
            PipelineStatus.STORY_COMPLETE:            self._step_story_complete,
        }
        _is_github_review_mode = (self.config.pipeline_mode == PipelineMode.GITHUB_REVIEW)
        _DISPATCH = _GHR_DISPATCH if _is_github_review_mode else _STANDARD_DISPATCH

        while True:
            if self._stop_event.is_set():
                logger.info("Pipeline stopped (reset requested)")
                self._emit(EventType.STOPPED)
                break

            if self._pause_event.is_set():
                logger.info("Pipeline paused by user")
                self._emit(EventType.PAUSED)
                break

            status = self.state_mgr.current_status

            if status == PipelineStatus.PIPELINE_COMPLETE:
                logger.info("Pipeline complete!")
                self._emit(EventType.PIPELINE_COMPLETE)
                # Auto-close ADO work items if they were ingested
                self._close_ado_work_items()
                break

            if status == PipelineStatus.FAILED:
                logger.warning("Pipeline in FAILED state — awaiting reset")
                self._emit(EventType.FAILED)
                break

            if status == PipelineStatus.CODE_GEN_FAILED:
                logger.warning("Pipeline paused at CODE_GEN_FAILED — awaiting retry or reset")
                break

            if status == PipelineStatus.CODE_GEN_STOPPED:
                logger.info("Pipeline stopped by user — awaiting rollback or continue decision")
                self._emit(EventType.CODE_GEN_STOPPED, {
                    "working_dir": self.state_mgr.state.metadata.get("stopped_working_dir", ""),
                })
                break

            if self.state_mgr.is_hitl_gate():
                if self.config.orchestrator.auto_approve_hitl:
                    logger.info("Auto-approving HITL gate: %s", status.value)
                    self._auto_approve(status)
                    continue
                logger.info("Paused at HITL gate: %s", status.value)
                self._emit(EventType.HITL_GATE, {"gate": status.value})
                break

            step = _DISPATCH.get(status)
            if step is None:
                logger.error("No step handler for state: %s", status.value)
                self.state_mgr.transition_to(PipelineStatus.FAILED)
                break

            try:
                import time as _time
                _step_start = _time.perf_counter()
                step()
                _step_ms = round((_time.perf_counter() - _step_start) * 1000, 1)
                logger.info(
                    "Step %s completed in %.1fms",
                    status.value,
                    _step_ms,
                    extra={"step": status.value, "duration_ms": _step_ms},
                )
            except Exception as exc:
                logger.exception("Error in step %s: %s", status.value, exc)
                self.state_mgr.transition_to(PipelineStatus.FAILED)
                self._emit(EventType.ERROR, {"message": str(exc)})
                break

    # ── Step handlers (standard mode) ─────────────────────────────────────────

    def _step_idle(self) -> None:
        """IDLE → LOADING_REQUIREMENTS."""
        self.state_mgr.transition_to(PipelineStatus.LOADING_REQUIREMENTS)
        self._emit(EventType.STATE_CHANGED)

    def _step_load_requirements(self) -> None:
        """LOADING_REQUIREMENTS → PROMPT_GENERATION.

        Loads requirements from the configured source into the DB.
        """
        from ..requirements.parser import RequirementsParser
        req_path = self.config.requirements.path
        logger.info("Loading requirements from: %s", req_path)
        self._emit(EventType.LOADING_REQUIREMENTS, {"path": req_path})

        parser = RequirementsParser(db=self.db)
        stats = parser.load_and_store(req_path)
        logger.info("Requirements loaded: %s", stats)

        # Derive project name — use cached value from metadata if available (Phase 14.3)
        cached_title = self.state_mgr.state.metadata.get("_project_name")
        cached_slug = self.state_mgr.state.metadata.get("_project_slug")
        if cached_title and cached_slug:
            self.config.project.name = cached_title
            self.config.project.repo_name = cached_slug
            logger.info(
                "Project name from cache: %s (repo=%s)", cached_title, cached_slug
            )
        else:
            try:
                from ..services.project_namer import derive_name
                title, slug = derive_name(req_path)
                self.config.project.name = title
                self.config.project.repo_name = slug
                self.state_mgr.update_metadata({"_project_name": title, "_project_slug": slug})
                logger.info(
                    "Project name set from requirements: %s (repo=%s)", title, slug
                )
            except Exception:
                logger.warning("Could not extract project name from requirements", exc_info=True)

        state = self.state_mgr.state
        if self.config.pipeline_mode == PipelineMode.GITHUB_REVIEW:
            self.state_mgr.transition_to(
                PipelineStatus.ANALYSING_DEPENDENCIES,
                iteration=max(state.current_iteration, 1),
            )
        else:
            self.state_mgr.transition_to(
                PipelineStatus.PROMPT_GENERATION,
                iteration=max(state.current_iteration, 1),
            )
        self._emit(EventType.STATE_CHANGED)

    def _step_prompt_generation(self) -> None:
        """PROMPT_GENERATION → HITL_PROMPT_REVIEW. Delegates to StandardPipelineRunner."""
        from .pipeline_runner import StandardPipelineRunner
        StandardPipelineRunner(self).step_prompt_generation()

    def _step_code_generation(self) -> None:
        """CODE_GENERATION → CODE_REVIEW. Delegates to StandardPipelineRunner."""
        from .pipeline_runner import StandardPipelineRunner
        StandardPipelineRunner(self).step_code_generation()

    def _step_code_review(self) -> None:
        """CODE_REVIEW → HITL_REVIEW_DECISION. Delegates to StandardPipelineRunner."""
        from .pipeline_runner import StandardPipelineRunner
        StandardPipelineRunner(self).step_code_review()

    # ── Step handlers (GitHub Review mode) ────────────────────────────────────

    def _fork_and_clone(self) -> bool:
        """Delegates to StoryPipelineRunner."""
        from .story_runner import StoryPipelineRunner
        return StoryPipelineRunner(self).step_fork_and_clone()

    def _step_analyse_dependencies(self) -> None:
        """Delegates to StoryPipelineRunner."""
        from .story_runner import StoryPipelineRunner
        StoryPipelineRunner(self).step_analyse_dependencies()

    def _step_queue_ready(self) -> None:
        """Delegates to StoryPipelineRunner."""
        from .story_runner import StoryPipelineRunner
        StoryPipelineRunner(self).step_queue_ready()

    def _step_story_prompt_generation(self) -> None:
        """Delegates to StoryPipelineRunner."""
        from .story_runner import StoryPipelineRunner
        StoryPipelineRunner(self).step_story_prompt_generation()

    def _step_story_code_generation(self) -> None:
        """Delegates to StoryPipelineRunner."""
        from .story_runner import StoryPipelineRunner
        StoryPipelineRunner(self).step_story_code_generation()

    def _step_story_code_review(self) -> None:
        """Delegates to StoryPipelineRunner."""
        from .story_runner import StoryPipelineRunner
        StoryPipelineRunner(self).step_story_code_review()

    def _step_story_complete(self) -> None:
        """Delegates to StoryPipelineRunner."""
        from .story_runner import StoryPipelineRunner
        StoryPipelineRunner(self).step_story_complete()

    # ── HITL gate approvals ───────────────────────────────────────────────────

    def _auto_approve(self, status: PipelineStatus) -> None:
        """Auto-approve HITL gate (used when auto_approve_hitl=True)."""
        is_ghr = getattr(self.config, "pipeline_mode", "") == PipelineMode.GITHUB_REVIEW
        if status == PipelineStatus.HITL_PROMPT_REVIEW:
            next_status = PipelineStatus.STORY_CODE_GENERATION if is_ghr else PipelineStatus.CODE_GENERATION
            self.state_mgr.transition_to(next_status)
        elif status == PipelineStatus.HITL_REVIEW_DECISION:
            if is_ghr:
                self.state_mgr.transition_to(PipelineStatus.STORY_PROMPT_GENERATION)
            else:
                self.state_mgr.transition_to(PipelineStatus.PIPELINE_COMPLETE)
        self._emit(EventType.STATE_CHANGED)

    def approve_prompt(
        self,
        prompt_content: Optional[str] = None,
        cli_tool: Optional[str] = None,
        cli_model: Optional[str] = None,
    ) -> bool:
        """HITL checkpoint 1 — user approved the generated prompt.

        Args:
            prompt_content: Optional edited prompt text to persist.
            cli_tool: CLI tool name to use for code generation.
            cli_model: Model override for the selected CLI tool.

        Returns True if gate was approved, False if not at the expected gate.
        """
        if self.state_mgr.current_status != PipelineStatus.HITL_PROMPT_REVIEW:
            logger.warning("approve_prompt() called but not at HITL_PROMPT_REVIEW")
            return False

        metadata: dict[str, Any] = {}
        if cli_tool:
            metadata["selected_cli_tool"] = cli_tool
        if cli_model:
            metadata["selected_cli_model"] = cli_model
        if prompt_content is not None:
            metadata["edited_prompt"] = prompt_content
            # Persist to the configured prompt file path
            prompt_path = getattr(self.config.project, "prompt_file_path", "")
            if prompt_path:
                try:
                    Path(prompt_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(prompt_path).write_text(prompt_content, encoding="utf-8")
                    logger.info("Edited prompt saved to: %s", prompt_path)
                except Exception:
                    logger.warning("Could not save prompt to file", exc_info=True)

        if metadata:
            self.state_mgr.update_metadata(metadata)

        is_ghr = getattr(self.config, "pipeline_mode", "") == PipelineMode.GITHUB_REVIEW
        next_status = PipelineStatus.STORY_CODE_GENERATION if is_ghr else PipelineStatus.CODE_GENERATION
        self.state_mgr.transition_to(next_status)
        self._emit(EventType.STATE_CHANGED, {"approved": "prompt"})

        # Resume the pipeline loop in a background thread
        self._resume_in_thread()
        return True

    def approve_review(self) -> bool:
        """HITL checkpoint 2 — user approved the code review JSON.

        If the review was already accepted (reviewer merged the PR), transitions
        directly to PIPELINE_COMPLETE. Otherwise loops back to PROMPT_GENERATION
        for the next iteration, unless max_iterations is reached.
        """
        if self.state_mgr.current_status != PipelineStatus.HITL_REVIEW_DECISION:
            logger.warning("approve_review() called but not at HITL_REVIEW_DECISION")
            return False

        state = self.state_mgr.state

        # If reviewer already accepted, just confirm completion
        review_status = state.metadata.get("review_overall_status", "")
        if review_status == "accepted":
            is_ghr = getattr(self.config, "pipeline_mode", "") == PipelineMode.GITHUB_REVIEW
            if is_ghr:
                self.state_mgr.transition_to(PipelineStatus.STORY_COMPLETE)
                self._emit("story_completed", {"story_id": state.current_story_id, "reason": "user_approved"})
                self._resume_in_thread()
            else:
                self.state_mgr.transition_to(PipelineStatus.PIPELINE_COMPLETE)
                self._emit(EventType.PIPELINE_COMPLETE, {"reason": "user_approved_accepted_review"})
            return True

        is_ghr = getattr(self.config, "pipeline_mode", "") == PipelineMode.GITHUB_REVIEW
        if is_ghr:
            # GHR mode: loop back to story prompt generation for another fix iteration
            self.state_mgr.transition_to(PipelineStatus.STORY_PROMPT_GENERATION)
            self._emit(EventType.STATE_CHANGED, {
                "approved": "review",
                "next": "story_prompt_generation",
                "story_id": state.current_story_id,
            })
            self._resume_in_thread()
        else:
            max_iter = self.config.orchestrator.max_iterations
            if state.current_iteration >= max_iter:
                self.state_mgr.transition_to(PipelineStatus.PIPELINE_COMPLETE)
                self._emit(EventType.PIPELINE_COMPLETE, {"reason": "max_iterations_reached"})
            else:
                self.state_mgr.transition_to(
                    PipelineStatus.PROMPT_GENERATION,
                    iteration=state.current_iteration + 1,
                )
                self._emit(EventType.STATE_CHANGED, {"approved": "review", "next_iteration": state.current_iteration + 1})
                self._resume_in_thread()

        return True

    def move_to_next_story(self) -> bool:
        """Force-advance to the next story: merge current PR, delete branch, then resume.

        Intended to be triggered by the frontend "Move to Next Story" / "Skip Story" button.
        Valid when the pipeline is at ``HITL_REVIEW_DECISION`` or ``STORY_COMPLETE``.

        Steps performed (asynchronously in a background thread):
          1. Resolve open review threads on the PR.
          2. Merge the PR for the current story via the GitHub VCS client.
          3. Delete the feature branch.
          4. Mark the story as complete in the queue.
          5. Transition to ``STORY_COMPLETE``.
          6. Resume the pipeline loop (``_step_story_complete`` picks the next story
             or transitions to ``PIPELINE_COMPLETE`` if the queue is exhausted).

        Returns True if the action was triggered, False if not in the right state.
        """
        current = self.state_mgr.current_status

        # If already at STORY_COMPLETE (e.g. pipeline stuck), just resume the loop
        if current == PipelineStatus.STORY_COMPLETE:
            self._resume_in_thread()
            return True

        if current != PipelineStatus.HITL_REVIEW_DECISION:
            logger.warning("move_to_next_story() called but pipeline is at %s", current)
            return False

        # Capture state snapshot needed by the background work
        state = self.state_mgr.state
        story_id = state.current_story_id
        feature_branch = self.config.project.feature_branch or (f"story-{story_id}" if story_id else "dev")

        pr_number: Optional[int] = None
        pr_raw = state.metadata.get("pr_number")
        if pr_raw is not None:
            try:
                pr_number = int(pr_raw)
            except (TypeError, ValueError):
                pass

        # Transition to STORY_COMPLETE immediately so the API returns fast
        self.state_mgr.transition_to(PipelineStatus.STORY_COMPLETE)
        self._emit("story_completed", {
            "story_id": story_id,
            "reason": "move_to_next_story",
        })

        # Run the heavy GitHub/VCS work + resume in a background thread
        def _finalize_and_resume():
            self._finalize_story_merge(story_id, feature_branch, pr_number, state)
            self._resume_in_thread()

        t = threading.Thread(target=_finalize_and_resume, daemon=True, name="move-to-next-story")
        t.start()
        return True

    def _finalize_story_merge(
        self,
        story_id: Optional[str],
        feature_branch: str,
        pr_number: Optional[int],
        state,
    ) -> None:
        """Perform the slow GitHub operations for move-to-next-story in background."""
        from ..vcs.factory import make_vcs_client
        from ..orchestrator.story_queue import StoryQueueManager

        def _project_vcs():
            vcs = make_vcs_client(self.config)
            if vcs is None:
                return None
            repo = self.config.project.repo_name or ""
            if repo and hasattr(vcs, "for_repo") and repo != getattr(vcs, "_repo", ""):
                return vcs.for_repo(repo)
            return vcs

        vcs = _project_vcs()
        merged = False
        branch_deleted = False
        comments_resolved = False

        if vcs and pr_number:
            # 1. Resolve all open review comments / threads before merging
            try:
                resolve_results = vcs.resolve_all_pr_review_comments(pr_number)
                comments_resolved = all(r.success for r in resolve_results) if resolve_results else True
                logger.info(
                    "[GHR] move_to_next_story: resolved %d comment threads on PR #%d",
                    len(resolve_results), pr_number,
                )
            except Exception:
                logger.warning("[GHR] move_to_next_story: resolve comments raised", exc_info=True)

            # 2. Merge the PR
            try:
                merge_result = vcs.merge_pr(
                    pr_number,
                    commit_message=f"Story {story_id}: merged via Agent OS — Move to Next Story",
                )
                merged = merge_result.success
                if merged:
                    logger.info("[GHR] move_to_next_story: PR #%d merged for story %s", pr_number, story_id)
                else:
                    logger.warning(
                        "[GHR] move_to_next_story: PR #%d merge failed: %s",
                        pr_number, merge_result.error,
                    )
            except Exception:
                logger.warning("[GHR] move_to_next_story: merge PR raised", exc_info=True)

        if vcs and feature_branch:
            try:
                del_result = vcs.delete_branch(feature_branch)
                branch_deleted = del_result.success
                if branch_deleted:
                    logger.info("[GHR] move_to_next_story: deleted branch '%s'", feature_branch)
            except Exception:
                logger.debug("[GHR] move_to_next_story: branch delete raised", exc_info=True)

        # Mark story complete in the queue (idempotent if already marked)
        mgr = StoryQueueManager(self.db)
        mgr.mark_complete(story_id, pr_number=pr_number, pr_url=state.metadata.get("pr_url", ""))

        self.state_mgr.update_story_context(
            stories_completed=state.stories_completed + 1,
        )
        self.state_mgr.update_metadata({
            "pr_merged": str(merged),
            "branch_deleted": str(branch_deleted),
            "comments_resolved": str(comments_resolved),
            "move_to_next_story_triggered": "true",
        })

        # Close the ADO work item for this specific story (Active → Closed)
        self._close_ado_work_items(story_id=story_id)

    def pause(self) -> bool:
        """Request the pipeline to pause after the current step completes."""
        self._pause_event.set()
        logger.info("Pause requested")
        return True

    def stop_code_generation(self) -> bool:
        """Kill the active code-generation subprocess mid-flight.

        Sets a stop-requested flag, calls kill_session() on the active
        CodexWrapper, and transitions the pipeline to CODE_GEN_STOPPED.
        The pipeline loop will then wait for the user to choose rollback or
        save-and-continue (Phase 2 endpoints).

        Returns True if a code-generation step was active and the kill was
        attempted.  Returns False if not currently in a code-generation state.
        """
        from ..codex.session import SessionType

        status = self.state_mgr.current_status
        if status not in (PipelineStatus.CODE_GENERATION, PipelineStatus.STORY_CODE_GENERATION):
            logger.warning(
                "stop_code_generation() called but pipeline is not in a code-generation state (%s)",
                status.value,
            )
            return False

        self._code_gen_stop_requested.set()

        with self._wrapper_lock:
            wrapper = self._active_codex_wrapper
        killed = False
        if wrapper is not None:
            killed = wrapper.kill_session(SessionType.CODE_GENERATOR)
            logger.info("stop_code_generation: kill_session(CODE_GENERATOR) = %s", killed)
        else:
            logger.warning("stop_code_generation: no active wrapper found — stop flag set, process may already be finishing")

        self._emit("code_gen_stopping", {
            "message": "Stop requested — killing code generation subprocess",
            "killed": killed,
        })
        return True

    def rollback_after_stop(self) -> bool:
        """Discard all partial changes from a stopped code-gen session and return
        to HITL_PROMPT_REVIEW so the user can edit the prompt and try again.

        Actions performed:
          1. ``git reset --hard HEAD`` — restore tracked files to last commit.
          2. ``git clean -fd``        — remove untracked files/dirs written by codex.
          3. Transition to HITL_PROMPT_REVIEW.

        Returns True if the action was performed; False if not at CODE_GEN_STOPPED.
        """
        from ..git_ops.manager import GitOpsManager
        from pathlib import Path as _Path

        if self.state_mgr.current_status != PipelineStatus.CODE_GEN_STOPPED:
            logger.warning("rollback_after_stop() called but not at CODE_GEN_STOPPED (current: %s)",
                           self.state_mgr.current_status.value)
            return False

        state = self.state_mgr.state
        working_dir = (
            state.metadata.get("stopped_working_dir", "")
            or getattr(self.config.project, "root_path", "")
            or ""
        )

        if working_dir:
            wd = _Path(working_dir)
            if wd.exists():
                git = GitOpsManager(str(wd))
                r_reset = git.reset_hard("HEAD")
                if r_reset.success:
                    logger.info("rollback_after_stop: hard-reset to HEAD in %s", working_dir)
                else:
                    logger.warning("rollback_after_stop: reset --hard failed: %s", r_reset.stderr)
                r_clean = git._run("clean", "-fd")
                if r_clean.success:
                    logger.info("rollback_after_stop: cleaned untracked files in %s", working_dir)
                else:
                    logger.warning("rollback_after_stop: clean -fd failed: %s", r_clean.stderr)
            else:
                logger.warning("rollback_after_stop: working_dir does not exist: %s", working_dir)
        else:
            logger.warning("rollback_after_stop: no working_dir in metadata — skipping git cleanup")

        self.state_mgr.update_metadata({"stopped_working_dir": "", "code_gen_stopped": False})
        self.state_mgr.transition_to(PipelineStatus.HITL_PROMPT_REVIEW)
        self._emit(EventType.HITL_GATE, {
            "gate": PipelineStatus.HITL_PROMPT_REVIEW.value,
            "reason": "stop_rollback",
        })
        return True

    def continue_after_stop(self) -> bool:
        """Commit and push whatever partial changes exist from a stopped code-gen
        session, then proceed to code review as if generation completed normally.

        Actions performed:
          1. Check for uncommitted changes; if none — roll back instead.
          2. Sanitise .gitignore and ``git rm --cached`` large directories.
          3. ``git commit -m "partial: ..."``.
          4. Push the feature branch and create/find a GitHub PR.
          5. Transition to CODE_REVIEW (standard) or STORY_CODE_REVIEW (GHR).
          6. Resume the pipeline loop.

        Returns True if action was attempted; False if not at CODE_GEN_STOPPED.
        """
        from pathlib import Path as _Path
        from ..code_generator.runner import CodeGeneratorRunner, CodeGenResult
        from ..code_generator.completion import CompletionResult, CompletionStatus
        from ..codex.session import CodexResult
        from ..git_ops.manager import GitOpsManager
        from ..vcs.factory import make_vcs_client

        if self.state_mgr.current_status != PipelineStatus.CODE_GEN_STOPPED:
            logger.warning("continue_after_stop() called but not at CODE_GEN_STOPPED (current: %s)",
                           self.state_mgr.current_status.value)
            return False

        state = self.state_mgr.state
        working_dir = (
            state.metadata.get("stopped_working_dir", "")
            or getattr(self.config.project, "root_path", "")
            or ""
        )
        if not working_dir:
            logger.error("continue_after_stop: no working_dir available — cannot commit")
            return False

        wd = _Path(working_dir)
        git = GitOpsManager(str(wd))

        # If there's nothing to commit, silently roll back to avoid an empty PR
        if not git.has_changes():
            logger.info("continue_after_stop: no changes detected — rolling back to HITL_PROMPT_REVIEW")
            self.state_mgr.update_metadata({"stopped_working_dir": "", "code_gen_stopped": False})
            self.state_mgr.transition_to(PipelineStatus.HITL_PROMPT_REVIEW)
            self._emit(EventType.HITL_GATE, {
                "gate": PipelineStatus.HITL_PROMPT_REVIEW.value,
                "reason": "stop_continue_no_changes",
                "message": "No changes were written — rolled back to prompt review.",
            })
            return True

        is_ghr = (self.config.pipeline_mode == PipelineMode.GITHUB_REVIEW)
        story_id = state.current_story_id
        iteration = (
            state.metadata.get("story_iteration", 1) if is_ghr else state.current_iteration
        )
        pr_number: Optional[int] = None
        pr_raw = state.metadata.get("pr_number")
        if pr_raw is not None:
            try:
                pr_number = int(pr_raw)
            except (TypeError, ValueError):
                pass

        # Build a synthetic CodeGenResult so runner git ops can fill in PR fields
        syn_result = CodeGenResult(
            completion=CompletionResult(status=CompletionStatus.COMPLETE, reason="partial — user stopped"),
            codex_result=CodexResult(exit_code=0, stdout="", stderr=""),
        )

        runner = CodeGeneratorRunner(self.config, vcs_client=make_vcs_client(self.config))

        self._emit("code_gen_continue_started", {
            "working_dir": working_dir,
            "iteration": iteration,
            "story_id": story_id,
        })

        if is_ghr:
            from ..orchestrator.story_queue import StoryQueueManager
            _sq = StoryQueueManager(self.db)
            _item = _sq.get_item(story_id) if story_id else None
            git_errors = runner._git_operations_fork_mode(
                wd, iteration, pr_number, syn_result,
                story_context={
                    "story_id": story_id or "",
                    "title": _item.title if _item else "",
                    "acceptance_criteria": _item.acceptance_criteria if _item else [],
                },
            )
        else:
            git_errors = runner._git_operations(wd, iteration, pr_number, syn_result)

        meta_update: dict = {"code_gen_stopped": False, "stopped_working_dir": ""}
        if syn_result.pr_number is not None:
            meta_update["pr_number"] = syn_result.pr_number
            meta_update["pr_url"] = syn_result.pr_url
        if git_errors:
            meta_update["git_errors"] = git_errors
            logger.warning("continue_after_stop: git errors: %s", git_errors)
        self.state_mgr.update_metadata(meta_update)

        next_status = PipelineStatus.STORY_CODE_REVIEW if is_ghr else PipelineStatus.CODE_REVIEW
        self.state_mgr.transition_to(next_status)
        self._emit(EventType.STATE_CHANGED, {
            "reason": "stop_continue",
            "next": next_status.value,
            "pr_number": syn_result.pr_number,
        })
        self._resume_in_thread()
        return True

    def retry_pr(self) -> bool:
        """Retry pull request creation after a failure.

        Called from the HITL_REVIEW_DECISION gate when pr_failed metadata is
        set. Performs: create repo (if needed) → push code → create PR.
        Emits progress events for each step. On success, transitions to
        CODE_REVIEW and resumes the pipeline loop.

        Returns True for all "retry was attempted" outcomes (including
        operational failures — the updated pr_error in metadata lets the
        frontend show a meaningful message). Returns False only for pre-condition
        failures (wrong pipeline state / missing flag), which map to HTTP 409.
        """
        if self.state_mgr.current_status != PipelineStatus.HITL_REVIEW_DECISION:
            logger.warning(
                "retry_pr() called but not at HITL_REVIEW_DECISION (current: %s)",
                self.state_mgr.current_status.value,
            )
            return False

        state = self.state_mgr.state
        if not state.metadata.get("pr_failed"):
            logger.warning(
                "retry_pr() called but pr_failed is not set in metadata: %s",
                state.metadata,
            )
            return False

        from ..git_ops.manager import GitOpsManager

        iteration = state.current_iteration
        feature_branch = self.config.project.feature_branch or "dev"
        repo_name = self.config.project.repo_name or ""

        def _persist_error(err: str) -> None:
            """Store the error message so the UI shows it and the Retry button stays."""
            self.state_mgr.update_metadata({"pr_error": err})

        working_dir = Path(self.config.project.root_path) if self.config.project.root_path else None
        if not working_dir or not working_dir.exists():
            err = f"Project root_path does not exist: {working_dir}"
            self._emit("pr_retry_progress", {"step": "error", "message": err})
            _persist_error(err)
            return True  # precondition for *git*, not for the gate itself

        # Build VCS client — prefer project repo_name directly so the call works
        # even when config.github.repo is not set as a default.
        token = getattr(self.config.secrets, "github_token", "") or ""
        owner = getattr(self.config.github, "owner", "") or ""
        effective_repo = repo_name or getattr(self.config.github, "repo", "") or ""

        if not token or not owner:
            # Fall back to the factory which logs a proper warning
            from ..vcs.factory import make_vcs_client
            vcs = make_vcs_client(self.config)
        else:
            from ..vcs.github_client import GitHubVCSClient
            vcs = GitHubVCSClient(token=token, owner=owner, repo=effective_repo) if effective_repo else None

        if vcs is None:
            err = "VCS client not configured (check GitHub token / owner / repo_name in Settings)"
            self._emit("pr_retry_progress", {"step": "error", "message": err})
            _persist_error(err)
            return True  # let the frontend update the error banner

        # Ensure the VCS client targets the project repo
        if effective_repo and hasattr(vcs, "for_repo") and effective_repo != getattr(vcs, "_repo", ""):
            vcs = vcs.for_repo(effective_repo)

        # Fast-path: if a PR already exists for the feature branch skip git work
        try:
            _existing_pr = vcs.find_open_pr(feature_branch)
            if _existing_pr is not None:
                self.state_mgr.update_metadata({
                    "pr_number": _existing_pr,
                    "pr_failed": False,
                    "pr_error": "",
                })
                self._emit("pr_retry_progress", {
                    "step": "create_pr",
                    "message": f"Found existing pull request #{_existing_pr} — proceeding to review",
                })
                self._emit("pr_retry_success", {"pr_number": _existing_pr, "iteration": iteration})
                self.state_mgr.transition_to(PipelineStatus.CODE_REVIEW)
                self._resume_in_thread()
                return True
        except Exception:
            pass  # fall through to full git-push path

        # Step 1: Create repo if needed
        self._emit("pr_retry_progress", {"step": "create_repo", "message": "Creating repository..."})
        if effective_repo:
            create_result = vcs.create_repo(effective_repo)
            if create_result.success:
                self._emit("pr_retry_progress", {"step": "create_repo", "message": "Repository created successfully"})
            else:
                err_lower = (create_result.error or "").lower()
                if any(kw in err_lower for kw in ("already exists", "name already", "422", "409")):
                    self._emit("pr_retry_progress", {"step": "create_repo", "message": "Repository already exists"})
                else:
                    err = f"Create repo failed: {create_result.error}"
                    self._emit("pr_retry_progress", {"step": "error", "message": err})
                    _persist_error(err)
                    return True

        # Step 2: Push code
        self._emit("pr_retry_progress", {"step": "push", "message": "Pushing code..."})
        git = GitOpsManager(working_dir)
        remote_url = vcs.get_remote_url(effective_repo)
        _BOT_NAME = "Agent OS"
        _BOT_EMAIL = "agent-os@automated.dev"

        if not git.is_repo():
            r = git.init_repo()
            if not r.success:
                err = f"git init failed: {r.stderr}"
                self._emit("pr_retry_progress", {"step": "error", "message": err})
                _persist_error(err)
                return True
            git.set_user(_BOT_NAME, _BOT_EMAIL)
            git.add_remote("origin", remote_url)
        else:
            # Ensure remote URL is correct
            git.add_remote("origin", remote_url)

        # Commit any uncommitted changes
        commit_msg = f"Agent OS iteration {iteration}"
        git.commit_all(commit_msg)  # may fail if nothing to commit — ok

        # Push main
        branch_result = git.push_upstream("main")
        if not branch_result.success:
            branch_result = git.push("main", force=True)
            if not branch_result.success:
                err = f"Push main failed: {branch_result.stderr}"
                self._emit("pr_retry_progress", {"step": "error", "message": err})
                _persist_error(err)
                return True

        # Ensure feature branch exists and push
        branch_result = git.checkout(feature_branch)
        if not branch_result.success:
            branch_result = git.create_and_checkout(feature_branch, "main")
            if not branch_result.success:
                err = f"Create feature branch failed: {branch_result.stderr}"
                self._emit("pr_retry_progress", {"step": "error", "message": err})
                _persist_error(err)
                return True

        branch_result = git.push_upstream(feature_branch)
        if not branch_result.success:
            branch_result = git.push(feature_branch, force=True)
            if not branch_result.success:
                err = f"Push feature branch failed: {branch_result.stderr}"
                self._emit("pr_retry_progress", {"step": "error", "message": err})
                _persist_error(err)
                return True

        self._emit("pr_retry_progress", {"step": "push", "message": "Code pushed successfully"})

        # Step 3: Create PR
        self._emit("pr_retry_progress", {"step": "create_pr", "message": "Creating pull request..."})
        pr_title = f"[Agent OS] Iteration {iteration} — implementation"
        pr_body = (
            "Automated pull request created by Agent OS.\n\n"
            f"**Iteration:** {iteration}\n"
        )
        pr_result = vcs.create_pr(
            title=pr_title,
            head=feature_branch,
            base="main",
            body=pr_body,
        )
        if pr_result.success and pr_result.data:
            pr_number = pr_result.data.get("number")
            self.state_mgr.update_metadata({
                "pr_number": pr_number,
                "pr_failed": False,
                "pr_error": "",
            })
            self._emit("pr_retry_progress", {"step": "create_pr", "message": f"Pull request #{pr_number} created successfully"})
            self._emit("pr_retry_success", {"pr_number": pr_number, "iteration": iteration})
            self.state_mgr.transition_to(PipelineStatus.CODE_REVIEW)
            self._resume_in_thread()
            return True
        else:
            err = pr_result.error or "Unknown error"
            # PR might already exist from a previous push — try to discover it
            err_lower = err.lower()
            if any(kw in err_lower for kw in ("already exists", "there is already", "pull request already", "422")):
                try:
                    existing = vcs.find_open_pr(feature_branch)
                    if existing is not None:
                        self.state_mgr.update_metadata({
                            "pr_number": existing,
                            "pr_failed": False,
                            "pr_error": "",
                        })
                        self._emit("pr_retry_progress", {"step": "create_pr", "message": f"Pull request #{existing} already exists — proceeding to review"})
                        self._emit("pr_retry_success", {"pr_number": existing, "iteration": iteration})
                        self.state_mgr.transition_to(PipelineStatus.CODE_REVIEW)
                        self._resume_in_thread()
                        return True
                except Exception:
                    pass
            err_full = f"PR creation failed: {err}"
            self._emit("pr_retry_progress", {"step": "error", "message": err_full})
            _persist_error(err_full)
            return True  # attempted but failed — 200 so frontend refreshes

    def retry_prompt_generator(self) -> bool:
        """Re-run prompt generation from the HITL_PROMPT_REVIEW gate.

        Callable when at HITL_PROMPT_REVIEW, whether or not a prior failure occurred.
        This covers both "retry after failure" and "regenerate prompt on demand".
        Clears any failure flag and resumes from PROMPT_GENERATION.
        """
        if self.state_mgr.current_status != PipelineStatus.HITL_PROMPT_REVIEW:
            logger.warning("retry_prompt_generator() called but not at HITL_PROMPT_REVIEW")
            return False
        is_ghr = getattr(self.config, "pipeline_mode", "") == PipelineMode.GITHUB_REVIEW
        next_status = (
            PipelineStatus.STORY_PROMPT_GENERATION if is_ghr else PipelineStatus.PROMPT_GENERATION
        )
        self.state_mgr.transition_to(
            next_status,
            metadata={"prompt_gen_failed": False, "prompt_gen_error": ""},
        )
        self._emit(EventType.STATE_CHANGED, {"retry": "prompt_generator"})
        self._resume_in_thread()
        return True

    def retry_code_generator(self, cli_tool: str = "", cli_model: str = "") -> bool:
        """Retry code generation after a failure.

        Only callable when at CODE_GEN_FAILED.
        Clears the failure flag and resumes from CODE_GENERATION.
        Optionally overrides the CLI tool and model for this retry.
        """
        if self.state_mgr.current_status != PipelineStatus.CODE_GEN_FAILED:
            logger.warning("retry_code_generator() called but not at CODE_GEN_FAILED")
            return False
        if cli_tool:
            self.config.codex.cli_routing["CODE_GENERATOR"] = cli_tool
            self.state_mgr.update_metadata({"selected_cli_tool": cli_tool})
            logger.info("retry_code_generator: cli_tool overridden to '%s'", cli_tool)
        if cli_model:
            self.config.codex.model_routing["CODE_GENERATOR"] = cli_model
            self.state_mgr.update_metadata({"selected_cli_model": cli_model})
            logger.info("retry_code_generator: cli_model overridden to '%s'", cli_model)
        is_ghr = getattr(self.config, "pipeline_mode", "") == PipelineMode.GITHUB_REVIEW
        next_status = PipelineStatus.STORY_CODE_GENERATION if is_ghr else PipelineStatus.CODE_GENERATION
        self.state_mgr.transition_to(
            next_status,
            metadata={"code_gen_failed": False, "code_gen_error": ""},
        )
        self._emit(EventType.STATE_CHANGED, {"retry": "code_generator"})
        self._resume_in_thread()
        return True

    def retry_code_reviewer(self) -> bool:
        """Retry code review.

        Callable whenever the pipeline is paused at HITL_REVIEW_DECISION —
        covers both LLM failures (code_review_failed=True) and the normal
        "needs_work" rejection path where the user wants to re-run the review
        (e.g. after changing the code-reviewer provider/model in Settings).
        """
        if self.state_mgr.current_status != PipelineStatus.HITL_REVIEW_DECISION:
            logger.warning("retry_code_reviewer() called but not at HITL_REVIEW_DECISION")
            return False
        # Determine the correct review status for the current pipeline mode.
        _is_github_review_mode = (self.config.pipeline_mode == PipelineMode.GITHUB_REVIEW)
        _review_status = PipelineStatus.STORY_CODE_REVIEW if _is_github_review_mode else PipelineStatus.CODE_REVIEW
        self.state_mgr.transition_to(
            _review_status,
            metadata={"code_review_failed": False, "code_review_error": ""},
        )
        self._emit(EventType.STATE_CHANGED, {"retry": "code_reviewer"})
        self._resume_in_thread()
        return True

    def reset(self) -> None:
        """Reset the pipeline to IDLE, discarding all in-progress state.

        Clears iteration history from the database so the Projects, Code
        Insights, and Git History pages reflect a clean slate for the next run.
        Also clears project name and root_path so a fresh folder is provisioned
        on the next run based on updated requirements.
        """
        self._stop_event.set()
        self._pause_event.set()
        self._code_gen_stop_requested.clear()
        with self._wrapper_lock:
            self._active_codex_wrapper = None
        # Wipe iteration rows + reset pipeline_state in one transaction
        self.db.clear_run_data()
        # Clear project name + root_path + repo_name so next run derives them fresh
        self.config.project.name = ""
        self.config.project.root_path = ""
        self.config.project.repo_name = ""
        # Re-initialize StateManager from the now-clean DB
        self.state_mgr.reset()
        logger.info("Pipeline reset to IDLE — iteration history cleared")
        self._emit("reset")

    def _provision_project_dir(self) -> str:
        """Create (if needed) and return a project folder under ~/Desktop.

        Delegates to ProjectProvisioner for the actual work.
        """
        from .provisioner import ProjectProvisioner
        return ProjectProvisioner(self.config).provision()

    def _activate_ado_work_items(self) -> None:
        """Transition ADO work items from New → Active. Delegates to ADOWorkItemManager."""
        from .ado_manager import ADOWorkItemManager
        ADOWorkItemManager(self.state_mgr, self.config).activate_work_items()

    def _close_ado_work_items(self, story_id: Optional[str] = None) -> None:
        """Transition ADO work items to Closed. Delegates to ADOWorkItemManager."""
        from .ado_manager import ADOWorkItemManager
        ADOWorkItemManager(self.state_mgr, self.config).close_work_items(story_id)

    def approve_gate(self, gate: Optional[str] = None) -> bool:
        """Generic gate approval — kept for backward compat with old pipeline routes."""
        status = self.state_mgr.current_status
        if gate:
            try:
                expected = PipelineStatus(gate)
                if status != expected:
                    return False
            except ValueError:
                return False
        if status == PipelineStatus.HITL_PROMPT_REVIEW:
            return self.approve_prompt()
        if status == PipelineStatus.HITL_REVIEW_DECISION:
            return self.approve_review()
        return False

    def _resume_in_thread(self) -> None:
        """Re-start the run loop in a daemon thread (called after HITL approval)."""
        self._stop_event.clear()
        self._pause_event.clear()
        # Guard: don't spawn a second thread if one is already running
        if self._loop_thread is not None and self._loop_thread.is_alive():
            logger.warning("_resume_in_thread: loop thread already running — skipping duplicate start")
            return
        self._loop_thread = threading.Thread(target=self._loop, daemon=True, name="orchestrator-loop")
        self._loop_thread.start()

    # ── Status helpers ────────────────────────────────────────────────────────

    @property
    def current_iteration(self) -> int:
        return self.state_mgr.state.current_iteration

    def get_iterations(self) -> list[dict[str, Any]]:
        """Return all iteration records from the DB for the API /iterations endpoint."""
        rows = self.db.conn.execute(
            """SELECT id, iteration_number, status, prompt_path, prompt_content,
                      review_json_path, review_json_content, token_usage,
                      cli_tool_used, ci_result, ci_output, started_at, completed_at
               FROM iterations ORDER BY iteration_number ASC"""
        ).fetchall()
        return [dict(row) for row in rows]

    def get_current_prompt(self) -> str:
        """Return content of the current prompt file, or empty string."""
        prompt_path = getattr(self.config.project, "prompt_file_path", "")
        if prompt_path:
            p = Path(prompt_path)
            if p.exists():
                return p.read_text(encoding="utf-8")
        # Fallback: last iteration's prompt_content
        row = self.db.conn.execute(
            "SELECT prompt_content FROM iterations ORDER BY iteration_number DESC LIMIT 1"
        ).fetchone()
        return row["prompt_content"] if row else ""

    def get_current_review(self) -> str:
        """Return content of the latest review JSON, or empty string."""
        row = self.db.conn.execute(
            "SELECT review_json_content FROM iterations ORDER BY iteration_number DESC LIMIT 1"
        ).fetchone()
        return row["review_json_content"] if row else ""

    def shutdown(self) -> None:
        """Cleanup — stop the loop and close the DB connection."""
        self._stop_event.set()
        self.db.close()
