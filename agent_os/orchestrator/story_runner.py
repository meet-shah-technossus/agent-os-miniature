"""Story pipeline runner — extracted from Orchestrator (Phase 8.5).

Owns the step handlers for GitHub Review (GHR) mode: dependency analysis,
queue management, per-story prompt/code/review cycles. Shared steps
(idle, load_requirements) remain on the Orchestrator.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

from ..constants import EventType, PipelineMode, TerminalEvent
from ..storage.models import PipelineStatus

if TYPE_CHECKING:
    from .engine import Orchestrator

logger = logging.getLogger(__name__)


class StoryPipelineRunner:
    """Executes GHR (github_review) mode pipeline steps."""

    def __init__(self, orch: Orchestrator) -> None:
        self._orch = orch

    # ── Proxy accessors ───────────────────────────────────────────────────────

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

    def _close_ado_work_items(self, story_id: Optional[str] = None) -> None:
        self._orch._close_ado_work_items(story_id)

    def _resume_in_thread(self) -> None:
        self._orch._resume_in_thread()

    # ── Step handlers ─────────────────────────────────────────────────────────

    def step_fork_and_clone(self) -> bool:
        """Fork the source repo and clone it locally (once per pipeline run)."""
        import re as _re

        cfg = self.config
        source_url = getattr(cfg.github_review, "source_repo_url", "") or ""

        if not source_url:
            logger.info("[GHR] No source_repo_url — skipping fork+clone (will use existing root_path)")
            return True

        m = _re.match(
            r"https?://github\.com/([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+?)(?:\.git)?/?$",
            source_url,
        )
        if not m:
            err = f"[GHR] Cannot parse source_repo_url: {source_url!r}"
            logger.error(err)
            self.state_mgr.transition_to(PipelineStatus.FAILED, metadata={"error": err})
            self._emit(EventType.ERROR, {"message": err})
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
                    self._emit(EventType.ERROR, {"message": err})
                    return False
                logger.info("[GHR] Fork already exists — continuing")

            self._emit("fork_waiting", {"fork": f"{owner}/{fork_name}"})
            if not vcs.wait_for_fork(owner, fork_name, max_wait_seconds=30):
                logger.warning("[GHR] Fork %s/%s not ready after 30s — proceeding anyway", owner, fork_name)

        clone_repo_owner = source_owner if same_owner else owner
        clone_repo_name = source_repo if same_owner else fork_name
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
                self._emit(EventType.ERROR, {"message": err})
                return False

        git = GitOpsManager(str(clone_target))
        git.set_user("Agent OS Bot", "agent-os@noreply.github.com")

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

    def step_analyse_dependencies(self) -> None:
        """ANALYSING_DEPENDENCIES → QUEUE_READY."""
        import asyncio
        from ..orchestrator.story_queue import StoryQueueManager

        logger.info("[GHR] Analysing story dependencies")
        self._emit(EventType.STATE_CHANGED, {"step": "analyse_dependencies"})

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
            self._emit(EventType.PIPELINE_COMPLETE, {"reason": "no_stories"})
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
        self._emit(EventType.STATE_CHANGED)

    def step_queue_ready(self) -> None:
        """QUEUE_READY → STORY_PROMPT_GENERATION (or PIPELINE_COMPLETE)."""
        from ..orchestrator.story_queue import StoryQueueManager

        if not self.config.project.root_path:
            if not self.step_fork_and_clone():
                return

        mgr = StoryQueueManager(self.db)
        next_story = mgr.dequeue()

        if next_story is None:
            counts = mgr.counts()
            logger.info("[GHR] Queue exhausted — %s", counts)
            self.state_mgr.transition_to(PipelineStatus.PIPELINE_COMPLETE)
            self._emit(EventType.PIPELINE_COMPLETE, {"reason": "queue_exhausted", "counts": counts})
            self._close_ado_work_items()
            return

        logger.info("[GHR] Starting story: %s — %s", next_story.story_id, next_story.title)
        self.state_mgr.update_story_context(current_story_id=next_story.story_id)
        self._emit("story_started", {
            "story_id": next_story.story_id,
            "title": next_story.title,
            "position": next_story.position,
        })
        self.state_mgr.update_metadata({"story_iteration": 1, "story_review_json": None})
        self.state_mgr.transition_to(PipelineStatus.STORY_PROMPT_GENERATION)
        self._emit(EventType.STATE_CHANGED)

    def step_story_prompt_generation(self) -> None:
        """STORY_PROMPT_GENERATION → HITL_PROMPT_REVIEW."""
        import json as _json
        import uuid as _uuid
        from ..prompt_generator.runner import PromptGeneratorRunner
        from ..orchestrator.story_queue import StoryQueueManager

        state = self.state_mgr.state
        story_id = state.current_story_id
        story_iter = state.metadata.get("story_iteration", 1)

        logger.info("[GHR] Story prompt generation — story=%s iter=%d", story_id, story_iter)
        self._emit(EventType.PROMPT_GENERATION_STARTED, {"story_id": story_id, "story_iteration": story_iter})

        mgr = StoryQueueManager(self.db)
        item = mgr.get_item(story_id) if story_id else None
        if item is None:
            logger.error("[GHR] Could not find story %s in queue — failing", story_id)
            self.state_mgr.transition_to(PipelineStatus.FAILED)
            return

        acs_md = "\n".join(f"- {ac}" for ac in item.acceptance_criteria) or "(no acceptance criteria)"
        requirements_text = (
            f"## Story: {item.title}\n\n"
            f"{item.description}\n\n"
            f"### Acceptance Criteria\n{acs_md}\n"
        )

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
        self._emit_terminal(TerminalEvent.SESSION_START, "PROMPT_GENERATOR", _pg_session,
                            story_id=story_id, iteration=story_iter, model=model_pg)

        def _on_stdout(line: str) -> None:
            self._emit(EventType.PROMPT_TOKEN, {"line": line})
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
            self._emit_terminal(TerminalEvent.SESSION_END, "PROMPT_GENERATOR", _pg_session, exit_code=1)
            self.state_mgr.update_metadata({"story_prompt_error": str(exc)})
            self.state_mgr.transition_to(PipelineStatus.FAILED)
            self._emit(EventType.ERROR, {"message": str(exc), "story_id": story_id})
            return

        self.state_mgr.update_metadata({"prompt_content": prompt_text, "story_prompt_error": ""})
        self._emit_terminal(TerminalEvent.SESSION_END, "PROMPT_GENERATOR", _pg_session, exit_code=0)
        self._emit(EventType.PROMPT_GENERATION_COMPLETE, {
            "story_id": story_id, "story_iteration": story_iter, "char_count": len(prompt_text),
        })
        self.state_mgr.transition_to(PipelineStatus.HITL_PROMPT_REVIEW)
        self._emit(EventType.HITL_GATE, {"gate": PipelineStatus.HITL_PROMPT_REVIEW.value})

    def step_story_code_generation(self) -> None:
        """STORY_CODE_GENERATION → STORY_CODE_REVIEW."""
        import uuid as _uuid
        import re as _re
        from ..code_generator.runner import CodeGeneratorRunner
        from ..vcs.factory import make_vcs_client
        from ..orchestrator.story_queue import StoryQueueManager

        state = self.state_mgr.state
        story_id = state.current_story_id
        story_iter = state.metadata.get("story_iteration", 1)

        logger.info("[GHR] Story code generation — story=%s iter=%d", story_id, story_iter)

        if story_iter == 1:
            self._activate_ado_work_items()

        mgr = StoryQueueManager(self.db)
        item = mgr.get_item(story_id) if story_id else None

        if item and not item.branch_name:
            slug = _re.sub(r"[^a-z0-9]+", "-", item.title.lower()).strip("-")[:40]
            branch_name = f"story-{story_id}-{slug}".lower()
            mgr.update_branch(story_id, branch_name)
        else:
            branch_name = (item.branch_name if item else None) or f"story-{story_id}"

        self.config.project.feature_branch = branch_name
        if story_iter == 1:
            self.state_mgr.update_metadata({"pr_number": None, "pr_url": ""})

        prompt_path = getattr(self.config.project, "prompt_file_path", "") or "data/prompts/latest.md"
        working_dir = getattr(self.config.project, "root_path", "") or ""
        if not working_dir:
            working_dir = self._provision_project_dir()

        cli_tool = state.metadata.get("selected_cli_tool")
        if cli_tool:
            self.config.codex.cli_routing["CODE_GENERATOR"] = cli_tool
        cli_model = state.metadata.get("selected_cli_model")
        if cli_model:
            self.config.codex.model_routing["CODE_GENERATOR"] = cli_model

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
        self._emit_terminal(TerminalEvent.SESSION_START, "CODE_GENERATOR", _cg_session,
                            story_id=story_id, iteration=story_iter, model=_cg_model, tool=_cg_tool)
        self._emit(EventType.CODE_GENERATION_STARTED, {"story_id": story_id, "story_iteration": story_iter})

        def _on_stdout(line: str) -> None:
            self._emit(EventType.CODEX_STDOUT, {"line": line})
            self._emit_terminal("line", "CODE_GENERATOR", _cg_session,
                                line=line, stream="stdout", story_id=story_id)

        def _on_stderr(line: str) -> None:
            self._emit(EventType.CODEX_STDERR, {"line": line})
            self._emit_terminal("line", "CODE_GENERATOR", _cg_session,
                                line=line, stream="stderr", story_id=story_id)

        runner = CodeGeneratorRunner(self.config, vcs_client=make_vcs_client(self.config))
        with self._wrapper_lock:
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
            with self._wrapper_lock:
                self._active_codex_wrapper = None
            logger.exception("[GHR] Story code generator raised: %s", exc)
            self._emit_terminal(TerminalEvent.SESSION_END, "CODE_GENERATOR", _cg_session, exit_code=1)
            if self._code_gen_stop_requested.is_set():
                self.state_mgr.transition_to(
                    PipelineStatus.CODE_GEN_STOPPED,
                    metadata={"stopped_working_dir": str(working_dir), "stopped_story_id": story_id or ""},
                )
                self._emit(EventType.CODE_GEN_STOPPED, {"story_id": story_id})
            else:
                self.state_mgr.transition_to(
                    PipelineStatus.CODE_GEN_FAILED,
                    metadata={"code_gen_failed": True, "code_gen_error": str(exc)},
                )
                self._emit(EventType.CODE_GEN_FAILED, {"story_id": story_id, "error": str(exc)})
            return
        with self._wrapper_lock:
            self._active_codex_wrapper = None

        if self._code_gen_stop_requested.is_set():
            self._emit_terminal(TerminalEvent.SESSION_END, "CODE_GENERATOR", _cg_session, exit_code=-2)
            self.state_mgr.transition_to(
                PipelineStatus.CODE_GEN_STOPPED,
                metadata={"stopped_working_dir": str(working_dir), "stopped_story_id": story_id or ""},
            )
            self._emit(EventType.CODE_GEN_STOPPED, {"story_id": story_id, "working_dir": str(working_dir)})
            return

        meta_update: dict = {"completion_status": gen_result.completion.status.value}
        if gen_result.pr_number is not None:
            meta_update["pr_number"] = gen_result.pr_number
            meta_update["pr_url"] = gen_result.pr_url
        if gen_result.git_errors:
            meta_update["git_errors"] = gen_result.git_errors
        self.state_mgr.update_metadata(meta_update)

        if gen_result.git_errors:
            for git_err in gen_result.git_errors:
                self._emit_terminal("line", "CODE_GENERATOR", _cg_session,
                                    line=f"[git] {git_err}", stream="stderr", story_id=story_id)

        _is_incomplete = gen_result.completion.status.value in ("failed", "partial")
        self._emit_terminal(TerminalEvent.SESSION_END, "CODE_GENERATOR", _cg_session,
                            exit_code=0 if not _is_incomplete else 1)

        if _is_incomplete:
            err = gen_result.completion.reason or "Code generation did not complete successfully."
            self.state_mgr.transition_to(
                PipelineStatus.CODE_GEN_FAILED,
                metadata={"code_gen_failed": True, "code_gen_error": err},
            )
            self._emit(EventType.CODE_GEN_FAILED, {"story_id": story_id, "error": err})
            return

        if gen_result.pr_number is None and gen_result.git_errors:
            err_git = "; ".join(gen_result.git_errors)
            self.state_mgr.transition_to(
                PipelineStatus.CODE_GEN_FAILED,
                metadata={"code_gen_failed": True, "code_gen_error": f"Git ops failed: {err_git}"},
            )
            self._emit(EventType.CODE_GEN_FAILED, {"story_id": story_id, "error": err_git})
            return

        self._emit(EventType.CODE_GENERATION_COMPLETE, {
            "story_id": story_id, "story_iteration": story_iter,
            "pr_number": gen_result.pr_number, "pr_url": gen_result.pr_url,
        })
        self.state_mgr.transition_to(PipelineStatus.STORY_CODE_REVIEW)
        self._emit(EventType.STATE_CHANGED)

    def step_story_code_review(self) -> None:
        """STORY_CODE_REVIEW → HITL_REVIEW_DECISION or STORY_COMPLETE."""
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
        self._emit(EventType.CODE_REVIEW_STARTED, {"story_id": story_id, "story_iteration": story_iter})

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
                logger.warning("[GHR] PR discovery failed", exc_info=True)

        if pr_number is None:
            err_no_pr = "No pull request found or created — code may not have been pushed to GitHub."
            self.state_mgr.transition_to(
                PipelineStatus.CODE_GEN_FAILED,
                metadata={"code_gen_failed": True, "code_gen_error": err_no_pr},
            )
            self._emit(EventType.CODE_GEN_FAILED, {"story_id": story_id, "reason": "no_pr", "error": err_no_pr})
            return

        _cr_session = f"cr-story-{story_id}-iter{story_iter}-{_uuid.uuid4().hex[:8]}"
        _cr_cfg_ghr = getattr(self.config, "code_reviewer", None)
        _cr_provider_ghr = (getattr(_cr_cfg_ghr, "provider", None) or "openai") if _cr_cfg_ghr else "openai"
        if _cr_provider_ghr == "ollama":
            _cr_model = (getattr(_cr_cfg_ghr, "ollama_model", "") or "") if _cr_cfg_ghr else ""
        else:
            _cr_model = (getattr(_cr_cfg_ghr, "model", "") or "") if _cr_cfg_ghr else ""
        _cr_model = _cr_model or self.config.codex.model_routing.get("CODE_REVIEWER") or self.config.codex.default_model or ""
        self._emit_terminal(TerminalEvent.SESSION_START, "CODE_REVIEWER", _cr_session,
                            story_id=story_id, iteration=story_iter, model=_cr_model)

        def _on_stdout(line: str) -> None:
            self._emit("reviewer_stdout", {"line": line})
            self._emit_terminal("line", "CODE_REVIEWER", _cr_session,
                                line=line, stream="stdout", story_id=story_id)

        runner = CodeReviewerRunner(self.config, vcs_client=_project_vcs())
        _mgr = StoryQueueManager(self.db)
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
            self._emit_terminal(TerminalEvent.SESSION_END, "CODE_REVIEWER", _cr_session, exit_code=1)
            err_msg = str(exc)
            self.state_mgr.transition_to(
                PipelineStatus.HITL_REVIEW_DECISION,
                metadata={"code_review_failed": True, "code_review_error": err_msg},
            )
            self._emit("code_review_failed", {"story_id": story_id, "error": err_msg})
            self._emit(EventType.HITL_GATE, {"gate": PipelineStatus.HITL_REVIEW_DECISION.value})
            return

        review = run_result.review
        review_json_str = review.model_dump_json()
        self.state_mgr.update_metadata({
            "story_review_json": review_json_str,
            "review_json_content": review_json_str,
            "review_overall_status": review.overall_status,
            "pr_merged": str(run_result.pr_merged),
        })
        self._upsert_iteration(story_iter, review_json_content=review_json_str)

        if run_result.pr_merged:
            StoryQueueManager(self.db).mark_complete(
                story_id,
                pr_number=pr_number,
                pr_url=state.metadata.get("pr_url", ""),
            )

        self._emit_terminal(TerminalEvent.SESSION_END, "CODE_REVIEWER", _cr_session, exit_code=0)
        self._emit(EventType.CODE_REVIEW_COMPLETE, {
            "story_id": story_id, "story_iteration": story_iter,
            "overall_status": review.overall_status,
            "overall_score": review.overall_score,
            "pr_merged": run_result.pr_merged,
        })

        if review.overall_status == "accepted":
            logger.info("[GHR] Story %s accepted (iter %d) — moving to STORY_COMPLETE", story_id, story_iter)
            self.state_mgr.update_story_context(stories_completed=state.stories_completed + 1)
            self.state_mgr.transition_to(PipelineStatus.STORY_COMPLETE)
            self._emit("story_completed", {"story_id": story_id, "story_iteration": story_iter})
        elif story_iter >= max_story_iters:
            logger.warning("[GHR] Story %s hit max iterations (%d) — marking failed", story_id, max_story_iters)
            StoryQueueManager(self.db).mark_failed(story_id, reason=f"Max iterations ({max_story_iters}) reached")
            self.state_mgr.update_story_context(stories_completed=state.stories_completed + 1)
            self.state_mgr.transition_to(PipelineStatus.STORY_COMPLETE)
            self._emit("story_failed", {"story_id": story_id, "reason": "max_iterations"})
        else:
            next_iter = story_iter + 1
            logger.info("[GHR] Story %s rejected — pausing at review gate before iteration %d",
                        story_id, next_iter)
            self.state_mgr.update_metadata({"story_iteration": next_iter})
            StoryQueueManager(self.db).increment_iteration(story_id)
            if self.config.orchestrator.auto_approve_hitl:
                self.state_mgr.transition_to(PipelineStatus.STORY_PROMPT_GENERATION)
                self._emit(EventType.STATE_CHANGED, {"story_id": story_id, "next_story_iteration": next_iter})
                self._resume_in_thread()
            else:
                self.state_mgr.transition_to(PipelineStatus.HITL_REVIEW_DECISION)
                self._emit(EventType.HITL_GATE, {
                    "gate": PipelineStatus.HITL_REVIEW_DECISION.value,
                    "story_id": story_id,
                    "next_story_iteration": next_iter,
                    "review_overall_status": review.overall_status,
                })

    def step_story_complete(self) -> None:
        """STORY_COMPLETE → QUEUE_READY (next story) or PIPELINE_COMPLETE."""
        from ..orchestrator.story_queue import StoryQueueManager

        state = self.state_mgr.state
        story_id = state.current_story_id
        mgr = StoryQueueManager(self.db)

        logger.info("[GHR] Story complete: %s — checking queue", story_id)

        self._close_ado_work_items(story_id=story_id)

        if mgr.is_complete():
            counts = mgr.counts()
            logger.info("[GHR] All stories processed — %s", counts)
            self.state_mgr.transition_to(PipelineStatus.PIPELINE_COMPLETE)
            self._emit(EventType.PIPELINE_COMPLETE, {
                "reason": "all_stories_processed",
                "stories_completed": state.stories_completed,
                "stories_total": state.stories_total,
                "counts": counts,
            })
        else:
            self.state_mgr.transition_to(PipelineStatus.QUEUE_READY)
            self._emit(EventType.STATE_CHANGED, {"next": "queue_ready"})
