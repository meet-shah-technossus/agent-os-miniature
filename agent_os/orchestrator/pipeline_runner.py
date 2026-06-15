"""Standard pipeline runner — extracted from Orchestrator (Phase 8.4).

Owns the step handlers for standard mode: prompt generation, code generation,
and code review. Shared steps (idle, load_requirements) remain on the Orchestrator.
"""
from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..constants import EventType, TerminalEvent
from ..storage.models import PipelineStatus

if TYPE_CHECKING:
    from .engine import Orchestrator

logger = logging.getLogger(__name__)


class StandardPipelineRunner:
    """Executes standard-mode pipeline steps on behalf of the Orchestrator."""

    def __init__(self, orch: Orchestrator) -> None:
        self._orch = orch

    # ── Proxy accessors (keep step method bodies identical to original) ────

    @property
    def config(self) -> Any:
        return self._orch.config

    @property
    def state_mgr(self) -> Any:
        return self._orch.state_mgr

    @property
    def db(self) -> Any:
        return self._orch.db

    @property
    def _wrapper_lock(self):
        return self._orch._wrapper_lock

    @property
    def _code_gen_stop_requested(self):
        return self._orch._code_gen_stop_requested

    @property
    def _active_codex_wrapper(self):
        return self._orch._active_codex_wrapper

    @_active_codex_wrapper.setter
    def _active_codex_wrapper(self, val):
        self._orch._active_codex_wrapper = val

    def _emit(self, *args: Any, **kwargs: Any) -> None:
        self._orch._emit(*args, **kwargs)

    def _emit_terminal(self, *args: Any, **kwargs: Any) -> None:
        self._orch._emit_terminal(*args, **kwargs)

    def _upsert_iteration(self, *args: Any, **kwargs: Any) -> None:
        self._orch._upsert_iteration(*args, **kwargs)

    def _provision_project_dir(self) -> str:
        return self._orch._provision_project_dir()

    def _activate_ado_work_items(self) -> None:
        self._orch._activate_ado_work_items()

    # ── Step handlers ─────────────────────────────────────────────────────────

    def step_prompt_generation(self) -> None:
        """PROMPT_GENERATION → HITL_PROMPT_REVIEW.

        Calls the real Prompt Generator (OpenAI API) to produce the iteration
        prompt, then pauses at the HITL review gate.
        """
        from ..prompt_generator.runner import PromptGeneratorRunner

        state = self.state_mgr.state
        iteration = state.current_iteration
        logger.info("Prompt generation — iteration %d", iteration)
        self._emit(EventType.PROMPT_GENERATION_STARTED, {"iteration": iteration})

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
        self._emit_terminal(TerminalEvent.SESSION_START, "PROMPT_GENERATOR", _pg_session,
                            iteration=iteration, module_id="", model=model_pg)

        def _on_stdout(line: str) -> None:
            self._emit(EventType.PROMPT_TOKEN, {"line": line})
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
            self._emit_terminal(TerminalEvent.SESSION_END, "PROMPT_GENERATOR", _pg_session, exit_code=1)
            err_msg = str(exc)
            self.state_mgr.transition_to(
                PipelineStatus.HITL_PROMPT_REVIEW,
                metadata={"prompt_gen_failed": True, "prompt_gen_error": err_msg},
            )
            self._emit(EventType.PROMPT_GEN_FAILED, {"iteration": iteration, "error": err_msg})
            self._emit(EventType.HITL_GATE, {"gate": PipelineStatus.HITL_PROMPT_REVIEW.value})
            return

        # Persist prompt content to DB metadata
        self.state_mgr.update_metadata({"prompt_content": prompt_text})
        logger.info("Prompt generation complete — %d chars", len(prompt_text))
        self._emit_terminal(TerminalEvent.SESSION_END, "PROMPT_GENERATOR", _pg_session, exit_code=0)
        self._emit(EventType.PROMPT_GENERATION_COMPLETE, {"iteration": iteration, "char_count": len(prompt_text)})

        self.state_mgr.transition_to(PipelineStatus.HITL_PROMPT_REVIEW)
        self._emit(EventType.HITL_GATE, {"gate": PipelineStatus.HITL_PROMPT_REVIEW.value})

    def step_code_generation(self) -> None:
        """CODE_GENERATION → CODE_REVIEW.

        Invokes the Code Generator (Codex CLI) then performs iteration-aware
        git commit + push + PR operations via the configured VCS provider.
        """
        from ..code_generator.runner import CodeGeneratorRunner
        from ..vcs.factory import make_vcs_client

        state = self.state_mgr.state
        iteration = state.current_iteration
        logger.info("Code generation — iteration %d", iteration)
        self._emit(EventType.CODE_GENERATION_STARTED, {"iteration": iteration})

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
            with contextlib.suppress(TypeError, ValueError):
                pr_number = int(pr_raw)

        import uuid as _uuid
        _cg_session = f"cg-{iteration}-{_uuid.uuid4().hex[:8]}"
        _cg_model = self.config.codex.model_routing.get("CODE_GENERATOR") or self.config.codex.default_model or ""
        _cg_tool = cli_tool or self.config.codex.cli_routing.get("CODE_GENERATOR", "codex")
        self._emit_terminal(TerminalEvent.SESSION_START, "CODE_GENERATOR", _cg_session,
                            iteration=iteration, module_id="",
                            model=_cg_model, tool=_cg_tool)

        def _on_stdout(line: str) -> None:
            self._emit(EventType.CODEX_STDOUT, {"line": line})
            self._emit_terminal("line", "CODE_GENERATOR", _cg_session,
                                line=line, stream="stdout",
                                iteration=iteration, module_id="")

        def _on_stderr(line: str) -> None:
            self._emit(EventType.CODEX_STDERR, {"line": line})
            self._emit_terminal("line", "CODE_GENERATOR", _cg_session,
                                line=line, stream="stderr",
                                iteration=iteration, module_id="")

        # Iteration 1: activate ADO work items (New → Active)
        if iteration == 1:
            self._activate_ado_work_items()

        runner = CodeGeneratorRunner(self.config, vcs_client=make_vcs_client(self.config))
        with self._wrapper_lock:
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
            with self._wrapper_lock:
                self._active_codex_wrapper = None
            logger.exception("Code generator raised: %s", exc)
            self._emit_terminal(TerminalEvent.SESSION_END, "CODE_GENERATOR", _cg_session, exit_code=1)
            if self._code_gen_stop_requested.is_set():
                self.state_mgr.transition_to(
                    PipelineStatus.CODE_GEN_STOPPED,
                    metadata={"stopped_working_dir": str(working_dir)},
                )
                self._emit(EventType.CODE_GEN_STOPPED, {"iteration": iteration})
            else:
                err_msg = str(exc)
                self.state_mgr.transition_to(
                    PipelineStatus.CODE_GEN_FAILED,
                    metadata={"code_gen_failed": True, "code_gen_error": err_msg},
                )
                self._emit(EventType.CODE_GEN_FAILED, {"iteration": iteration, "error": err_msg})
            return
        with self._wrapper_lock:
            self._active_codex_wrapper = None

        # If the user stopped code gen mid-flight, transition to CODE_GEN_STOPPED
        if self._code_gen_stop_requested.is_set():
            self._emit_terminal(TerminalEvent.SESSION_END, "CODE_GENERATOR", _cg_session, exit_code=-2)
            self.state_mgr.transition_to(
                PipelineStatus.CODE_GEN_STOPPED,
                metadata={"stopped_working_dir": str(working_dir)},
            )
            self._emit(EventType.CODE_GEN_STOPPED, {"iteration": iteration, "working_dir": str(working_dir)})
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
        self._emit_terminal(TerminalEvent.SESSION_END, "CODE_GENERATOR", _cg_session,
                            exit_code=0 if not _is_incomplete else 1)

        if _is_incomplete:
            err_msg = gen_result.completion.reason or "Code generation incomplete (no summary.md produced)"
            logger.warning("Code generation incomplete — transitioning to CODE_GEN_FAILED: %s", err_msg)
            self.state_mgr.transition_to(
                PipelineStatus.CODE_GEN_FAILED,
                metadata={"code_gen_failed": True, "code_gen_error": err_msg},
            )
            self._emit(EventType.CODE_GEN_FAILED, {"iteration": iteration, "error": err_msg})
            return

        self._emit(EventType.CODE_GENERATION_COMPLETE, {
            "iteration": iteration,
            "pr_number": gen_result.pr_number,
            "pr_url": gen_result.pr_url,
            "retried": gen_result.retried,
        })
        self.state_mgr.transition_to(PipelineStatus.CODE_REVIEW)
        self._emit(EventType.STATE_CHANGED)

    def step_code_review(self) -> None:
        """CODE_REVIEW → HITL_REVIEW_DECISION (or PIPELINE_COMPLETE if accepted).

        Invokes the Code Reviewer (OpenAI API via PR diff) and posts GitHub PR
        comments. Transitions to HITL_REVIEW_DECISION for user approval, or
        directly to PIPELINE_COMPLETE if the reviewer accepted and merged.
        """

        from ..code_reviewer.runner import CodeReviewerRunner
        from ..vcs.factory import make_vcs_client

        state = self.state_mgr.state
        iteration = state.current_iteration
        logger.info("Code review — iteration %d", iteration)

        # Clear any stale failure flags
        self.state_mgr.update_metadata({
            "code_review_failed": False,
            "code_review_error": "",
            "pr_failed": False,
            "pr_error": "",
        })

        self._emit(EventType.CODE_REVIEW_STARTED, {"iteration": iteration})

        # Retrieve pr_number stored by step_code_generation
        pr_number: int | None = None
        pr_raw = state.metadata.get("pr_number")
        if pr_raw is not None:
            with contextlib.suppress(TypeError, ValueError):
                pr_number = int(pr_raw)

        feature_branch = self.config.project.feature_branch or "dev"

        # Build a VCS client scoped to the actual project repo
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
                logger.warning("PR discovery failed", exc_info=True)

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
            self._emit(EventType.HITL_GATE, {"gate": PipelineStatus.HITL_REVIEW_DECISION.value})
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
        self._emit_terminal(TerminalEvent.SESSION_START, "CODE_REVIEWER", _cr_session,
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
            self._emit_terminal(TerminalEvent.SESSION_END, "CODE_REVIEWER", _cr_session, exit_code=1)
            err_msg = str(exc)
            self.state_mgr.transition_to(
                PipelineStatus.HITL_REVIEW_DECISION,
                metadata={"code_review_failed": True, "code_review_error": err_msg},
            )
            self._emit("code_review_failed", {"iteration": iteration, "error": err_msg})
            self._emit(EventType.HITL_GATE, {"gate": PipelineStatus.HITL_REVIEW_DECISION.value})
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

        self._emit_terminal(TerminalEvent.SESSION_END, "CODE_REVIEWER", _cr_session, exit_code=0)
        self._emit(EventType.CODE_REVIEW_COMPLETE, {
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
            self._emit(EventType.PIPELINE_COMPLETE, {"reason": "accepted_by_reviewer", "iteration": iteration})
            return

        self.state_mgr.transition_to(PipelineStatus.HITL_REVIEW_DECISION)
        self._emit(EventType.HITL_GATE, {"gate": PipelineStatus.HITL_REVIEW_DECISION.value})
