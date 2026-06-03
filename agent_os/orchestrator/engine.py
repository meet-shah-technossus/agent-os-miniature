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
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from rich.console import Console

from ..config.schema import AgentOSConfig
from ..storage.database import Database
from ..storage.models import PipelineState, PipelineStatus
from .state import StateManager

logger = logging.getLogger(__name__)
console = Console()


class Orchestrator:
    """Autonomous SDLC pipeline orchestrator — POC linear loop."""

    def __init__(self, config: AgentOSConfig) -> None:
        self.config = config
        self.db = Database(config.storage.db_path)
        self.db.connect()
        self.state_mgr = StateManager(self.db)

        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        # Stop-code-generation support
        self._code_gen_stop_requested = threading.Event()
        self._active_codex_wrapper = None  # CodexWrapper instance during code gen steps
        self._loop_thread: Optional[threading.Thread] = None

        # WebSocket broadcast queue — populated by _emit(); drained by API layer
        self._ws_queue: Optional[asyncio.Queue] = None

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
                                   completed_at=datetime.utcnow().isoformat())
        elif new_status == PipelineStatus.PIPELINE_COMPLETE:
            self._upsert_iteration(iter_num, status="completed",
                                   completed_at=datetime.utcnow().isoformat())

    def _upsert_iteration(self, iteration_number: int, **kwargs: Any) -> None:
        """Create or update an iteration row in the iterations table.

        On first call for a given iteration_number an INSERT is performed.
        Subsequent calls only SET the provided columns.
        """
        try:
            count = self.db.conn.execute(
                "SELECT COUNT(*) FROM iterations WHERE iteration_number = ?",
                (iteration_number,),
            ).fetchone()[0]
            if count == 0:
                cols = ["iteration_number", "status", "started_at"] + list(kwargs.keys())
                vals: list[Any] = [
                    iteration_number,
                    kwargs.pop("status", "in_progress"),
                    kwargs.pop("started_at", datetime.utcnow().isoformat()),
                    *kwargs.values(),
                ]
                placeholders = ", ".join("?" for _ in vals)
                self.db.conn.execute(
                    f"INSERT INTO iterations ({', '.join(cols)}) VALUES ({placeholders})",
                    vals,
                )
            else:
                if not kwargs:
                    return
                set_clause = ", ".join(f"{k} = ?" for k in kwargs)
                self.db.conn.execute(
                    f"UPDATE iterations SET {set_clause} WHERE iteration_number = ?",
                    [*kwargs.values(), iteration_number],
                )
            self.db.conn.commit()
        except Exception:
            logger.debug("_upsert_iteration(%d) failed", iteration_number, exc_info=True)

    # ── WebSocket integration ──────────────────────────────────────────────────

    def set_ws_queue(self, queue: asyncio.Queue) -> None:
        """Inject the asyncio broadcast queue from the API layer."""
        self._ws_queue = queue

    def _emit(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Push a pipeline event onto the WebSocket broadcast queue (non-blocking)."""
        if self._ws_queue is None:
            return
        import datetime as _dt
        payload = {
            "channel": "pipeline",
            "sender": "orchestrator",
            "event": event_type,
            "timestamp": _dt.datetime.utcnow().isoformat() + "Z",
            "pipeline_status": self.state_mgr.current_status.value,
            "current_iteration": self.state_mgr.state.current_iteration,
            **(data or {}),
        }
        try:
            self._ws_queue.put_nowait(payload)
        except Exception:
            pass  # queue full or closed — not fatal

    def _emit_terminal(
        self,
        event_type: str,
        agent_post: str,
        session_id: str,
        **kwargs: Any,
    ) -> None:
        """Push a terminal_output channel event so the frontend terminal grid
        receives structured session_start / line / session_end events."""
        if self._ws_queue is None:
            return
        import datetime as _dt
        payload = {
            "channel": f"terminal:{agent_post.lower()}",
            "sender": agent_post.lower(),
            "timestamp": _dt.datetime.utcnow().isoformat() + "Z",
            "payload": {
                "event_type": event_type,
                "agent_post": agent_post,
                "session_id": session_id,
                **kwargs,
            },
        }
        try:
            self._ws_queue.put_nowait(payload)
        except Exception:
            pass

    # ── Main run loop ──────────────────────────────────────────────────────────

    def run(self) -> None:
        """Run the pipeline from current state to completion or HITL pause.

        Called in a background thread by the API /start route.
        """
        self._stop_event.clear()
        self._pause_event.clear()
        state = self.state_mgr.state
        logger.info("Pipeline run() called — current status: %s", state.pipeline_status.value)
        self._emit("run_started")
        self._loop()

    def _loop(self) -> None:
        """Execute the state machine until paused, complete, HITL, or error.

        Dispatches on ``config.pipeline_mode``:
        - ``"standard"``      → original linear loop (unchanged).
        - ``"github_review"`` → story-aware queue loop (Phase 2).
        """
        _STANDARD_DISPATCH = {
            PipelineStatus.IDLE:                  self._step_idle,
            PipelineStatus.LOADING_REQUIREMENTS:  self._step_load_requirements,
            PipelineStatus.PROMPT_GENERATION:     self._step_prompt_generation,
            PipelineStatus.CODE_GENERATION:       self._step_code_generation,
            PipelineStatus.CODE_REVIEW:           self._step_code_review,
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
        _is_ghr = (self.config.pipeline_mode == "github_review")
        _DISPATCH = _GHR_DISPATCH if _is_ghr else _STANDARD_DISPATCH

        while True:
            if self._stop_event.is_set():
                logger.info("Pipeline stopped (reset requested)")
                self._emit("stopped")
                break

            if self._pause_event.is_set():
                logger.info("Pipeline paused by user")
                self._emit("paused")
                break

            status = self.state_mgr.current_status

            if status == PipelineStatus.PIPELINE_COMPLETE:
                logger.info("Pipeline complete!")
                self._emit("pipeline_complete")
                # Auto-close ADO work items if they were ingested
                self._close_ado_work_items()
                break

            if status == PipelineStatus.FAILED:
                logger.warning("Pipeline in FAILED state — awaiting reset")
                self._emit("failed")
                break

            if status == PipelineStatus.CODE_GEN_FAILED:
                logger.warning("Pipeline paused at CODE_GEN_FAILED — awaiting retry or reset")
                break

            if status == PipelineStatus.CODE_GEN_STOPPED:
                logger.info("Pipeline stopped by user — awaiting rollback or continue decision")
                self._emit("code_gen_stopped", {
                    "working_dir": self.state_mgr.state.metadata.get("stopped_working_dir", ""),
                })
                break

            if self.state_mgr.is_hitl_gate():
                if self.config.orchestrator.auto_approve_hitl:
                    logger.info("Auto-approving HITL gate: %s", status.value)
                    self._auto_approve(status)
                    continue
                logger.info("Paused at HITL gate: %s", status.value)
                self._emit("hitl_gate", {"gate": status.value})
                break

            step = _DISPATCH.get(status)
            if step is None:
                logger.error("No step handler for state: %s", status.value)
                self.state_mgr.transition_to(PipelineStatus.FAILED)
                break

            try:
                step()
            except Exception as exc:
                logger.exception("Error in step %s: %s", status.value, exc)
                self.state_mgr.transition_to(PipelineStatus.FAILED)
                self._emit("error", {"message": str(exc)})
                break

    # ── Step handlers (standard mode) ─────────────────────────────────────────

    def _step_idle(self) -> None:
        """IDLE → LOADING_REQUIREMENTS."""
        self.state_mgr.transition_to(PipelineStatus.LOADING_REQUIREMENTS)
        self._emit("state_changed")

    def _step_load_requirements(self) -> None:
        """LOADING_REQUIREMENTS → PROMPT_GENERATION.

        Loads requirements from the configured source into the DB.
        """
        from ..requirements.parser import RequirementsParser
        req_path = self.config.requirements.path
        logger.info("Loading requirements from: %s", req_path)
        self._emit("loading_requirements", {"path": req_path})

        parser = RequirementsParser(db=self.db)
        stats = parser.load_and_store(req_path)
        logger.info("Requirements loaded: %s", stats)

        # Always re-derive project name and repo slug from requirements content
        _GENERIC_TITLES = {"imported requirements", "general", "imported features", ""}
        try:
            import re as _re
            import yaml as _yaml
            from collections import Counter as _Counter

            raw_text = Path(req_path).read_text(encoding="utf-8")
            if Path(req_path).suffix.lower() == ".md":
                _md_match = _re.search(r"```yaml\s*\n(.*?)\n```", raw_text, _re.DOTALL)
                raw = _yaml.safe_load(_md_match.group(1)) if _md_match else {}
            else:
                raw = _yaml.safe_load(raw_text)
            epics = (raw or {}).get("epics", [])
            title = ""

            if epics:
                epic_title = (epics[0].get("title", "") or "").strip()
                if epic_title.lower() not in _GENERIC_TITLES:
                    # Epic has a meaningful domain-specific title — use it
                    title = epic_title
                else:
                    # Epic title is a generic placeholder — derive from story titles
                    _STOP_WORDS = {
                        "a", "an", "the", "and", "or", "of", "to", "in", "for",
                        "is", "as", "so", "that", "can", "be", "with", "on", "by",
                        "i", "my", "we", "our", "from", "its", "it", "at", "all",
                        "view", "manage", "create", "update", "delete", "get",
                        "want", "should", "display", "show", "see", "add", "set",
                        "list", "allow", "able", "user", "system", "using", "use",
                    }
                    words: list[str] = []
                    for ep in epics:
                        for feat in ep.get("features", []):
                            for story in feat.get("stories", []):
                                st = (story.get("title", "") or "").strip()
                                if st:
                                    for w in _re.findall(r"[a-zA-Z]{3,}", st):
                                        wl = w.lower()
                                        if wl not in _STOP_WORDS:
                                            words.append(wl)

                    if words:
                        # Pick up to 3 most frequent domain words
                        top = [w for w, _ in _Counter(words).most_common(5)][:3]
                        title = " ".join(w.capitalize() for w in top)

            if not title:
                title = "Agent OS Project"

            slug = _re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
            self.config.project.name = title
            self.config.project.repo_name = slug
            logger.info(
                "Project name set from requirements: %s (repo=%s)", title, slug
            )
        except Exception:
            logger.debug("Could not extract project name from requirements", exc_info=True)

        state = self.state_mgr.state
        if self.config.pipeline_mode == "github_review":
            self.state_mgr.transition_to(
                PipelineStatus.ANALYSING_DEPENDENCIES,
                iteration=max(state.current_iteration, 1),
            )
        else:
            self.state_mgr.transition_to(
                PipelineStatus.PROMPT_GENERATION,
                iteration=max(state.current_iteration, 1),
            )
        self._emit("state_changed")

    def _step_prompt_generation(self) -> None:
        """PROMPT_GENERATION → HITL_PROMPT_REVIEW.

        Calls the real Prompt Generator (OpenAI API) to produce the iteration
        prompt, then pauses at the HITL review gate.
        """
        from ..prompt_generator.runner import PromptGeneratorRunner

        state = self.state_mgr.state
        iteration = state.current_iteration
        logger.info("Prompt generation — iteration %d", iteration)
        self._emit("prompt_generation_started", {"iteration": iteration})

        # Ensure an iteration row exists for this iteration number
        self._upsert_iteration(iteration)

        # For iteration 2+ we pass the review JSON from the previous iteration
        review_json: dict | None = None
        if iteration > 1:
            review_content = state.metadata.get("review_json_content")
            if review_content:
                import json as _json
                try:
                    review_json = _json.loads(review_content)
                except Exception:
                    review_json = {"raw": review_content}

        requirements_text: str | None = None
        if iteration == 1:
            req_path = getattr(self.config.requirements, "path", "")
            if req_path:
                req_file = Path(req_path)
                if req_file.exists():
                    requirements_text = req_file.read_text(encoding="utf-8")

        import uuid as _uuid
        _pg_session = f"pg-{iteration}-{_uuid.uuid4().hex[:8]}"
        _pg_cfg = getattr(self.config, 'prompt_generator', None)
        _pg_provider = getattr(_pg_cfg, 'provider', 'ollama')
        if _pg_provider == 'openai':
            model_pg = getattr(_pg_cfg, 'openai_model', None) or 'gpt-4.1-mini'
        else:
            model_pg = f"ollama/{getattr(_pg_cfg, 'ollama_model', None) or 'llama3.1:8b'}"
        self._emit_terminal("session_start", "PROMPT_GENERATOR", _pg_session,
                            iteration=iteration, module_id="", model=model_pg)

        def _on_stdout(line: str) -> None:
            self._emit("prompt_token", {"line": line})
            self._emit_terminal("token", "PROMPT_GENERATOR", _pg_session,
                                text=line, stream="stdout",
                                iteration=iteration, module_id="")

        runner = PromptGeneratorRunner(self.config)
        try:
            prompt_text = runner.run(
                iteration=iteration,
                requirements_text=requirements_text,
                review_json=review_json,
                on_stdout=_on_stdout,
            )
        except Exception as exc:
            logger.exception("Prompt generator failed: %s", exc)
            self._emit_terminal("session_end", "PROMPT_GENERATOR", _pg_session, exit_code=1)
            err_msg = str(exc)
            self.state_mgr.transition_to(
                PipelineStatus.HITL_PROMPT_REVIEW,
                metadata={"prompt_gen_failed": True, "prompt_gen_error": err_msg},
            )
            self._emit("prompt_gen_failed", {"iteration": iteration, "error": err_msg})
            self._emit("hitl_gate", {"gate": PipelineStatus.HITL_PROMPT_REVIEW.value})
            return

        # Persist prompt content to DB metadata
        self.state_mgr.update_metadata({"prompt_content": prompt_text})
        logger.info("Prompt generation complete — %d chars", len(prompt_text))
        self._emit_terminal("session_end", "PROMPT_GENERATOR", _pg_session, exit_code=0)
        self._emit("prompt_generation_complete", {"iteration": iteration, "char_count": len(prompt_text)})

        self.state_mgr.transition_to(PipelineStatus.HITL_PROMPT_REVIEW)
        self._emit("hitl_gate", {"gate": PipelineStatus.HITL_PROMPT_REVIEW.value})

    def _step_code_generation(self) -> None:
        """CODE_GENERATION → CODE_REVIEW.

        Invokes the Code Generator (Codex CLI) then performs iteration-aware
        git commit + push + PR operations via the configured VCS provider.
        """
        from ..code_generator.runner import CodeGeneratorRunner
        from ..vcs.factory import make_vcs_client

        state = self.state_mgr.state
        iteration = state.current_iteration
        logger.info("Code generation — iteration %d", iteration)
        self._emit("code_generation_started", {"iteration": iteration})

        # Resolve paths
        prompt_path = getattr(self.config.project, "prompt_file_path", "")
        if not prompt_path:
            prompt_path = "data/prompts/latest.md"

        # Provision the project working directory under ~/Desktop if not set
        working_dir = getattr(self.config.project, "root_path", "") or ""
        if not working_dir:
            working_dir = self._provision_project_dir()
        if not working_dir:
            working_dir = "."

        # Retrieve the selected CLI tool and previously-opened PR number.
        # When the user chooses a tool at the HITL_PROMPT_REVIEW gate, override
        # the config's cli_routing so the CodexWrapper uses it for this step.
        cli_tool = state.metadata.get("selected_cli_tool")
        if cli_tool:
            self.config.codex.cli_routing["CODE_GENERATOR"] = cli_tool
            logger.info("CLI tool overridden to '%s' for code generation step", cli_tool)
        cli_model = state.metadata.get("selected_cli_model")
        if cli_model:
            self.config.codex.model_routing["CODE_GENERATOR"] = cli_model
            logger.info("Model overridden to '%s' for code generation step", cli_model)

        pr_number: int | None = None
        pr_raw = state.metadata.get("pr_number")
        if pr_raw is not None:
            try:
                pr_number = int(pr_raw)
            except (TypeError, ValueError):
                pass

        import uuid as _uuid
        _cg_session = f"cg-{iteration}-{_uuid.uuid4().hex[:8]}"
        _cg_model = self.config.codex.model_routing.get("CODE_GENERATOR") or self.config.codex.default_model or ""
        _cg_tool = cli_tool or self.config.codex.cli_routing.get("CODE_GENERATOR", "codex")
        self._emit_terminal("session_start", "CODE_GENERATOR", _cg_session,
                            iteration=iteration, module_id="",
                            model=_cg_model, tool=_cg_tool)

        def _on_stdout(line: str) -> None:
            self._emit("codex_stdout", {"line": line})
            self._emit_terminal("line", "CODE_GENERATOR", _cg_session,
                                line=line, stream="stdout",
                                iteration=iteration, module_id="")

        def _on_stderr(line: str) -> None:
            self._emit("codex_stderr", {"line": line})
            self._emit_terminal("line", "CODE_GENERATOR", _cg_session,
                                line=line, stream="stderr",
                                iteration=iteration, module_id="")

        # Iteration 1: activate ADO work items (New → Active) via REST API directly,
        # so the status change is guaranteed regardless of MCP tool availability.
        if iteration == 1:
            self._activate_ado_work_items()

        runner = CodeGeneratorRunner(self.config, vcs_client=make_vcs_client(self.config))
        self._active_codex_wrapper = runner._codex
        self._code_gen_stop_requested.clear()
        try:
            gen_result = runner.run(
                prompt_path=prompt_path,
                working_dir=working_dir,
                iteration=iteration,
                pr_number=pr_number,
                on_stdout=_on_stdout,
                on_stderr=_on_stderr,
            )
        except Exception as exc:
            self._active_codex_wrapper = None
            logger.exception("Code generator raised: %s", exc)
            self._emit_terminal("session_end", "CODE_GENERATOR", _cg_session, exit_code=1)
            if self._code_gen_stop_requested.is_set():
                self.state_mgr.transition_to(
                    PipelineStatus.CODE_GEN_STOPPED,
                    metadata={"stopped_working_dir": str(working_dir)},
                )
                self._emit("code_gen_stopped", {"iteration": iteration})
            else:
                err_msg = str(exc)
                self.state_mgr.transition_to(
                    PipelineStatus.CODE_GEN_FAILED,
                    metadata={"code_gen_failed": True, "code_gen_error": err_msg},
                )
                self._emit("code_gen_failed", {"iteration": iteration, "error": err_msg})
            return
        self._active_codex_wrapper = None

        # If the user stopped code gen mid-flight, transition to CODE_GEN_STOPPED
        if self._code_gen_stop_requested.is_set():
            self._emit_terminal("session_end", "CODE_GENERATOR", _cg_session, exit_code=-2)
            self.state_mgr.transition_to(
                PipelineStatus.CODE_GEN_STOPPED,
                metadata={"stopped_working_dir": str(working_dir)},
            )
            self._emit("code_gen_stopped", {"iteration": iteration, "working_dir": str(working_dir)})
            return

        # Persist PR metadata for subsequent iterations
        metadata_update: dict[str, Any] = {
            "completion_status": gen_result.completion.status.value,
        }
        if cli_tool:
            metadata_update["cli_tool_used"] = cli_tool
        if gen_result.pr_number is not None:
            metadata_update["pr_number"] = gen_result.pr_number
            metadata_update["pr_url"] = gen_result.pr_url
        if gen_result.git_errors:
            metadata_update["git_errors"] = gen_result.git_errors
        self.state_mgr.update_metadata(metadata_update)

        # Persist cli_tool_used into the iterations table row for this iteration
        if cli_tool:
            try:
                self.db.conn.execute(
                    "UPDATE iterations SET cli_tool_used = ? WHERE iteration_number = ?",
                    (cli_tool, iteration),
                )
                self.db.conn.commit()
            except Exception:
                logger.debug("Could not update iterations.cli_tool_used", exc_info=True)

        # Persist prompt content and tool used to the iteration row
        self._upsert_iteration(
            iteration,
            prompt_content=self.state_mgr.state.metadata.get("prompt_content", ""),
            cli_tool_used=cli_tool or self.config.codex.cli_routing.get("CODE_GENERATOR", ""),
        )

        # Emit git errors visibly to the terminal
        if gen_result.git_errors:
            for git_err in gen_result.git_errors:
                self._emit_terminal("line", "CODE_GENERATOR", _cg_session,
                                    line=f"[git] {git_err}",
                                    stream="stderr", iteration=iteration, module_id="")

        _is_incomplete = gen_result.completion.status.value in ("failed", "partial")
        self._emit_terminal("session_end", "CODE_GENERATOR", _cg_session,
                            exit_code=0 if not _is_incomplete else 1)

        if _is_incomplete:
            err_msg = gen_result.completion.reason or "Code generation incomplete (no summary.md produced)"
            logger.warning("Code generation incomplete — transitioning to CODE_GEN_FAILED: %s", err_msg)
            self.state_mgr.transition_to(
                PipelineStatus.CODE_GEN_FAILED,
                metadata={"code_gen_failed": True, "code_gen_error": err_msg},
            )
            self._emit("code_gen_failed", {"iteration": iteration, "error": err_msg})
            return

        self._emit("code_generation_complete", {
            "iteration": iteration,
            "pr_number": gen_result.pr_number,
            "pr_url": gen_result.pr_url,
            "retried": gen_result.retried,
        })
        self.state_mgr.transition_to(PipelineStatus.CODE_REVIEW)
        self._emit("state_changed")

    def _step_code_review(self) -> None:
        """CODE_REVIEW → HITL_REVIEW_DECISION (or PIPELINE_COMPLETE if accepted).

        Invokes the Code Reviewer (OpenAI API via PR diff) and posts GitHub PR
        comments. Transitions to HITL_REVIEW_DECISION for user approval, or
        directly to PIPELINE_COMPLETE if the reviewer accepted and merged.
        """
        from ..code_reviewer.runner import CodeReviewerRunner
        from ..vcs.factory import make_vcs_client
        import json as _json

        state = self.state_mgr.state
        iteration = state.current_iteration
        logger.info("Code review — iteration %d", iteration)

        # Clear any stale failure flags left over from a previous attempt so
        # that the UI always reflects the *current* step's outcome.
        self.state_mgr.update_metadata({
            "code_review_failed": False,
            "code_review_error": "",
            "pr_failed": False,
            "pr_error": "",
        })

        self._emit("code_review_started", {"iteration": iteration})

        # Retrieve pr_number stored by _step_code_generation
        pr_number: Optional[int] = None
        pr_raw = state.metadata.get("pr_number")
        if pr_raw is not None:
            try:
                pr_number = int(pr_raw)
            except (TypeError, ValueError):
                pass

        feature_branch = self.config.project.feature_branch or "dev"

        # Build a VCS client scoped to the actual project repo (not the
        # default config.github.repo which may point to an unrelated repo).
        def _project_vcs():
            vcs = make_vcs_client(self.config)
            if vcs is None:
                return None
            repo = self.config.project.repo_name or ""
            if repo and hasattr(vcs, "for_repo") and repo != getattr(vcs, "_repo", ""):
                return vcs.for_repo(repo)
            return vcs

        # Fallback 1: discover open PR via VCS API
        if pr_number is None:
            logger.info("PR number not in metadata — attempting discovery via VCS API")
            try:
                vcs = _project_vcs()
                if vcs is not None:
                    _actor = getattr(vcs, "_owner", "unknown")
                    _actor_repo = getattr(vcs, "_repo", "")
                    logger.info(
                        "[actor: %s] Searching for open PR on branch '%s' in %s/%s",
                        _actor, feature_branch, _actor, _actor_repo,
                    )
                    discovered = vcs.find_open_pr(feature_branch)
                    if discovered is not None:
                        pr_number = discovered
                        self.state_mgr.update_metadata({"pr_number": pr_number})
                        logger.info(
                            "[actor: %s] Discovered PR #%d for branch '%s'",
                            _actor, pr_number, feature_branch,
                        )
                    else:
                        logger.info("[actor: %s] No open PR found for branch '%s'", _actor, feature_branch)
            except Exception:
                logger.debug("PR discovery failed", exc_info=True)

        # Fallback 2: create a new PR from the feature branch
        if pr_number is None:
            logger.info("PR discovery found nothing — attempting to create PR for review")
            try:
                vcs = _project_vcs()
                if vcs is not None:
                    _actor = getattr(vcs, "_owner", "unknown")
                    _actor_repo = getattr(vcs, "_repo", "")
                    logger.info(
                        "[actor: %s] Creating fallback PR: '%s' → main in %s/%s",
                        _actor, feature_branch, _actor, _actor_repo,
                    )
                    pr_title = f"[Agent OS] Iteration {iteration} — implementation"
                    pr_body = (
                        f"Automated pull request opened by Agent OS (code review fallback).\n\n"
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
                        self.state_mgr.update_metadata({"pr_number": pr_number})
                        logger.info(
                            "[actor: %s] Created PR #%d as review fallback in %s/%s",
                            _actor, pr_number, _actor, _actor_repo,
                        )
                    else:
                        logger.warning(
                            "[actor: %s] Fallback PR creation failed in %s/%s: %s",
                            _actor, _actor, _actor_repo, pr_result.error,
                        )
                        self.state_mgr.update_metadata({"pr_error": pr_result.error or "PR creation returned failure"})
            except Exception as exc:
                logger.debug("Fallback PR creation raised", exc_info=True)
                self.state_mgr.update_metadata({"pr_error": str(exc)})

        # No PR available — pause pipeline and show retry button in UI
        if pr_number is None:
            pr_err = state.metadata.get("pr_error", "No pull request could be created or discovered.")
            logger.warning(
                "No PR available for automated review — pausing for manual retry"
            )
            self.state_mgr.update_metadata({
                "pr_failed": True,
                "pr_error": pr_err,
            })
            self._emit("pr_creation_failed", {
                "iteration": iteration,
                "error": pr_err,
            })
            self.state_mgr.transition_to(PipelineStatus.HITL_REVIEW_DECISION)
            self._emit("hitl_gate", {"gate": PipelineStatus.HITL_REVIEW_DECISION.value})
            return

        import uuid as _uuid
        _cr_session = f"cr-{iteration}-{_uuid.uuid4().hex[:8]}"
        _cr_cfg = getattr(self.config, "code_reviewer", None)
        _cr_provider = (getattr(_cr_cfg, "provider", None) or "openai") if _cr_cfg else "openai"
        if _cr_provider == "ollama":
            _cr_model = (getattr(_cr_cfg, "ollama_model", "") or "") if _cr_cfg else ""
        else:
            _cr_model = (getattr(_cr_cfg, "model", "") or "") if _cr_cfg else ""
        _cr_model = _cr_model or self.config.codex.model_routing.get("CODE_REVIEWER") or self.config.codex.default_model or ""
        self._emit_terminal("session_start", "CODE_REVIEWER", _cr_session,
                            iteration=iteration, module_id="", model=_cr_model)

        def _on_stdout(line: str) -> None:
            self._emit("reviewer_stdout", {"line": line})
            self._emit_terminal("line", "CODE_REVIEWER", _cr_session,
                                line=line, stream="stdout",
                                iteration=iteration, module_id="")

        runner = CodeReviewerRunner(self.config, vcs_client=_project_vcs())
        try:
            run_result = runner.run(
                pr_number=pr_number,
                iteration=iteration,
                feature_branch=feature_branch,
                on_stdout=_on_stdout,
            )
        except Exception as exc:
            logger.exception("Code reviewer raised: %s", exc)
            self._emit_terminal("session_end", "CODE_REVIEWER", _cr_session, exit_code=1)
            err_msg = str(exc)
            self.state_mgr.transition_to(
                PipelineStatus.HITL_REVIEW_DECISION,
                metadata={"code_review_failed": True, "code_review_error": err_msg},
            )
            self._emit("code_review_failed", {"iteration": iteration, "error": err_msg})
            self._emit("hitl_gate", {"gate": PipelineStatus.HITL_REVIEW_DECISION.value})
            return

        review = run_result.review

        # Persist review data to metadata for prompt generator + HITL display
        self.state_mgr.update_metadata({
            "review_json_content": review.model_dump_json(),
            "review_json_path": run_result.review_json_path,
            "review_overall_status": review.overall_status,
            "review_overall_score": str(review.overall_score),
            "pr_merged": str(run_result.pr_merged),
            "branch_deleted": str(run_result.branch_deleted),
        })

        # Persist review data to the iteration row
        self._upsert_iteration(
            iteration,
            review_json_content=review.model_dump_json(),
            review_json_path=str(run_result.review_json_path),
        )

        self._emit_terminal("session_end", "CODE_REVIEWER", _cr_session, exit_code=0)
        self._emit("code_review_complete", {
            "iteration": iteration,
            "overall_status": review.overall_status,
            "overall_score": review.overall_score,
            "comments_posted": run_result.comments_posted,
            "pr_merged": run_result.pr_merged,
        })

        # Accepted + merged → skip HITL, complete pipeline
        if review.overall_status == "accepted" and run_result.pr_merged:
            logger.info("Review accepted and PR merged — transitioning to PIPELINE_COMPLETE")
            self.state_mgr.transition_to(PipelineStatus.PIPELINE_COMPLETE)
            self._emit("pipeline_complete", {"reason": "accepted_by_reviewer", "iteration": iteration})
            return

        self.state_mgr.transition_to(PipelineStatus.HITL_REVIEW_DECISION)
        self._emit("hitl_gate", {"gate": PipelineStatus.HITL_REVIEW_DECISION.value})

    # ── Step handlers (GitHub Review mode) ────────────────────────────────────

    def _fork_and_clone(self) -> bool:
        """Fork the source repo and clone it locally (once per pipeline run).

        Called by :meth:`_step_queue_ready` on the first story when
        ``config.project.root_path`` is not yet set.

        Returns:
            True on success (or graceful skip when config is incomplete).
            False on hard failure — the state is already transitioned to FAILED.
        """
        import re as _re
        import time as _time

        cfg = self.config
        source_url = getattr(cfg.github_review, "source_repo_url", "") or ""

        if not source_url:
            logger.info("[GHR] No source_repo_url — skipping fork+clone (will use existing root_path)")
            return True

        # Parse github.com/owner/repo from the URL
        m = _re.match(
            r"https?://github\.com/([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+?)(?:\.git)?/?$",
            source_url,
        )
        if not m:
            err = f"[GHR] Cannot parse source_repo_url: {source_url!r}"
            logger.error(err)
            self.state_mgr.transition_to(PipelineStatus.FAILED, metadata={"error": err})
            self._emit("error", {"message": err})
            return False

        source_owner, source_repo = m.groups()

        token = getattr(cfg.secrets, "github_token", "") or ""
        owner = getattr(cfg.github, "owner", "") or ""
        if not token or not owner:
            logger.warning("[GHR] GitHub token or owner not configured — skipping fork+clone")
            return True

        fork_name = (
            getattr(cfg.github_review, "fork_repo_name", "") or f"{source_repo}-agent-os"
        )

        from ..vcs.github_client import GitHubVCSClient
        from ..git_ops.manager import GitOpsManager

        vcs = GitHubVCSClient(token=token, owner=owner, repo=fork_name)

        # ── Fork (skipped when source_owner == owner — can't fork own repo) ──
        same_owner = source_owner.lower() == owner.lower()
        if same_owner:
            logger.info(
                "[GHR] source_owner == owner (%s) — skipping fork, cloning source repo directly",
                owner,
            )
            self._emit("fork_skipped", {"reason": "same_owner", "repo": f"{source_owner}/{source_repo}"})
        else:
            self._emit("fork_started", {"source": f"{source_owner}/{source_repo}",
                                        "fork": f"{owner}/{fork_name}"})
            logger.info("[GHR] Forking %s/%s → %s/%s", source_owner, source_repo, owner, fork_name)

            fork_result = vcs.fork_repo(source_owner, source_repo, name=fork_name)
            if not fork_result.success:
                err_lower = (fork_result.error or "").lower()
                already = any(kw in err_lower for kw in ("already exists", "422", "409"))
                if not already:
                    if "not found" in err_lower or fork_result.status_code == 404:
                        err = (
                            f"Fork failed: source repo '{source_owner}/{source_repo}' not found "
                            f"(404). Check that source_repo_url is correct and the GitHub token "
                            f"has 'repo' scope access."
                        )
                    else:
                        err = f"Fork failed: {fork_result.error}"
                    logger.error("[GHR] %s", err)
                    self.state_mgr.transition_to(PipelineStatus.FAILED, metadata={"error": err})
                    self._emit("error", {"message": err})
                    return False
                logger.info("[GHR] Fork already exists — continuing")

            # Wait for fork to become accessible
            self._emit("fork_waiting", {"fork": f"{owner}/{fork_name}"})
            if not vcs.wait_for_fork(owner, fork_name, max_wait_seconds=30):
                logger.warning("[GHR] Fork %s/%s not ready after 30s — proceeding anyway", owner, fork_name)

        # ── Clone ─────────────────────────────────────────────────────────────
        # When same_owner, clone the source repo directly (no fork was created).
        clone_repo_owner = source_owner if same_owner else owner
        clone_repo_name  = source_repo  if same_owner else fork_name
        clone_target = Path.home() / "Desktop" / clone_repo_name

        if clone_target.exists() and (clone_target / ".git").is_dir():
            logger.info("[GHR] Fork already cloned at %s — reusing", clone_target)
        else:
            clone_vcs = GitHubVCSClient(token=token, owner=clone_repo_owner, repo=clone_repo_name)
            clone_url = clone_vcs.get_remote_url(clone_repo_name)
            self._emit("clone_started", {
                "url": f"github.com/{clone_repo_owner}/{clone_repo_name}",
                "target": str(clone_target),
            })
            logger.info("[GHR] Cloning %s/%s to %s", clone_repo_owner, clone_repo_name, clone_target)
            clone_result, _ = GitOpsManager.clone_and_open(clone_url, clone_target)
            if not clone_result.success:
                err = f"Clone failed: {clone_result.stderr}"
                logger.error("[GHR] %s", err)
                self.state_mgr.transition_to(PipelineStatus.FAILED, metadata={"error": err})
                self._emit("error", {"message": err})
                return False

        # Set git identity in the cloned directory
        git = GitOpsManager(str(clone_target))
        git.set_user("Agent OS Bot", "agent-os@noreply.github.com")

        # Persist into config so all downstream steps (code gen, review) use it
        self.config.project.root_path = str(clone_target)
        self.config.project.repo_name = clone_repo_name
        self.state_mgr.update_metadata({
            "fork_name": clone_repo_name,
            "fork_owner": clone_repo_owner,
            "fork_clone_path": str(clone_target),
        })

        logger.info("[GHR] Fork+clone complete → %s", clone_target)
        self._emit("fork_clone_complete", {
            "repo": f"{clone_repo_owner}/{clone_repo_name}",
            "local_path": str(clone_target),
        })
        return True

    def _step_analyse_dependencies(self) -> None:
        """ANALYSING_DEPENDENCIES → QUEUE_READY.

        Reads all stories from the requirements DB, calls the LLM-powered
        dependency analyser, builds the ordered story queue, then transitions.
        """
        import asyncio
        from ..orchestrator.story_queue import StoryQueueManager

        logger.info("[GHR] Analysing story dependencies")
        self._emit("state_changed", {"step": "analyse_dependencies"})

        # Fetch stories (and their ACs) from the requirements DB
        conn = self.db.conn
        story_rows = conn.execute(
            "SELECT id, title, description FROM requirements WHERE type = 'story'"
        ).fetchall()

        raw_stories = []
        for row in story_rows:
            ac_rows = conn.execute(
                "SELECT title FROM requirements WHERE parent_id = ? AND type = 'acceptance_criteria'",
                (row["id"],),
            ).fetchall()
            raw_stories.append({
                "story_id": row["id"],
                "title": row["title"],
                "description": row["description"] or "",
                "acceptance_criteria": [ac["title"] for ac in ac_rows],
            })

        if not raw_stories:
            logger.warning("[GHR] No stories found in requirements DB — completing pipeline")
            self.state_mgr.transition_to(PipelineStatus.PIPELINE_COMPLETE)
            self._emit("pipeline_complete", {"reason": "no_stories"})
            return

        logger.info("[GHR] Found %d stories — building queue", len(raw_stories))
        self._emit("analyse_dependencies_started", {"story_count": len(raw_stories)})

        mgr = StoryQueueManager(self.db)
        items = asyncio.run(mgr.build_queue(
            raw_stories,
            api_key=getattr(self.config.secrets, "openai_api_key", "") or "",
            model=getattr(self.config, "openai_model", "gpt-4o-mini") or "gpt-4o-mini",
        ))

        self.state_mgr.update_story_context(stories_total=len(items), stories_completed=0)
        logger.info("[GHR] Queue built — %d stories in execution order", len(items))
        self._emit("queue_built", {"stories": [
            {"story_id": it.story_id, "title": it.title, "position": it.position,
             "depends_on": it.depends_on}
            for it in items
        ]})
        self.state_mgr.transition_to(PipelineStatus.QUEUE_READY)
        self._emit("state_changed")

    def _step_queue_ready(self) -> None:
        """QUEUE_READY → STORY_PROMPT_GENERATION (or PIPELINE_COMPLETE if done).

        On the first story: forks + clones the source repo (once).
        Dequeues the next ready story and sets it as the active story.
        """
        from ..orchestrator.story_queue import StoryQueueManager

        # Fork + clone once before the first story
        if not self.config.project.root_path:
            if not self._fork_and_clone():
                return  # _fork_and_clone transitioned to FAILED

        mgr = StoryQueueManager(self.db)
        next_story = mgr.dequeue()

        if next_story is None:
            # Queue exhausted (or all remaining stories have unresolved deps from failures)
            counts = mgr.counts()
            logger.info("[GHR] Queue exhausted — %s", counts)
            self.state_mgr.transition_to(PipelineStatus.PIPELINE_COMPLETE)
            self._emit("pipeline_complete", {"reason": "queue_exhausted", "counts": counts})
            self._close_ado_work_items()
            return

        logger.info("[GHR] Starting story: %s — %s", next_story.story_id, next_story.title)
        self.state_mgr.update_story_context(current_story_id=next_story.story_id)
        self._emit("story_started", {
            "story_id": next_story.story_id,
            "title": next_story.title,
            "position": next_story.position,
        })
        # Reset per-story iteration counter in state metadata
        self.state_mgr.update_metadata({"story_iteration": 1, "story_review_json": None})
        self.state_mgr.transition_to(PipelineStatus.STORY_PROMPT_GENERATION)
        self._emit("state_changed")

    def _step_story_prompt_generation(self) -> None:
        """STORY_PROMPT_GENERATION → STORY_CODE_GENERATION.

        Same as _step_prompt_generation but scoped to the current story's
        acceptance criteria and (on iteration 2+) the previous ReviewJSON.
        """
        import json as _json
        import uuid as _uuid
        from ..prompt_generator.runner import PromptGeneratorRunner
        from ..orchestrator.story_queue import StoryQueueManager

        state = self.state_mgr.state
        story_id = state.current_story_id
        story_iter = state.metadata.get("story_iteration", 1)

        logger.info("[GHR] Story prompt generation — story=%s iter=%d", story_id, story_iter)
        self._emit("prompt_generation_started", {"story_id": story_id, "story_iteration": story_iter})

        # Fetch story details from queue
        mgr = StoryQueueManager(self.db)
        item = mgr.get_item(story_id) if story_id else None
        if item is None:
            logger.error("[GHR] Could not find story %s in queue — failing", story_id)
            self.state_mgr.transition_to(PipelineStatus.FAILED)
            return

        # Build requirements_text for this story
        acs_md = "\n".join(f"- {ac}" for ac in item.acceptance_criteria) or "(no acceptance criteria)"
        requirements_text = (
            f"## Story: {item.title}\n\n"
            f"{item.description}\n\n"
            f"### Acceptance Criteria\n{acs_md}\n"
        )

        # For iteration 2+ pass the review JSON
        review_json: dict | None = None
        if story_iter > 1:
            review_raw = state.metadata.get("story_review_json")
            if review_raw:
                try:
                    review_json = _json.loads(review_raw) if isinstance(review_raw, str) else review_raw
                except Exception:
                    review_json = {"raw": str(review_raw)}

        _pg_session = f"pg-story-{story_id}-iter{story_iter}-{_uuid.uuid4().hex[:8]}"
        _pg_cfg = getattr(self.config, 'prompt_generator', None)
        _pg_provider = getattr(_pg_cfg, 'provider', 'ollama')
        if _pg_provider == 'openai':
            model_pg = getattr(_pg_cfg, 'openai_model', None) or 'gpt-4.1-mini'
        else:
            model_pg = f"ollama/{getattr(_pg_cfg, 'ollama_model', None) or 'llama3.1:8b'}"
        self._emit_terminal("session_start", "PROMPT_GENERATOR", _pg_session,
                            story_id=story_id, iteration=story_iter, model=model_pg)

        def _on_stdout(line: str) -> None:
            self._emit("prompt_token", {"line": line})
            self._emit_terminal("token", "PROMPT_GENERATOR", _pg_session,
                                text=line, stream="stdout",
                                story_id=story_id, iteration=story_iter)

        runner = PromptGeneratorRunner(self.config)
        try:
            prompt_text = runner.run(
                iteration=story_iter,
                requirements_text=requirements_text,
                review_json=review_json,
                on_stdout=_on_stdout,
                story_context={
                    "story_id": story_id or "",
                    "title": item.title,
                    "pr_number": state.metadata.get("story_pr_number"),
                    "is_fork_mode": True,
                },
            )
        except Exception as exc:
            logger.exception("[GHR] Story prompt generator failed: %s", exc)
            self._emit_terminal("session_end", "PROMPT_GENERATOR", _pg_session, exit_code=1)
            self.state_mgr.update_metadata({"story_prompt_error": str(exc)})
            self.state_mgr.transition_to(PipelineStatus.FAILED)
            self._emit("error", {"message": str(exc), "story_id": story_id})
            return

        self.state_mgr.update_metadata({"prompt_content": prompt_text, "story_prompt_error": ""})
        self._emit_terminal("session_end", "PROMPT_GENERATOR", _pg_session, exit_code=0)
        self._emit("prompt_generation_complete", {
            "story_id": story_id, "story_iteration": story_iter, "char_count": len(prompt_text),
        })
        # Pause at HITL gate so the user can review/edit the generated prompt
        # before code generation starts.
        self.state_mgr.transition_to(PipelineStatus.HITL_PROMPT_REVIEW)
        self._emit("hitl_gate", {"gate": PipelineStatus.HITL_PROMPT_REVIEW.value})

    def _step_story_code_generation(self) -> None:
        """STORY_CODE_GENERATION → STORY_CODE_REVIEW.

        Phase 2 stub — runs the existing CodeGeneratorRunner with a per-story
        branch name.  Phase 3 will replace this with a full fork-based workflow.
        """
        import uuid as _uuid
        from ..code_generator.runner import CodeGeneratorRunner
        from ..vcs.factory import make_vcs_client
        from ..orchestrator.story_queue import StoryQueueManager
        import re as _re

        state = self.state_mgr.state
        story_id = state.current_story_id
        story_iter = state.metadata.get("story_iteration", 1)

        logger.info("[GHR] Story code generation — story=%s iter=%d", story_id, story_iter)

        # Activate ADO work items (New → Active) via REST API on the first story iteration.
        if story_iter == 1:
            self._activate_ado_work_items()

        # Derive branch name from story id + title
        mgr = StoryQueueManager(self.db)
        item = mgr.get_item(story_id) if story_id else None

        if item and not item.branch_name:
            slug = _re.sub(r"[^a-z0-9]+", "-", item.title.lower()).strip("-")[:40]
            branch_name = f"story-{story_id}-{slug}".lower()
            mgr.update_branch(story_id, branch_name)
        else:
            branch_name = (item.branch_name if item else None) or f"story-{story_id}"

        # Store branch name in config so the code generator uses it
        self.config.project.feature_branch = branch_name
        # Remove any stale pr_number so code generator creates a fresh PR for this story
        if story_iter == 1:
            self.state_mgr.update_metadata({"pr_number": None, "pr_url": ""})

        prompt_path = getattr(self.config.project, "prompt_file_path", "") or "data/prompts/latest.md"
        working_dir = getattr(self.config.project, "root_path", "") or ""
        if not working_dir:
            working_dir = self._provision_project_dir()

        cli_tool = state.metadata.get("selected_cli_tool")
        if cli_tool:
            self.config.codex.cli_routing["CODE_GENERATOR"] = cli_tool
            logger.info("[GHR] CLI tool overridden to '%s' for story code generation", cli_tool)
        cli_model = state.metadata.get("selected_cli_model")
        if cli_model:
            self.config.codex.model_routing["CODE_GENERATOR"] = cli_model
            logger.info("[GHR] Model overridden to '%s' for story code generation", cli_model)

        pr_number: Optional[int] = None
        if story_iter > 1:
            pr_raw = state.metadata.get("pr_number")
            if pr_raw is not None:
                try:
                    pr_number = int(pr_raw)
                except (TypeError, ValueError):
                    pass

        _cg_session = f"cg-story-{story_id}-iter{story_iter}-{_uuid.uuid4().hex[:8]}"
        _cg_model = self.config.codex.model_routing.get("CODE_GENERATOR") or self.config.codex.default_model or ""
        _cg_tool = cli_tool or self.config.codex.cli_routing.get("CODE_GENERATOR", "codex")
        self._emit_terminal("session_start", "CODE_GENERATOR", _cg_session,
                            story_id=story_id, iteration=story_iter, model=_cg_model, tool=_cg_tool)
        self._emit("code_generation_started", {"story_id": story_id, "story_iteration": story_iter})

        def _on_stdout(line: str) -> None:
            self._emit("codex_stdout", {"line": line})
            self._emit_terminal("line", "CODE_GENERATOR", _cg_session,
                                line=line, stream="stdout", story_id=story_id)

        def _on_stderr(line: str) -> None:
            self._emit("codex_stderr", {"line": line})
            self._emit_terminal("line", "CODE_GENERATOR", _cg_session,
                                line=line, stream="stderr", story_id=story_id)

        runner = CodeGeneratorRunner(self.config, vcs_client=make_vcs_client(self.config))
        self._active_codex_wrapper = runner._codex
        self._code_gen_stop_requested.clear()
        try:
            gen_result = runner.run(
                prompt_path=prompt_path,
                working_dir=working_dir,
                iteration=story_iter,
                pr_number=pr_number,
                on_stdout=_on_stdout,
                on_stderr=_on_stderr,
                story_context={
                    "story_id": story_id or "",
                    "title": item.title if item else "",
                    "acceptance_criteria": item.acceptance_criteria if item else [],
                } if item else None,
            )
        except Exception as exc:
            self._active_codex_wrapper = None
            logger.exception("[GHR] Story code generator raised: %s", exc)
            self._emit_terminal("session_end", "CODE_GENERATOR", _cg_session, exit_code=1)
            if self._code_gen_stop_requested.is_set():
                self.state_mgr.transition_to(
                    PipelineStatus.CODE_GEN_STOPPED,
                    metadata={"stopped_working_dir": str(working_dir), "stopped_story_id": story_id or ""},
                )
                self._emit("code_gen_stopped", {"story_id": story_id})
            else:
                self.state_mgr.transition_to(
                    PipelineStatus.CODE_GEN_FAILED,
                    metadata={"code_gen_failed": True, "code_gen_error": str(exc)},
                )
                self._emit("code_gen_failed", {"story_id": story_id, "error": str(exc)})
            return
        self._active_codex_wrapper = None

        # If the user stopped code gen mid-flight, transition to CODE_GEN_STOPPED
        if self._code_gen_stop_requested.is_set():
            self._emit_terminal("session_end", "CODE_GENERATOR", _cg_session, exit_code=-2)
            self.state_mgr.transition_to(
                PipelineStatus.CODE_GEN_STOPPED,
                metadata={
                    "stopped_working_dir": str(working_dir),
                    "stopped_story_id": story_id or "",
                },
            )
            self._emit("code_gen_stopped", {"story_id": story_id, "working_dir": str(working_dir)})
            return

        meta_update: dict = {"completion_status": gen_result.completion.status.value}
        if gen_result.pr_number is not None:
            meta_update["pr_number"] = gen_result.pr_number
            meta_update["pr_url"] = gen_result.pr_url
        if gen_result.git_errors:
            meta_update["git_errors"] = gen_result.git_errors
        self.state_mgr.update_metadata(meta_update)

        # Emit git errors to the terminal so they are visible in the UI
        if gen_result.git_errors:
            for git_err in gen_result.git_errors:
                logger.warning("[GHR] Git error for story %s: %s", story_id, git_err)
                self._emit_terminal("line", "CODE_GENERATOR", _cg_session,
                                    line=f"[git] {git_err}",
                                    stream="stderr", story_id=story_id)

        _is_incomplete = gen_result.completion.status.value in ("failed", "partial")
        self._emit_terminal("session_end", "CODE_GENERATOR", _cg_session,
                            exit_code=0 if not _is_incomplete else 1)

        if _is_incomplete:
            err = gen_result.completion.reason or "Code generation did not complete successfully."
            logger.warning("[GHR] Story %s code gen incomplete: %s", story_id, err)
            self.state_mgr.transition_to(
                PipelineStatus.CODE_GEN_FAILED,
                metadata={"code_gen_failed": True, "code_gen_error": err},
            )
            self._emit("code_gen_failed", {"story_id": story_id, "error": err})
            return

        # If codex completed but git push / PR creation failed, abort early with
        # a clear error rather than flowing to STORY_CODE_REVIEW where the failure
        # is reported as "no PR found" with no context.
        if gen_result.pr_number is None and gen_result.git_errors:
            err_git = "; ".join(gen_result.git_errors)
            logger.warning("[GHR] Story %s git ops failed — no PR created: %s", story_id, err_git)
            self.state_mgr.transition_to(
                PipelineStatus.CODE_GEN_FAILED,
                metadata={"code_gen_failed": True, "code_gen_error": f"Git ops failed: {err_git}"},
            )
            self._emit("code_gen_failed", {"story_id": story_id, "error": err_git})
            return

        self._emit("code_generation_complete", {
            "story_id": story_id,
            "story_iteration": story_iter,
            "pr_number": gen_result.pr_number,
            "pr_url": gen_result.pr_url,
        })
        self.state_mgr.transition_to(PipelineStatus.STORY_CODE_REVIEW)
        self._emit("state_changed")

    def _step_story_code_review(self) -> None:
        """STORY_CODE_REVIEW → STORY_COMPLETE (accepted) or STORY_PROMPT_GENERATION (rejected).

        Phase 2 stub — calls the existing CodeReviewerRunner and passes the
        story's acceptance criteria as context.  Phase 4 will refine to full
        PR-based review with comment resolution.
        """
        import json as _json
        import uuid as _uuid
        from ..code_reviewer.runner import CodeReviewerRunner
        from ..vcs.factory import make_vcs_client
        from ..orchestrator.story_queue import StoryQueueManager

        state = self.state_mgr.state
        story_id = state.current_story_id
        story_iter = state.metadata.get("story_iteration", 1)
        max_story_iters = getattr(self.config.orchestrator, "max_story_iterations",
                                  self.config.orchestrator.max_iterations)

        logger.info("[GHR] Story code review — story=%s iter=%d", story_id, story_iter)
        self._emit("code_review_started", {"story_id": story_id, "story_iteration": story_iter})

        pr_number: Optional[int] = None
        pr_raw = state.metadata.get("pr_number")
        if pr_raw is not None:
            try:
                pr_number = int(pr_raw)
            except (TypeError, ValueError):
                pass

        feature_branch = self.config.project.feature_branch or f"story-{story_id}"

        def _project_vcs():
            vcs = make_vcs_client(self.config)
            if vcs is None:
                return None
            repo = self.config.project.repo_name or ""
            if repo and hasattr(vcs, "for_repo") and repo != getattr(vcs, "_repo", ""):
                return vcs.for_repo(repo)
            return vcs

        if pr_number is None:
            try:
                vcs = _project_vcs()
                if vcs:
                    pr_number = vcs.find_open_pr(feature_branch)
                    if pr_number:
                        self.state_mgr.update_metadata({"pr_number": pr_number})
            except Exception:
                logger.debug("[GHR] PR discovery failed", exc_info=True)

        if pr_number is None:
            err_no_pr = "No pull request found or created — code may not have been pushed to GitHub."
            logger.warning("[GHR] No PR found for story %s — pausing at CODE_GEN_FAILED", story_id)
            self.state_mgr.transition_to(
                PipelineStatus.CODE_GEN_FAILED,
                metadata={"code_gen_failed": True, "code_gen_error": err_no_pr},
            )
            self._emit("code_gen_failed", {"story_id": story_id, "reason": "no_pr", "error": err_no_pr})
            return

        _cr_session = f"cr-story-{story_id}-iter{story_iter}-{_uuid.uuid4().hex[:8]}"
        _cr_cfg_ghr = getattr(self.config, "code_reviewer", None)
        _cr_provider_ghr = (getattr(_cr_cfg_ghr, "provider", None) or "openai") if _cr_cfg_ghr else "openai"
        if _cr_provider_ghr == "ollama":
            _cr_model = (getattr(_cr_cfg_ghr, "ollama_model", "") or "") if _cr_cfg_ghr else ""
        else:
            _cr_model = (getattr(_cr_cfg_ghr, "model", "") or "") if _cr_cfg_ghr else ""
        _cr_model = _cr_model or self.config.codex.model_routing.get("CODE_REVIEWER") or self.config.codex.default_model or ""
        self._emit_terminal("session_start", "CODE_REVIEWER", _cr_session,
                            story_id=story_id, iteration=story_iter, model=_cr_model)

        def _on_stdout(line: str) -> None:
            self._emit("reviewer_stdout", {"line": line})
            self._emit_terminal("line", "CODE_REVIEWER", _cr_session,
                                line=line, stream="stdout", story_id=story_id)

        runner = CodeReviewerRunner(self.config, vcs_client=_project_vcs())
        from ..orchestrator.story_queue import StoryQueueManager as _StoryQueueManager
        _mgr = _StoryQueueManager(self.db)
        _item = _mgr.get_item(story_id) if story_id else None
        try:
            run_result = runner.run(
                pr_number=pr_number,
                iteration=story_iter,
                feature_branch=feature_branch,
                on_stdout=_on_stdout,
                story_context={
                    "story_id": story_id or "",
                    "title": (_item.title if _item else ""),
                    "acceptance_criteria": (_item.acceptance_criteria if _item else []),
                },
            )
        except Exception as exc:
            logger.exception("[GHR] Story code reviewer raised: %s", exc)
            self._emit_terminal("session_end", "CODE_REVIEWER", _cr_session, exit_code=1)
            err_msg = str(exc)
            self.state_mgr.transition_to(
                PipelineStatus.HITL_REVIEW_DECISION,
                metadata={"code_review_failed": True, "code_review_error": err_msg},
            )
            self._emit("code_review_failed", {"story_id": story_id, "error": err_msg})
            self._emit("hitl_gate", {"gate": PipelineStatus.HITL_REVIEW_DECISION.value})
            return

        review = run_result.review
        review_json_str = review.model_dump_json()
        self.state_mgr.update_metadata({
            "story_review_json": review_json_str,
            "review_json_content": review_json_str,   # also write canonical key for API/frontend
            "review_overall_status": review.overall_status,
            "pr_merged": str(run_result.pr_merged),
        })
        # Persist review JSON to the iterations table so history/GitHistory views can show it
        self._upsert_iteration(story_iter, review_json_content=review_json_str)

        # Update pr_url in queue item if the reviewer merged it
        if run_result.pr_merged:
            StoryQueueManager(self.db).mark_complete(
                story_id,
                pr_number=pr_number,
                pr_url=state.metadata.get("pr_url", ""),
            )

        self._emit_terminal("session_end", "CODE_REVIEWER", _cr_session, exit_code=0)
        self._emit("code_review_complete", {
            "story_id": story_id,
            "story_iteration": story_iter,
            "overall_status": review.overall_status,
            "overall_score": review.overall_score,
            "pr_merged": run_result.pr_merged,
        })

        if review.overall_status == "accepted":
            logger.info("[GHR] Story %s accepted (iter %d) — moving to STORY_COMPLETE", story_id, story_iter)
            self.state_mgr.update_story_context(
                stories_completed=state.stories_completed + 1
            )
            self.state_mgr.transition_to(PipelineStatus.STORY_COMPLETE)
            self._emit("story_completed", {"story_id": story_id, "story_iteration": story_iter})
        elif story_iter >= max_story_iters:
            logger.warning("[GHR] Story %s hit max iterations (%d) — marking failed", story_id, max_story_iters)
            StoryQueueManager(self.db).mark_failed(story_id, reason=f"Max iterations ({max_story_iters}) reached")
            self.state_mgr.update_story_context(
                stories_completed=state.stories_completed + 1
            )
            self.state_mgr.transition_to(PipelineStatus.STORY_COMPLETE)
            self._emit("story_failed", {"story_id": story_id, "reason": "max_iterations"})
        else:
            # Loop back: bump story iteration counter, then pause at HITL so
            # the user can inspect / edit the review JSON before prompt gen.
            next_iter = story_iter + 1
            logger.info("[GHR] Story %s rejected — pausing at review gate before iteration %d",
                        story_id, next_iter)
            self.state_mgr.update_metadata({"story_iteration": next_iter})
            StoryQueueManager(self.db).increment_iteration(story_id)
            if self.config.orchestrator.auto_approve_hitl:
                # Auto-approve: skip the HITL gate and go straight to prompt gen
                self.state_mgr.transition_to(PipelineStatus.STORY_PROMPT_GENERATION)
                self._emit("state_changed", {"story_id": story_id, "next_story_iteration": next_iter})
                self._resume_in_thread()
            else:
                self.state_mgr.transition_to(PipelineStatus.HITL_REVIEW_DECISION)
                self._emit("hitl_gate", {
                    "gate": PipelineStatus.HITL_REVIEW_DECISION.value,
                    "story_id": story_id,
                    "next_story_iteration": next_iter,
                    "review_overall_status": review.overall_status,
                })

    def _step_story_complete(self) -> None:
        """STORY_COMPLETE → QUEUE_READY (next story) or PIPELINE_COMPLETE (queue empty)."""
        from ..orchestrator.story_queue import StoryQueueManager

        state = self.state_mgr.state
        story_id = state.current_story_id
        mgr = StoryQueueManager(self.db)

        logger.info("[GHR] Story complete: %s — checking queue", story_id)

        # Close this story's ADO work item now that it's done (Active → Closed)
        self._close_ado_work_items(story_id=story_id)

        if mgr.is_complete():
            counts = mgr.counts()
            logger.info("[GHR] All stories processed — %s", counts)
            self.state_mgr.transition_to(PipelineStatus.PIPELINE_COMPLETE)
            self._emit("pipeline_complete", {
                "reason": "all_stories_processed",
                "stories_completed": state.stories_completed,
                "stories_total": state.stories_total,
                "counts": counts,
            })
        else:
            self.state_mgr.transition_to(PipelineStatus.QUEUE_READY)
            self._emit("state_changed", {"next": "queue_ready"})

    # ── HITL gate approvals ───────────────────────────────────────────────────

    def _auto_approve(self, status: PipelineStatus) -> None:
        """Auto-approve HITL gate (used when auto_approve_hitl=True)."""
        is_ghr = getattr(self.config, "pipeline_mode", "") == "github_review"
        if status == PipelineStatus.HITL_PROMPT_REVIEW:
            next_status = PipelineStatus.STORY_CODE_GENERATION if is_ghr else PipelineStatus.CODE_GENERATION
            self.state_mgr.transition_to(next_status)
        elif status == PipelineStatus.HITL_REVIEW_DECISION:
            if is_ghr:
                self.state_mgr.transition_to(PipelineStatus.STORY_PROMPT_GENERATION)
            else:
                self.state_mgr.transition_to(PipelineStatus.PIPELINE_COMPLETE)
        self._emit("state_changed")

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

        is_ghr = getattr(self.config, "pipeline_mode", "") == "github_review"
        next_status = PipelineStatus.STORY_CODE_GENERATION if is_ghr else PipelineStatus.CODE_GENERATION
        self.state_mgr.transition_to(next_status)
        self._emit("state_changed", {"approved": "prompt"})

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
            is_ghr = getattr(self.config, "pipeline_mode", "") == "github_review"
            if is_ghr:
                self.state_mgr.transition_to(PipelineStatus.STORY_COMPLETE)
                self._emit("story_completed", {"story_id": state.current_story_id, "reason": "user_approved"})
                self._resume_in_thread()
            else:
                self.state_mgr.transition_to(PipelineStatus.PIPELINE_COMPLETE)
                self._emit("pipeline_complete", {"reason": "user_approved_accepted_review"})
            return True

        is_ghr = getattr(self.config, "pipeline_mode", "") == "github_review"
        if is_ghr:
            # GHR mode: loop back to story prompt generation for another fix iteration
            self.state_mgr.transition_to(PipelineStatus.STORY_PROMPT_GENERATION)
            self._emit("state_changed", {
                "approved": "review",
                "next": "story_prompt_generation",
                "story_id": state.current_story_id,
            })
            self._resume_in_thread()
        else:
            max_iter = self.config.orchestrator.max_iterations
            if state.current_iteration >= max_iter:
                self.state_mgr.transition_to(PipelineStatus.PIPELINE_COMPLETE)
                self._emit("pipeline_complete", {"reason": "max_iterations_reached"})
            else:
                self.state_mgr.transition_to(
                    PipelineStatus.PROMPT_GENERATION,
                    iteration=state.current_iteration + 1,
                )
                self._emit("state_changed", {"approved": "review", "next_iteration": state.current_iteration + 1})
                self._resume_in_thread()

        return True

    def move_to_next_story(self) -> bool:
        """Force-advance to the next story: merge current PR, delete branch, then resume.

        Intended to be triggered by the frontend "Move to Next Story" button.
        Only valid when the pipeline is paused at ``HITL_REVIEW_DECISION``
        (i.e. after the code reviewer has completed and produced a review JSON).

        Steps performed:
          1. Merge the PR for the current story via the GitHub VCS client.
          2. Delete the feature branch.
          3. Mark the story as complete in the queue.
          4. Transition to ``STORY_COMPLETE``.
          5. Resume the pipeline loop (``_step_story_complete`` picks the next story
             or transitions to ``PIPELINE_COMPLETE`` if the queue is exhausted).

        Returns True if the action was triggered, False if not in the right state.
        """
        from ..vcs.factory import make_vcs_client
        from ..orchestrator.story_queue import StoryQueueManager

        if self.state_mgr.current_status != PipelineStatus.HITL_REVIEW_DECISION:
            logger.warning("move_to_next_story() called but pipeline is not at HITL_REVIEW_DECISION")
            return False

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

        self.state_mgr.transition_to(PipelineStatus.STORY_COMPLETE)
        self._emit("story_completed", {
            "story_id": story_id,
            "reason": "move_to_next_story",
            "pr_merged": merged,
            "branch_deleted": branch_deleted,
        })
        self._resume_in_thread()
        return True

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
        self._emit("hitl_gate", {
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
            self._emit("hitl_gate", {
                "gate": PipelineStatus.HITL_PROMPT_REVIEW.value,
                "reason": "stop_continue_no_changes",
                "message": "No changes were written — rolled back to prompt review.",
            })
            return True

        is_ghr = (self.config.pipeline_mode == "github_review")
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
        self._emit("state_changed", {
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
        r = git.push_upstream("main")
        if not r.success:
            r = git.push("main", force=True)
            if not r.success:
                err = f"Push main failed: {r.stderr}"
                self._emit("pr_retry_progress", {"step": "error", "message": err})
                _persist_error(err)
                return True

        # Ensure feature branch exists and push
        r = git.checkout(feature_branch)
        if not r.success:
            r = git.create_and_checkout(feature_branch, "main")
            if not r.success:
                err = f"Create feature branch failed: {r.stderr}"
                self._emit("pr_retry_progress", {"step": "error", "message": err})
                _persist_error(err)
                return True

        r = git.push_upstream(feature_branch)
        if not r.success:
            r = git.push(feature_branch, force=True)
            if not r.success:
                err = f"Push feature branch failed: {r.stderr}"
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
        """Retry prompt generation after a failure.

        Only callable when at HITL_PROMPT_REVIEW with prompt_gen_failed metadata.
        Clears the failure flag and resumes from PROMPT_GENERATION.
        """
        if self.state_mgr.current_status != PipelineStatus.HITL_PROMPT_REVIEW:
            logger.warning("retry_prompt_generator() called but not at HITL_PROMPT_REVIEW")
            return False
        if not self.state_mgr.state.metadata.get("prompt_gen_failed"):
            logger.warning("retry_prompt_generator() called but prompt_gen_failed not set")
            return False
        self.state_mgr.transition_to(
            PipelineStatus.PROMPT_GENERATION,
            metadata={"prompt_gen_failed": False, "prompt_gen_error": ""},
        )
        self._emit("state_changed", {"retry": "prompt_generator"})
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
        is_ghr = getattr(self.config, "pipeline_mode", "") == "github_review"
        next_status = PipelineStatus.STORY_CODE_GENERATION if is_ghr else PipelineStatus.CODE_GENERATION
        self.state_mgr.transition_to(
            next_status,
            metadata={"code_gen_failed": False, "code_gen_error": ""},
        )
        self._emit("state_changed", {"retry": "code_generator"})
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
        _is_ghr = (self.config.pipeline_mode == "github_review")
        _review_status = PipelineStatus.STORY_CODE_REVIEW if _is_ghr else PipelineStatus.CODE_REVIEW
        self.state_mgr.transition_to(
            _review_status,
            metadata={"code_review_failed": False, "code_review_error": ""},
        )
        self._emit("state_changed", {"retry": "code_reviewer"})
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

        The folder name is derived from ``config.project.name`` when set, or
        falls back to the first epic title from the requirements file, or
        finally to ``agent-os-project``.  Collision-safe: appends ``-2``,
        ``-3``, … if the preferred name is already taken.

        The resolved path is stored back in ``config.project.root_path`` so
        subsequent iterations reuse the same folder.
        """
        import re

        # Determine a slug for the folder name
        raw_name = (self.config.project.name or "").strip()
        if not raw_name:
            # Try to extract from requirements file
            try:
                import re as _re
                import yaml as _yaml
                req_path = getattr(self.config.requirements, "path", "")
                if req_path:
                    req_file = Path(req_path)
                    text = req_file.read_text(encoding="utf-8")
                    if req_file.suffix.lower() == ".md":
                        match = _re.search(r"```yaml\s*\n(.*?)\n```", text, _re.DOTALL)
                        raw = _yaml.safe_load(match.group(1)) if match else {}
                    else:
                        raw = _yaml.safe_load(text)
                    epics = (raw or {}).get("epics", [])
                    if epics:
                        raw_name = epics[0].get("title", "").strip()
            except Exception:
                pass
        if not raw_name:
            raw_name = "agent-os-project"

        # Sanitise to a filesystem-safe slug
        slug = re.sub(r"[^a-zA-Z0-9_\-]", "-", raw_name).strip("-")
        slug = re.sub(r"-{2,}", "-", slug)[:60] or "agent-os-project"

        desktop = Path.home() / "Desktop"
        desktop.mkdir(parents=True, exist_ok=True)

        # Collision-safe: find an unused name
        candidate = desktop / slug
        counter = 2
        while candidate.exists():
            candidate = desktop / f"{slug}-{counter}"
            counter += 1

        candidate.mkdir(parents=True, exist_ok=True)
        # Ensure owner has full read/write/execute on the directory so Codex
        # (and any spawned process) can create files inside it.
        import stat as _stat
        candidate.chmod(
            _stat.S_IRWXU | _stat.S_IRGRP | _stat.S_IXGRP | _stat.S_IROTH | _stat.S_IXOTH
        )
        logger.info("Project directory provisioned: %s", candidate)

        # Persist so subsequent steps (code review, iteration 2+, …) reuse it
        self.config.project.root_path = str(candidate)
        if not self.config.project.name:
            self.config.project.name = slug
        return str(candidate)

    def _activate_ado_work_items(self) -> None:
        """Transition ADO work items from New → Active when code generation starts (iteration 1 only).

        In GHR mode the current story's ID is the ADO work item ID, so only that
        item is activated.  In standard mode all imported work items are activated.
        Credentials fall back from state metadata to config.requirements.
        """
        meta = self.state_mgr.state.metadata
        # Credential fallback: metadata (set via ADO import API) → config.requirements
        ado_org = meta.get("ado_org", "") or getattr(self.config.requirements, "ado_org", "")
        ado_token = meta.get("ado_token", "") or getattr(self.config.requirements, "ado_token", "")
        if not ado_org or not ado_token:
            logger.debug("[ADO] No credentials — skipping New→Active transition")
            return
        # In GHR mode the current story_id IS the ADO work item ID
        story_id = self.state_mgr.state.current_story_id
        if story_id and str(story_id).isdigit():
            work_item_ids: list[int] = [int(story_id)]
        else:
            work_item_ids = meta.get("ado_work_item_ids", [])
        if not work_item_ids:
            logger.debug("[ADO] No work item IDs — skipping New→Active transition")
            return
        try:
            import base64
            import httpx
            from urllib.parse import quote

            token_b64 = base64.b64encode(f":{ado_token}".encode()).decode()
            headers = {
                "Authorization": f"Basic {token_b64}",
                "Content-Type": "application/json-patch+json",
            }
            org_enc = quote(ado_org, safe="")
            patch_body = [{"op": "replace", "path": "/fields/System.State", "value": "Active"}]

            with httpx.Client(headers=headers, timeout=15, follow_redirects=False) as client:
                for wi_id in work_item_ids:
                    try:
                        resp = client.patch(
                            f"https://dev.azure.com/{org_enc}/_apis/wit/workitems/{wi_id}?api-version=7.1",
                            json=patch_body,
                        )
                        logger.debug("[ADO] Activated work item %s → HTTP %s", wi_id, resp.status_code)
                    except Exception:
                        logger.debug("Failed to activate ADO work item %s", wi_id, exc_info=True)

            logger.info("[ADO] Activated %d work item(s) to Active: %s", len(work_item_ids), work_item_ids)
        except Exception:
            logger.warning("Failed to activate ADO work items", exc_info=True)

    def _close_ado_work_items(self, story_id: Optional[str] = None) -> None:
        """Transition ADO work items to Closed.

        When *story_id* is given (GHR per-story completion), only that item is
        closed.  Without *story_id* all items from state metadata are closed
        (used at final PIPELINE_COMPLETE as a safety net).
        Credentials fall back from state metadata to config.requirements.
        """
        meta = self.state_mgr.state.metadata
        # Credential fallback: metadata → config.requirements
        ado_org = meta.get("ado_org", "") or getattr(self.config.requirements, "ado_org", "")
        ado_token = meta.get("ado_token", "") or getattr(self.config.requirements, "ado_token", "")
        if not ado_org or not ado_token:
            logger.debug("[ADO] No credentials — skipping Active→Closed transition")
            return
        if story_id and str(story_id).isdigit():
            work_item_ids: list[int] = [int(story_id)]
        else:
            work_item_ids = meta.get("ado_work_item_ids", [])
        if not work_item_ids:
            logger.debug("[ADO] No work item IDs — skipping Active→Closed transition")
            return
        try:
            import base64
            import httpx
            from urllib.parse import quote

            token_b64 = base64.b64encode(f":{ado_token}".encode()).decode()
            headers = {
                "Authorization": f"Basic {token_b64}",
                "Content-Type": "application/json-patch+json",
            }
            org_enc = quote(ado_org, safe="")
            patch_body = [{"op": "replace", "path": "/fields/System.State", "value": "Closed"}]

            with httpx.Client(headers=headers, timeout=15, follow_redirects=False) as client:
                for wi_id in work_item_ids:
                    try:
                        resp = client.patch(
                            f"https://dev.azure.com/{org_enc}/_apis/wit/workitems/{wi_id}?api-version=7.1",
                            json=patch_body,
                        )
                        logger.debug("[ADO] Closed work item %s → HTTP %s", wi_id, resp.status_code)
                    except Exception:
                        logger.debug("Failed to close ADO work item %s", wi_id, exc_info=True)

            logger.info("[ADO] Closed %d work item(s): %s", len(work_item_ids), work_item_ids)
        except Exception:
            logger.warning("Failed to close ADO work items", exc_info=True)

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
