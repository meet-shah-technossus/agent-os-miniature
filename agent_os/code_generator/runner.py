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
            or ""
        )
        # Auto-derive repo slug from project name when repo_name is not set
        if not repo_name:
            import re as _re
            project_name = getattr(cfg.project, "name", "") or ""
            if project_name:
                repo_name = _re.sub(r"[^a-z0-9]+", "-", project_name.lower()).strip("-")
                # Persist so subsequent iterations use the same repo
                try:
                    cfg.project.repo_name = repo_name
                except Exception:
                    pass
            else:
                repo_name = (
                    getattr(getattr(cfg, "github", None), "repo", None) or ""
                )

        # Resolve VCS client: use injected one, or build via factory
        gh: VCSClient | None = self._vcs_client
        if gh is None:
            from ..vcs.factory import make_vcs_client
            gh = make_vcs_client(cfg)

        if gh is None:
            logger.info("VCS credentials not configured — skipping git operations")
            return []

        # Re-bind VCS client to the actual project repo so create_pr targets
        # the right repository (not the default config.github.repo value).
        if repo_name and hasattr(gh, "for_repo") and repo_name != getattr(gh, "_repo", ""):
            gh = gh.for_repo(repo_name)

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
            #    push an EMPTY baseline commit to main, commit all generated
            #    files on the feature branch, then open PR (feature → main).
            #
            #    IMPORTANT: generated files must NOT land on main here.
            #    If main and the feature branch share the same commit GitHub
            #    raises 422 "Validation Failed" (no diff) when creating the PR.

            _actor = getattr(gh, "_owner", "unknown")
            _actor_repo = getattr(gh, "_repo", repo_name) or repo_name

            # Create the remote repository first — idempotent.
            if repo_name:
                create_result = gh.create_repo(repo_name)
                if create_result.success:
                    logger.info(
                        "[actor: %s] Remote repo created: %s/%s",
                        _actor, _actor, repo_name,
                    )
                else:
                    err_lower = (create_result.error or "").lower()
                    if any(kw in err_lower for kw in ("already exists", "name already", "422", "409")):
                        logger.info(
                            "[actor: %s] Remote repo already exists — continuing: %s/%s",
                            _actor, _actor, repo_name,
                        )
                    else:
                        errors.append(f"create_repo failed: {create_result.error}")
                        # non-fatal: attempt push anyway
            else:
                logger.warning("[actor: %s] repo_name not configured — skipping create_repo", _actor)

            if not git.is_repo():
                r = git.init_repo()
                if not r.success:
                    errors.append(f"git init failed: {r.stderr}")
                    return errors

            git.set_user(_BOT_NAME, _BOT_EMAIL)
            logger.info("[actor: %s] Git identity set to '%s <%s>'", _actor, _BOT_NAME, _BOT_EMAIL)
            git.add_remote("origin", remote_url)

            # ── Create an ORPHAN baseline commit on main ──────────────────────
            # Using --orphan guarantees main has no connection to any prior
            # history.  Without this, if a previous run committed generated
            # files to main and then branched dev from that commit, dev's
            # entire history is already reachable from main → zero diff →
            # GitHub 422 "No commits between main and dev".
            #
            # Flow:
            #   1. checkout --orphan <temp>   (new root, index copied from HEAD)
            #   2. rm --cached -r .           (clear the index; keep working tree)
            #   3. commit --allow-empty       (fresh root commit — truly empty)
            #   4. rename temp → main         (replace any prior main)
            #   5. force-push main            (GitHub main = clean orphan root)
            #   6. checkout/create dev from main  (dev starts at orphan root)
            #   7. reset --mixed main         (re-base dev if it already existed)
            #   8. commit_all on dev          (all generated files land here)
            #   9. force-push dev             (dev ahead of main → real diff)
            #  10. create PR                  (succeeds every time)

            _ORPHAN_TMP = "__agent_os_baseline_tmp__"

            # Step 1: create orphan branch
            r = git._run("checkout", "--orphan", _ORPHAN_TMP)
            if not r.success:
                # git init may have left us in an unborn state — try creating main directly
                logger.warning("[actor: %s] --orphan failed (%s), falling back to checkout -b main", _actor, r.stderr)
                git._run("checkout", "-b", "main")
            else:
                # Step 2: clear the index (ignore errors on an empty index)
                git._run("rm", "--cached", "-rq", "--ignore-unmatch", ".")
                # Step 3: empty root commit
                r_c = git._run("commit", "--allow-empty", "-m", "chore: initial project baseline [Agent OS]")
                if r_c.success:
                    # Step 4: replace main with this fresh orphan
                    if git.branch_exists("main"):
                        git._run("branch", "-D", "main")
                    git._run("branch", "-m", _ORPHAN_TMP, "main")
                    logger.info("[actor: %s] Created fresh orphan baseline on main", _actor)
                else:
                    # Unlikely fallback — clean up and carry on
                    git._run("checkout", "main" if git.branch_exists("main") else "-b main")
                    git._run("branch", "-D", _ORPHAN_TMP)
                    logger.warning("[actor: %s] Orphan commit failed; continuing on existing main: %s", _actor, r_c.stderr)

            # Step 5: push main to GitHub (force required — history replaced)
            logger.info("[actor: %s] Pushing orphan baseline main to %s/%s", _actor, _actor, _actor_repo)
            r = git.push_upstream("main")
            if not r.success:
                r = git.push("main", force=True)
                if not r.success:
                    errors.append(f"push main failed: {r.stderr}")
            result.branch_pushed = "main"

            # Steps 6-9: create/update feature branch then commit all generated files.
            feature_pushed = False
            if git.branch_exists(feature_branch):
                # Branch exists from a prior run — just check it out…
                git.checkout(feature_branch)
                # …then reset its pointer (and index) to the new orphan main so
                # dev has no prior commits. Working tree is preserved, so all
                # Codex-generated files remain on disk as unstaged changes.
                git._run("reset", "--mixed", "main")
                logger.info("[actor: %s] Reset existing '%s' to new orphan main baseline", _actor, feature_branch)
            else:
                # Fresh branch — create from the new orphan main
                r = git._run("checkout", "-b", feature_branch, "main")
                if not r.success:
                    errors.append(f"create feature branch failed: {r.stderr}")

            if not errors:
                r_commit = git.commit_all(commit_msg)
                if not r_commit.success:
                    errors.append(f"commit on {feature_branch} failed: {r_commit.stderr}")
                elif r_commit.stdout == "nothing to commit":
                    # Extremely unusual: Codex generated no files or all were gitignored
                    errors.append(
                        f"commit on {feature_branch} produced no changes — "
                        "Codex may not have written any files to disk"
                    )
                else:
                    logger.info(
                        "[actor: %s] Pushing feature branch '%s' to %s/%s",
                        _actor, feature_branch, _actor, _actor_repo,
                    )
                    r2 = git.push_upstream(feature_branch)
                    if not r2.success:
                        # Remote branch has diverged — force-overwrite with new history
                        logger.warning(
                            "[actor: %s] Normal push of '%s' failed (%s) — retrying with --force",
                            _actor, feature_branch, r2.stderr,
                        )
                        r2 = git.push(feature_branch, force=True)
                    if not r2.success:
                        errors.append(f"push feature branch failed: {r2.stderr}")
                    else:
                        feature_pushed = True

            # Open PR (only if feature branch was pushed and has a diff from main)
            if feature_pushed:
                pr_title = f"[Agent OS] Iteration {iteration} — initial implementation"
                pr_body = (
                    "Automated pull request created by Agent OS.\n\n"
                    f"**Iteration:** {iteration}\n"
                )
                logger.info(
                    "[actor: %s] Creating PR: '%s' → main in %s/%s",
                    _actor, feature_branch, _actor, _actor_repo,
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
                    logger.info(
                        "[actor: %s] PR #%d created: %s",
                        _actor, result.pr_number, result.pr_url,
                    )
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
