"""Git operations strategies — extracted from CodeGeneratorRunner (Phase 9.1).

Each strategy encapsulates iteration-specific git + VCS logic so that
CodeGeneratorRunner._git_operations() becomes a thin dispatch (~20 lines).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ..constants import GIT_AUTHOR_NAME, DEFAULT_GITIGNORE_PATTERNS
from ..git_ops.manager import GitOpsManager
from ..vcs.base import VCSClient

logger = logging.getLogger(__name__)

_BOT_NAME = GIT_AUTHOR_NAME
_BOT_EMAIL = "agent-os@noreply.github.com"


@dataclass
class GitOpsContext:
    """All parameters needed by a git ops strategy."""
    working_dir: Path
    iteration: int
    pr_number: Optional[int]
    feature_branch: str
    repo_name: str
    vcs_client: VCSClient
    config: Any  # AgentOSConfig
    # Fork-mode extras
    story_context: dict = field(default_factory=dict)
    tool_label: str = "AI tool"


@dataclass
class GitOpsResult:
    """All return values from a git ops strategy."""
    errors: list[str] = field(default_factory=list)
    pr_number: Optional[int] = None
    pr_url: str = ""
    branch_pushed: str = ""


def _sanitise_before_commit(working_dir: Path, git: GitOpsManager) -> None:
    """Ensure generated artefacts (venv, caches) are excluded before commit."""
    gitignore_path = working_dir / ".gitignore"
    try:
        existing = gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else ""
        missing = [e for e in DEFAULT_GITIGNORE_PATTERNS if e.rstrip("/") not in existing]
        if missing:
            with gitignore_path.open("a", encoding="utf-8") as fh:
                fh.write("\n" + "\n".join(missing) + "\n")
            logger.debug("[sanitise] Added %d entries to .gitignore", len(missing))
    except OSError:
        logger.debug("[sanitise] Could not update .gitignore", exc_info=True)

    _CACHED_PATTERNS = (
        ".venv", "venv", "env", "__pycache__", "node_modules",
        ".eggs", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    )
    for pattern in _CACHED_PATTERNS:
        r = git._run("rm", "--cached", "-r", "--ignore-unmatch", pattern)
        if r and getattr(r, "stdout", "") and r.stdout.strip():
            logger.info("[sanitise] Removed %s from git index (--cached)", pattern)


# ── Standard mode strategies ──────────────────────────────────────────────────


class StandardFirstIterationGitOps:
    """Standard mode, iteration 1: init repo, push orphan main, open PR."""

    def execute(self, ctx: GitOpsContext) -> GitOpsResult:
        result = GitOpsResult()
        gh = ctx.vcs_client
        git = GitOpsManager(ctx.working_dir)
        remote_url = gh.get_remote_url(ctx.repo_name)
        feature_branch = ctx.feature_branch
        iteration = ctx.iteration

        _actor = getattr(gh, "_owner", "unknown")
        _actor_repo = getattr(gh, "_repo", ctx.repo_name) or ctx.repo_name

        # Create remote repo (idempotent)
        if ctx.repo_name:
            create_result = gh.create_repo(ctx.repo_name)
            if create_result.success:
                logger.info("[actor: %s] Remote repo created: %s/%s", _actor, _actor, ctx.repo_name)
            else:
                err_lower = (create_result.error or "").lower()
                if not any(kw in err_lower for kw in ("already exists", "name already", "422", "409")):
                    result.errors.append(f"create_repo failed: {create_result.error}")
        else:
            logger.warning("[actor: %s] repo_name not configured — skipping create_repo", _actor)

        if not git.is_repo():
            r = git.init_repo()
            if not r.success:
                result.errors.append(f"git init failed: {r.stderr}")
                return result

        git.set_user(_BOT_NAME, _BOT_EMAIL)
        git.add_remote("origin", remote_url)

        # Create orphan baseline on main
        _ORPHAN_TMP = "__agent_os_baseline_tmp__"
        r = git._run("checkout", "--orphan", _ORPHAN_TMP)
        if not r.success:
            logger.warning("[actor: %s] --orphan failed (%s), falling back to checkout -b main", _actor, r.stderr)
            git._run("checkout", "-b", "main")
        else:
            git._run("rm", "--cached", "-rq", "--ignore-unmatch", ".")
            r_c = git._run("commit", "--allow-empty", "-m", "chore: initial project baseline [Agent OS]")
            if r_c.success:
                if git.branch_exists("main"):
                    git._run("branch", "-D", "main")
                git._run("branch", "-m", _ORPHAN_TMP, "main")
                logger.info("[actor: %s] Created fresh orphan baseline on main", _actor)
            else:
                git._run("checkout", "main" if git.branch_exists("main") else "-b main")
                git._run("branch", "-D", _ORPHAN_TMP)
                logger.warning("[actor: %s] Orphan commit failed; continuing on existing main: %s", _actor, r_c.stderr)

        # Push main
        logger.info("[actor: %s] Pushing orphan baseline main to %s/%s", _actor, _actor, _actor_repo)
        r = git.push_upstream("main")
        if not r.success:
            r = git.push("main", force=True)
            if not r.success:
                result.errors.append(f"push main failed: {r.stderr}")
        result.branch_pushed = "main"

        # Create/update feature branch and commit all generated files
        feature_pushed = False
        if git.branch_exists(feature_branch):
            git.checkout(feature_branch)
            git._run("reset", "--mixed", "main")
            logger.info("[actor: %s] Reset existing '%s' to new orphan main baseline", _actor, feature_branch)
        else:
            r = git._run("checkout", "-b", feature_branch, "main")
            if not r.success:
                result.errors.append(f"create feature branch failed: {r.stderr}")

        if not result.errors:
            commit_msg = f"Initial commit [Agent OS iteration {iteration}]"
            _sanitise_before_commit(ctx.working_dir, git)
            r_commit = git.commit_all(commit_msg)
            if not r_commit.success:
                result.errors.append(f"commit on {feature_branch} failed: {r_commit.stderr}")
            elif r_commit.stdout == "nothing to commit":
                result.errors.append(
                    f"commit on {feature_branch} produced no changes — "
                    "Codex may not have written any files to disk"
                )
            else:
                logger.info("[actor: %s] Pushing feature branch '%s' to %s/%s", _actor, feature_branch, _actor, _actor_repo)
                r2 = git.push_upstream(feature_branch)
                if not r2.success:
                    logger.warning("[actor: %s] Normal push of '%s' failed (%s) — retrying with --force", _actor, feature_branch, r2.stderr)
                    r2 = git.push(feature_branch, force=True)
                if not r2.success:
                    result.errors.append(f"push feature branch failed: {r2.stderr}")
                else:
                    feature_pushed = True

        # Open PR
        if feature_pushed:
            pr_title = f"[Agent OS] Iteration {iteration} — initial implementation"
            pr_body = (
                "Automated pull request created by Agent OS.\n\n"
                f"**Iteration:** {iteration}\n"
            )
            logger.info("[actor: %s] Creating PR: '%s' → main in %s/%s", _actor, feature_branch, _actor, _actor_repo)
            pr_result = gh.create_pr(title=pr_title, head=feature_branch, base="main", body=pr_body)
            if pr_result.success and pr_result.data:
                result.pr_number = pr_result.data.get("number")
                result.pr_url = pr_result.data.get("html_url", "")
                logger.info("[actor: %s] PR #%d created: %s", _actor, result.pr_number, result.pr_url)
            else:
                result.errors.append(f"create_pr failed: {pr_result.error}")

        return result


class StandardSubsequentIterationGitOps:
    """Standard mode, iteration 2+: commit on feature branch, push, resolve comments."""

    def execute(self, ctx: GitOpsContext) -> GitOpsResult:
        result = GitOpsResult()
        gh = ctx.vcs_client
        git = GitOpsManager(ctx.working_dir)
        feature_branch = ctx.feature_branch

        r = git.checkout(feature_branch)
        if not r.success:
            r = git.create_and_checkout(feature_branch, f"origin/{feature_branch}")
            if not r.success:
                result.errors.append(f"checkout feature branch failed: {r.stderr}")
                return result

        commit_msg = f"Fix iteration {ctx.iteration} [Agent OS]"
        r = git.commit_all(commit_msg)
        if not r.success:
            result.errors.append(f"commit failed: {r.stderr}")
            return result

        r = git.push_upstream(feature_branch)
        if not r.success:
            result.errors.append(f"push failed: {r.stderr}")
        result.branch_pushed = feature_branch

        if ctx.pr_number is not None:
            resolve_results = gh.resolve_all_pr_review_comments(ctx.pr_number)
            failed_resolutions = [r for r in resolve_results if not r.success]
            if failed_resolutions:
                result.errors.append(f"{len(failed_resolutions)} review comment(s) could not be resolved")
        else:
            logger.warning("pr_number not provided for iteration %d — skipping comment resolution", ctx.iteration)

        return result


# ── Fork mode strategies (GitHub Review) ──────────────────────────────────────


class ForkModeFirstIterationGitOps:
    """Fork mode (GHR), iteration 1: stash, reset main, branch, commit, push, open PR."""

    def execute(self, ctx: GitOpsContext) -> GitOpsResult:
        result = GitOpsResult()
        gh = ctx.vcs_client
        git = GitOpsManager(ctx.working_dir)
        feature_branch = ctx.feature_branch
        story_ctx = ctx.story_context
        story_id = story_ctx.get("story_id", "")
        story_title = story_ctx.get("title", "")
        story_acs: list[str] = story_ctx.get("acceptance_criteria", [])
        repo_name = ctx.repo_name
        tool_label = ctx.tool_label

        remote_url = gh.get_remote_url(repo_name)
        git.add_remote("origin", remote_url)
        git.set_user(_BOT_NAME, _BOT_EMAIL)

        # Stash Codex's generated changes
        _has_codex_changes = git.has_changes()
        _stashed = False
        if _has_codex_changes:
            stash_r = git._run("stash", "push", "--include-untracked", "-m", "codex-output")
            _stashed = stash_r.success and "No local changes" not in stash_r.stdout

        # Fetch + reset to latest main
        git.fetch("origin", "main")
        if git.branch_exists("main"):
            git.checkout("main")
            git._run("reset", "--hard", "origin/main")
        else:
            r = git._run("checkout", "-b", "main", "origin/main")
            if not r.success:
                result.errors.append(f"checkout main failed: {r.stderr}")
                return result

        # Create / checkout story branch
        if git.branch_exists(feature_branch):
            git.checkout(feature_branch)
            git._run("rebase", "main")
        else:
            r = git.create_and_checkout(feature_branch, "main")
            if not r.success:
                result.errors.append(f"create branch {feature_branch} failed: {r.stderr}")
                return result

        # Restore Codex's generated changes
        if _stashed:
            pop_r = git._run("stash", "pop")
            if not pop_r.success:
                logger.warning("[GHR] stash pop failed — trying stash apply: %s", pop_r.stderr)
                git._run("stash", "apply")

        # Commit
        commit_msg = (
            f"feat({feature_branch}): AI-generated implementation"
            if not story_id
            else f"feat({story_id}): {story_title or 'AI-generated implementation'}"
        )
        _sanitise_before_commit(ctx.working_dir, git)
        commit_r = git.commit_all(commit_msg)
        _nothing_committed = "nothing to commit" in (commit_r.stdout or "")
        if _nothing_committed:
            logger.warning("[GHR] commit_all returned 'nothing to commit' for story %s iter 1 "
                           "— %s may not have written any files", story_id, tool_label)
            existing_pr = gh.find_open_pr(feature_branch)
            if existing_pr:
                result.pr_number = existing_pr
                logger.info("[GHR] Nothing new to commit but PR #%d already exists — proceeding", existing_pr)
                return result
            result.errors.append(
                f"{tool_label} produced no file changes — nothing to commit. "
                "The prompt may need to be more specific or the model changed."
            )
            return result

        # Push story branch
        r = git.push_upstream(feature_branch)
        if not r.success:
            r = git.push(feature_branch, force=True)
        if not r.success:
            result.errors.append(f"push {feature_branch} failed: {r.stderr}")
            return result
        result.branch_pushed = feature_branch

        # Open PR
        acs_lines = "\n".join(f"- [ ] {ac}" for ac in story_acs) if story_acs else ""
        pr_title = (
            f"[Story {story_id}] {story_title}"
            if story_id and story_title
            else f"[Agent OS] {feature_branch}"
        )
        pr_body = (
            f"## {story_title}\n\n"
            f"Automated pull request generated by Agent OS.\n\n"
            + (f"### Acceptance Criteria\n{acs_lines}\n" if acs_lines else "")
        )
        pr_res = gh.create_pr(title=pr_title, head=feature_branch, base="main", body=pr_body)
        if pr_res.success and pr_res.data:
            result.pr_number = pr_res.data.get("number")
            result.pr_url = pr_res.data.get("html_url", "")
            logger.info("[GHR] Created PR #%d for story %s", result.pr_number, story_id)
        else:
            existing = gh.find_open_pr(feature_branch)
            if existing:
                result.pr_number = existing
                logger.info("[GHR] Reusing existing PR #%d for %s", existing, feature_branch)
            else:
                result.errors.append(f"create PR failed: {pr_res.error}")

        return result


class ForkModeSubsequentIterationGitOps:
    """Fork mode (GHR), iteration 2+: checkout story branch, commit, push, resolve comments."""

    def execute(self, ctx: GitOpsContext) -> GitOpsResult:
        result = GitOpsResult()
        gh = ctx.vcs_client
        git = GitOpsManager(ctx.working_dir)
        feature_branch = ctx.feature_branch
        story_id = ctx.story_context.get("story_id", "")
        repo_name = ctx.repo_name

        remote_url = gh.get_remote_url(repo_name)
        git.add_remote("origin", remote_url)
        git.set_user(_BOT_NAME, _BOT_EMAIL)

        git.fetch("origin", feature_branch)
        r = git.checkout(feature_branch)
        if not r.success:
            result.errors.append(f"checkout {feature_branch} failed: {r.stderr}")
            return result

        commit_msg = f"fix({story_id or feature_branch}): address review comments (iter {ctx.iteration})"
        _sanitise_before_commit(ctx.working_dir, git)
        git.commit_all(commit_msg)

        r = git.push(feature_branch)
        if not r.success:
            r = git.push(feature_branch, force=True)
        if not r.success:
            result.errors.append(f"push {feature_branch} iter{ctx.iteration} failed: {r.stderr}")
        result.branch_pushed = feature_branch
        result.pr_number = ctx.pr_number

        # Resolve PR review comments
        if ctx.pr_number:
            try:
                gh.resolve_all_pr_review_comments(ctx.pr_number)
                logger.info("[GHR] Resolved review comments on PR #%d", ctx.pr_number)
            except Exception:
                logger.debug("[GHR] resolve_all_pr_review_comments raised", exc_info=True)

        return result
