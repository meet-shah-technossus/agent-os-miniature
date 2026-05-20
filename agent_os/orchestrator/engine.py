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
        model_pg = self.config.codex.model_routing.get("PROMPT_GENERATOR") or self.config.codex.default_model or ""
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

        # On the first iteration, inject an ADO work-item activation instruction
        # into the prompt file so the code-generator CLI can use its azure-devops
        # MCP connection to update work item states (New → Active) as its first action.
        if iteration == 1:
            meta = self.state_mgr.state.metadata
            work_item_ids = meta.get("ado_work_item_ids", [])
            ado_org = meta.get("ado_org", "")
            ado_project = meta.get("ado_project", "")
            if work_item_ids and ado_org:
                try:
                    prompt_file = Path(prompt_path)
                    if prompt_file.exists():
                        original = prompt_file.read_text(encoding="utf-8")
                        ids_str = ", ".join(str(i) for i in work_item_ids)
                        preamble = (
                            f"## Pre-task: Activate Azure DevOps Work Items\n\n"
                            f"Before starting the main implementation, use the **azure-devops MCP tool** "
                            f"to update the following work items to **Active** status:\n\n"
                            f"- Work Item IDs: {ids_str}\n"
                            f"- Organisation: {ado_org}\n"
                            f"- Project: {ado_project}\n\n"
                            f"Use the `update_work_item` tool (or equivalent) from the azure-devops MCP "
                            f"server to set `System.State` = `Active` for each work item ID listed above.\n\n"
                            f"---\n\n"
                        )
                        prompt_file.write_text(preamble + original, encoding="utf-8")
                        logger.info(
                            "Injected ADO work item activation preamble into prompt for %d items",
                            len(work_item_ids),
                        )
                except Exception:
                    logger.warning("Failed to inject ADO preamble into prompt", exc_info=True)

        runner = CodeGeneratorRunner(self.config, vcs_client=make_vcs_client(self.config))
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
            logger.exception("Code generator raised: %s", exc)
            self._emit_terminal("session_end", "CODE_GENERATOR", _cg_session, exit_code=1)
            err_msg = str(exc)
            self.state_mgr.transition_to(
                PipelineStatus.CODE_GEN_FAILED,
                metadata={"code_gen_failed": True, "code_gen_error": err_msg},
            )
            self._emit("code_gen_failed", {"iteration": iteration, "error": err_msg})
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

        self._emit_terminal("session_end", "CODE_GENERATOR", _cg_session,
                            exit_code=0 if gen_result.completion.status.value != "failed" else 1)

        if gen_result.completion.status.value == "failed":
            err_msg = gen_result.completion.reason or "Code generation failed (timeout or exit)"
            logger.warning("Code generation failed — transitioning to CODE_GEN_FAILED: %s", err_msg)
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
        _cr_model = self.config.codex.model_routing.get("CODE_REVIEWER") or self.config.codex.default_model or ""
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
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        items = loop.run_until_complete(mgr.build_queue(
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
        model_pg = self.config.codex.model_routing.get("PROMPT_GENERATOR") or self.config.codex.default_model or ""
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
        self._emit_terminal("session_start", "CODE_GENERATOR", _cg_session,
                            story_id=story_id, iteration=story_iter, model=_cg_model)
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
            logger.exception("[GHR] Story code generator raised: %s", exc)
            self._emit_terminal("session_end", "CODE_GENERATOR", _cg_session, exit_code=1)
            self.state_mgr.transition_to(
                PipelineStatus.CODE_GEN_FAILED,
                metadata={"code_gen_failed": True, "code_gen_error": str(exc)},
            )
            self._emit("code_gen_failed", {"story_id": story_id, "error": str(exc)})
            return

        meta_update: dict = {"completion_status": gen_result.completion.status.value}
        if gen_result.pr_number is not None:
            meta_update["pr_number"] = gen_result.pr_number
            meta_update["pr_url"] = gen_result.pr_url
        self.state_mgr.update_metadata(meta_update)

        self._emit_terminal("session_end", "CODE_GENERATOR", _cg_session,
                            exit_code=0 if gen_result.completion.status.value != "failed" else 1)

        if gen_result.completion.status.value == "failed":
            err = gen_result.completion.reason or "Code generation failed"
            self.state_mgr.transition_to(
                PipelineStatus.CODE_GEN_FAILED,
                metadata={"code_gen_failed": True, "code_gen_error": err},
            )
            self._emit("code_gen_failed", {"story_id": story_id, "error": err})
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
            logger.warning("[GHR] No PR found for story %s — marking story failed", story_id)
            mgr = StoryQueueManager(self.db)
            mgr.mark_failed(story_id, reason="No pull request found or created")
            self.state_mgr.update_story_context(
                stories_completed=state.stories_completed + 1
            )
            self.state_mgr.transition_to(PipelineStatus.STORY_COMPLETE)
            self._emit("story_failed", {"story_id": story_id, "reason": "no_pr"})
            return

        _cr_session = f"cr-story-{story_id}-iter{story_iter}-{_uuid.uuid4().hex[:8]}"
        _cr_model = self.config.codex.model_routing.get("CODE_REVIEWER") or self.config.codex.default_model or ""
        self._emit_terminal("session_start", "CODE_REVIEWER", _cr_session,
                            story_id=story_id, iteration=story_iter, model=_cr_model)

        def _on_stdout(line: str) -> None:
            self._emit("reviewer_stdout", {"line": line})
            self._emit_terminal("line", "CODE_REVIEWER", _cr_session,
                                line=line, stream="stdout", story_id=story_id)

        runner = CodeReviewerRunner(self.config, vcs_client=_project_vcs())
        try:
            run_result = runner.run(
                pr_number=pr_number,
                iteration=story_iter,
                feature_branch=feature_branch,
                on_stdout=_on_stdout,
                story_context={
                    "story_id": story_id or "",
                    "title": (mgr.get_item(story_id).title if story_id and mgr.get_item(story_id) else ""),
                    "acceptance_criteria": (mgr.get_item(story_id).acceptance_criteria
                                            if story_id and mgr.get_item(story_id) else []),
                },
            )
        except Exception as exc:
            logger.exception("[GHR] Story code reviewer raised: %s", exc)
            self._emit_terminal("session_end", "CODE_REVIEWER", _cr_session, exit_code=1)
            self.state_mgr.update_metadata({"code_review_error": str(exc)})
            self.state_mgr.transition_to(PipelineStatus.FAILED)
            self._emit("error", {"message": str(exc), "story_id": story_id})
            return

        review = run_result.review
        self.state_mgr.update_metadata({
            "story_review_json": review.model_dump_json(),
            "review_overall_status": review.overall_status,
            "pr_merged": str(run_result.pr_merged),
        })

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
            # Loop back: bump story iteration, re-run prompt generation
            next_iter = story_iter + 1
            logger.info("[GHR] Story %s rejected — starting iteration %d", story_id, next_iter)
            self.state_mgr.update_metadata({"story_iteration": next_iter})
            StoryQueueManager(self.db).increment_iteration(story_id)
            self.state_mgr.transition_to(PipelineStatus.STORY_PROMPT_GENERATION)
            self._emit("state_changed", {"story_id": story_id, "next_story_iteration": next_iter})

    def _step_story_complete(self) -> None:
        """STORY_COMPLETE → QUEUE_READY (next story) or PIPELINE_COMPLETE (queue empty)."""
        from ..orchestrator.story_queue import StoryQueueManager

        state = self.state_mgr.state
        story_id = state.current_story_id
        mgr = StoryQueueManager(self.db)

        logger.info("[GHR] Story complete: %s — checking queue", story_id)

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
            self._close_ado_work_items()
        else:
            self.state_mgr.transition_to(PipelineStatus.QUEUE_READY)
            self._emit("state_changed", {"next": "queue_ready"})

    # ── HITL gate approvals ───────────────────────────────────────────────────

    def _auto_approve(self, status: PipelineStatus) -> None:
        """Auto-approve HITL gate (used when auto_approve_hitl=True)."""
        if status == PipelineStatus.HITL_PROMPT_REVIEW:
            is_ghr = getattr(self.config, "pipeline_mode", "") == "github_review"
            next_status = PipelineStatus.STORY_CODE_GENERATION if is_ghr else PipelineStatus.CODE_GENERATION
            self.state_mgr.transition_to(next_status)
        elif status == PipelineStatus.HITL_REVIEW_DECISION:
            self.state_mgr.transition_to(PipelineStatus.PIPELINE_COMPLETE)
        self._emit("state_changed")

    def approve_prompt(
        self,
        prompt_content: Optional[str] = None,
        cli_tool: Optional[str] = None,
    ) -> bool:
        """HITL checkpoint 1 — user approved the generated prompt.

        Args:
            prompt_content: Optional edited prompt text to persist.
            cli_tool: CLI tool name to use for code generation.

        Returns True if gate was approved, False if not at the expected gate.
        """
        if self.state_mgr.current_status != PipelineStatus.HITL_PROMPT_REVIEW:
            logger.warning("approve_prompt() called but not at HITL_PROMPT_REVIEW")
            return False

        metadata: dict[str, Any] = {}
        if cli_tool:
            metadata["selected_cli_tool"] = cli_tool
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
            self.state_mgr.transition_to(PipelineStatus.PIPELINE_COMPLETE)
            self._emit("pipeline_complete", {"reason": "user_approved_accepted_review"})
            return True

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

    def pause(self) -> bool:
        """Request the pipeline to pause after the current step completes."""
        self._pause_event.set()
        logger.info("Pause requested")
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

    def retry_code_generator(self) -> bool:
        """Retry code generation after a failure.

        Only callable when at CODE_GEN_FAILED.
        Clears the failure flag and resumes from CODE_GENERATION.
        """
        if self.state_mgr.current_status != PipelineStatus.CODE_GEN_FAILED:
            logger.warning("retry_code_generator() called but not at CODE_GEN_FAILED")
            return False
        self.state_mgr.transition_to(
            PipelineStatus.CODE_GENERATION,
            metadata={"code_gen_failed": False, "code_gen_error": ""},
        )
        self._emit("state_changed", {"retry": "code_generator"})
        self._resume_in_thread()
        return True

    def retry_code_reviewer(self) -> bool:
        """Retry code review after a failure.

        Only callable when at HITL_REVIEW_DECISION with code_review_failed metadata.
        Clears the failure flag and resumes from CODE_REVIEW.
        """
        if self.state_mgr.current_status != PipelineStatus.HITL_REVIEW_DECISION:
            logger.warning("retry_code_reviewer() called but not at HITL_REVIEW_DECISION")
            return False
        if not self.state_mgr.state.metadata.get("code_review_failed"):
            logger.warning("retry_code_reviewer() called but code_review_failed not set")
            return False
        self.state_mgr.transition_to(
            PipelineStatus.CODE_REVIEW,
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
        """Transition ADO work items from New to Active when code generation starts (iteration 1 only)."""
        meta = self.state_mgr.state.metadata
        work_item_ids = meta.get("ado_work_item_ids", [])
        ado_org = meta.get("ado_org", "")
        ado_token = meta.get("ado_token", "")
        if not work_item_ids or not ado_org or not ado_token:
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
                        client.patch(
                            f"https://dev.azure.com/{org_enc}/_apis/wit/workitems/{wi_id}?api-version=7.1",
                            json=patch_body,
                        )
                    except Exception:
                        logger.debug("Failed to activate ADO work item %d", wi_id, exc_info=True)

            logger.info("Activated %d ADO work items to Active state", len(work_item_ids))
        except Exception:
            logger.warning("Failed to activate ADO work items", exc_info=True)

    def _close_ado_work_items(self) -> None:
        """Transition ADO work items from Active to Closed on pipeline completion."""
        meta = self.state_mgr.state.metadata
        work_item_ids = meta.get("ado_work_item_ids", [])
        ado_org = meta.get("ado_org", "")
        ado_token = meta.get("ado_token", "")
        if not work_item_ids or not ado_org or not ado_token:
            return
        try:
            import asyncio
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

            async def _update_all() -> None:
                async with httpx.AsyncClient(headers=headers, timeout=15, follow_redirects=False) as client:
                    for wi_id in work_item_ids:
                        try:
                            await client.patch(
                                f"https://dev.azure.com/{org_enc}/_apis/wit/workitems/{wi_id}?api-version=7.1",
                                json=patch_body,
                            )
                        except Exception:
                            logger.debug("Failed to close ADO work item %d", wi_id, exc_info=True)

            # Run in existing event loop or create one
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_update_all())
            except RuntimeError:
                asyncio.run(_update_all())

            logger.info("Queued ADO work item state update to Closed for %d items", len(work_item_ids))
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
        t = threading.Thread(target=self._loop, daemon=True, name="orchestrator-loop")
        t.start()

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
