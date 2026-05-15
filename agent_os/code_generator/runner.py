"""Code Generator runner — generates code from prompts via Codex CLI.

Reads the stamped prompt file, prepends guardrails, invokes Codex in the
project root, detects completion, then performs iteration-aware git and GitHub
PR operations:

  Iteration 1:
    1. init git repo (if needed)
    2. configure user identity
    3. set remote origin (authenticated HTTPS)
    4. commit all generated files on main
    5. push main →  GitHub
    6. checkout feature branch, push
    7. open PR: feature → main

  Iteration 2+:
    1. stage+commit all changes on the existing feature branch
    2. push the feature branch
    3. resolve/reply to all open PR review comments
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from ..codex.session import CodexResult, SessionType
from ..codex.wrapper import CodexWrapper
from ..config.schema import AgentOSConfig
from ..git_ops.manager import GitOpsManager
from ..vcs.base import VCSClient
from .completion import CompletionResult, CompletionStatus, consume_summary, detect_completion
from .guardrails import GUARDRAIL_PROMPT

logger = logging.getLogger(__name__)

_BOT_NAME = "Agent OS Bot"
_BOT_EMAIL = "agent-os@noreply.github.com"


@dataclass
class CodeGenResult:
    """Outcome of a code-generation run."""
    completion: CompletionResult
    codex_result: CodexResult
    summary_text: str = ""
    retried: bool = False
    # Git / PR metadata (populated when vcs=github)
    pr_number: Optional[int] = None
    pr_url: str = ""
    branch_pushed: str = ""          # "main" (iter 1) or feature branch name
    git_errors: list[str] = field(default_factory=list)


class CodeGeneratorRunner:
    """Generate code for a single pipeline iteration via Codex CLI."""

    def __init__(
        self,
        config: AgentOSConfig,
        identity_ctx=None,
        vcs_client: VCSClient | None = None,
    ) -> None:
        self._config = config
        self._identity_ctx = identity_ctx
        self._vcs_client = vcs_client
        self._codex = CodexWrapper(
            timeout_seconds=config.codex.timeout_seconds,
            max_retries=0,
            openai_api_key=config.secrets.openai_api_key,
            project_root=config.project.root_path or ".",
            model_routing=config.codex.model_routing,
            default_model=config.codex.model,
            cli_routing=config.codex.cli_routing,
        )

    # ── Public interface ───────────────────────────────────────────────────

    def run(
        self,
        prompt_path: str | Path,
        working_dir: str | Path,
        iteration: int = 1,
        pr_number: Optional[int] = None,
        on_stdout: Optional[Callable[[str], None]] = None,
        on_stderr: Optional[Callable[[str], None]] = None,
    ) -> CodeGenResult:
        """Execute code generation with one automatic retry on partial completion.

        Args:
            prompt_path: Path to the prompt file written by the Prompt Generator.
            working_dir: Working directory passed to Codex (project root).
            iteration:   Current pipeline iteration number (1-based).
            pr_number:   GitHub PR number from a prior iteration (required for
                         iteration >= 2 to resolve review comments).
            on_stdout:   Optional callback for Codex stdout lines.
            on_stderr:   Optional callback for Codex stderr lines.

        Returns:
            CodeGenResult with completion, CI, and git/PR metadata.
        """
        prompt_path = Path(prompt_path)
        working_dir = Path(working_dir) if working_dir else Path(".")

        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

        prompt_text = self._build_prompt(prompt_path, iteration)
        codex_result = self._execute(prompt_text, working_dir, on_stdout=on_stdout, on_stderr=on_stderr)
        completion = detect_completion(codex_result.exit_code, working_dir, codex_result.timed_out)

        # One automatic retry on partial completion
        retried = False
        if completion.status == CompletionStatus.PARTIAL:
            logger.info("Partial completion detected — retrying once.")
            retry_prompt = (
                f"{prompt_text}\n\n"
                "# RETRY NOTICE\n"
                "The previous attempt was incomplete. "
                "Continue from where you left off and ensure summary.md "
                "is written with END marker when done.\n"
            )
            codex_result = self._execute(retry_prompt, working_dir, on_stdout=on_stdout, on_stderr=on_stderr)
            completion = detect_completion(codex_result.exit_code, working_dir, codex_result.timed_out)
            retried = True

        summary = consume_summary(working_dir)

        result = CodeGenResult(
            completion=completion,
            codex_result=codex_result,
            summary_text=summary,
            retried=retried,
        )

        # Only run git ops when Codex succeeded
        if completion.status == CompletionStatus.COMPLETE:
            git_errors = self._git_operations(working_dir, iteration, pr_number, result)
            result.git_errors = git_errors

        return result

    # ── Git / GitHub operations ────────────────────────────────────────────

    def _git_operations(
        self,
        working_dir: Path,
        iteration: int,
        pr_number: Optional[int],
        result: CodeGenResult,
    ) -> list[str]:
        """Perform iteration-aware git commit + push + PR operations.

        Returns a list of error strings (empty = all OK).
        """
        cfg = self._config
        feature_branch = (
            getattr(cfg.project, "feature_branch", None)
            or getattr(getattr(cfg, "github", None), "feature_branch", None)
            or "agent-os/dev"
        )
        repo_name = (
            getattr(cfg.project, "repo_name", None)
            or getattr(getattr(cfg, "github", None), "repo", None)
            or ""
        )

        # Resolve VCS client: use injected one, or build via factory
        gh: VCSClient | None = self._vcs_client
        if gh is None:
            from ..vcs.factory import make_vcs_client
            gh = make_vcs_client(cfg)

        if gh is None:
            logger.info("VCS credentials not configured — skipping git operations")
            return []

        errors: list[str] = []
        git = GitOpsManager(working_dir)

        # Authenticated remote URL from VCS provider
        remote_url = gh.get_remote_url(repo_name)

        commit_msg = (
            "Initial commit [Agent OS iteration 1]"
            if iteration == 1
            else f"Fix iteration {iteration} [Agent OS]"
        )

        if iteration == 1:
            # ── Iteration 1: create remote repo (if needed), init local repo,
            #    commit on main, push main + feature branch, open PR

            # Create the remote repository first — idempotent: if it already
            # exists the VCS client will return an error we can safely ignore.
            if repo_name:
                create_result = gh.create_repo(repo_name)
                if create_result.success:
                    logger.info("Remote repo created: %s", repo_name)
                else:
                    err_lower = (create_result.error or "").lower()
                    if any(kw in err_lower for kw in ("already exists", "name already", "422", "409")):
                        logger.info("Remote repo already exists — continuing: %s", repo_name)
                    else:
                        errors.append(f"create_repo failed: {create_result.error}")
                        # non-fatal: attempt push anyway, the remote may still be reachable
            else:
                logger.warning("repo_name not configured — skipping create_repo")

            if not git.is_repo():
                r = git.init_repo()
                if not r.success:
                    errors.append(f"git init failed: {r.stderr}")
                    return errors

            git.set_user(_BOT_NAME, _BOT_EMAIL)
            git.add_remote("origin", remote_url)

            r = git.commit_all(commit_msg)
            if not r.success:
                errors.append(f"commit failed: {r.stderr}")
                return errors

            r = git.push_upstream("main")
            if not r.success:
                errors.append(f"push main failed: {r.stderr}")
            result.branch_pushed = "main"

            # Create + push feature branch
            feature_pushed = False
            r = git.create_and_checkout(feature_branch, "main")
            if r.success:
                r2 = git.push_upstream(feature_branch)
                if not r2.success:
                    errors.append(f"push feature branch failed: {r2.stderr}")
                else:
                    feature_pushed = True
            else:
                errors.append(f"create feature branch failed: {r.stderr}")

            # Open PR (only if feature branch was pushed successfully)
            if feature_pushed:
                pr_title = f"[Agent OS] Iteration {iteration} — initial implementation"
                pr_body = (
                    "Automated pull request created by Agent OS.\n\n"
                    f"**Iteration:** {iteration}\n"
                )
                pr_result = gh.create_pr(
                    title=pr_title,
                    head=feature_branch,
                    base="main",
                    body=pr_body,
                )
                if pr_result.success and pr_result.data:
                    result.pr_number = pr_result.data.get("number")
                    result.pr_url = pr_result.data.get("html_url", "")
                    logger.info("PR #%d created: %s", result.pr_number, result.pr_url)
                else:
                    errors.append(f"create_pr failed: {pr_result.error}")

        else:
            # ── Iteration 2+: commit on feature branch, push, resolve PR comments
            r = git.checkout(feature_branch)
            if not r.success:
                # Feature branch may not exist locally — create tracking
                r = git.create_and_checkout(feature_branch, f"origin/{feature_branch}")
                if not r.success:
                    errors.append(f"checkout feature branch failed: {r.stderr}")
                    return errors

            r = git.commit_all(commit_msg)
            if not r.success:
                errors.append(f"commit failed: {r.stderr}")
                return errors

            r = git.push_upstream(feature_branch)
            if not r.success:
                errors.append(f"push failed: {r.stderr}")
            result.branch_pushed = feature_branch

            # Resolve review comments on the PR
            if pr_number is not None:
                resolve_results = gh.resolve_all_pr_review_comments(pr_number)
                failed_resolutions = [r for r in resolve_results if not r.success]
                if failed_resolutions:
                    errors.append(
                        f"{len(failed_resolutions)} review comment(s) could not be resolved"
                    )
            else:
                logger.warning("pr_number not provided for iteration %d — skipping comment resolution", iteration)

        return errors

    # ── Helpers ───────────────────────────────────────────────────────────

    def _build_prompt(self, prompt_path: Path, iteration: int) -> str:
        """Prepend identity preamble and guardrails to the prompt file."""
        module_prompt = prompt_path.read_text(encoding="utf-8")
        parts: list[str] = []
        if self._identity_ctx:
            preamble = self._identity_ctx.build_preamble()
            if preamble:
                parts.append(preamble)
        # Inject current iteration number so Codex knows which rules apply
        parts.append(f"<!-- Agent OS: iteration={iteration} -->")
        parts.append(GUARDRAIL_PROMPT)
        parts.append(module_prompt)
        return "\n\n".join(parts)

    def _execute(
        self,
        prompt: str,
        working_dir: Path,
        *,
        on_stdout: Optional[Callable[[str], None]] = None,
        on_stderr: Optional[Callable[[str], None]] = None,
    ) -> CodexResult:
        return self._codex.execute(
            prompt=prompt,
            working_dir=working_dir,
            session_type=SessionType.CODE_GENERATOR,
            on_stdout=on_stdout,
            on_stderr=on_stderr,
        )
