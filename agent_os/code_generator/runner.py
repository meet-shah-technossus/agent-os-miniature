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

import contextlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..codex.cli_adapter import API_TOOLS
from ..codex.session import CodexResult, SessionType
from ..codex.wrapper import CodexWrapper
from ..config.schema import AgentOSConfig
from ..constants import DEFAULT_GITIGNORE_PATTERNS, GIT_AUTHOR_NAME
from ..git_ops.manager import GitOpsManager
from ..vcs.base import VCSClient
from .completion import CompletionResult, CompletionStatus, detect_completion
from .guardrails import GUARDRAIL_PROMPT

logger = logging.getLogger(__name__)

_BOT_NAME = GIT_AUTHOR_NAME
_BOT_EMAIL = "agent-os@noreply.github.com"


@dataclass
class CodeGenResult:
    """Outcome of a code-generation run."""
    completion: CompletionResult
    codex_result: CodexResult
    summary_text: str = ""
    retried: bool = False
    # Git / PR metadata (populated when vcs=github)
    pr_number: int | None = None
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
        codex_wrapper: Any | None = None,
        git_ops: Any | None = None,
    ) -> None:
        self._config = config
        self._identity_ctx = identity_ctx
        self._vcs_client = vcs_client
        self._git_ops = git_ops

        # Allow dependency injection for testing; default to real CodexWrapper.
        if codex_wrapper is not None:
            self._codex = codex_wrapper
        else:
            self._codex = CodexWrapper(
                timeout_seconds=config.codex.timeout_seconds,
                max_retries=0,
                openai_api_key=config.secrets.openai_api_key,
                project_root=config.project.root_path or ".",
                model_routing=config.codex.model_routing,
                default_model=config.codex.model,
                cli_routing=config.codex.cli_routing,
                github_token=(
                    getattr(getattr(config, "ai_tools", None), "copilot", None) and
                    config.ai_tools.copilot.api_key
                ) or config.secrets.github_token or "",
            )

    # ── Public interface ───────────────────────────────────────────────────

    def run(
        self,
        prompt_path: str | Path,
        working_dir: str | Path,
        iteration: int = 1,
        pr_number: int | None = None,
        on_stdout: Callable[[str], None] | None = None,
        on_stderr: Callable[[str], None] | None = None,
        story_context: dict | None = None,
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
            story_context: Optional dict with story metadata for GitHub Review
                         mode (``story_id``, ``title``, ``acceptance_criteria``).
                         Ignored in standard mode.

        Returns:
            CodeGenResult with completion, CI, and git/PR metadata.
        """
        prompt_path = Path(prompt_path)
        working_dir = Path(working_dir) if working_dir else Path(".")

        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

        # Determine the actual CLI tool being used (for labelling + api-tool file writing)
        _cli_tool_name = self._codex._cli_routing.get(SessionType.CODE_GENERATOR.value, "codex")
        _tool_label = _cli_tool_name.capitalize() if _cli_tool_name not in ("codex",) else "Codex"
        try:
            from ..codex.cli_adapter import TOOL_LABELS
            _tool_label = TOOL_LABELS.get(_cli_tool_name, _tool_label)
        except ImportError:
            pass

        prompt_text = self._build_prompt(prompt_path, iteration, api_tool=_cli_tool_name in API_TOOLS)
        codex_result = self._execute(prompt_text, working_dir, on_stdout=on_stdout, on_stderr=on_stderr)
        completion = detect_completion(codex_result.exit_code, working_dir, codex_result.timed_out)

        # For API-backed tools (copilot, gemini, …) the subprocess only streams
        # text to stdout — it has no agentic file-write capability.  Parse the
        # LLM's response for FILE blocks and write them to the working directory.
        if completion.status == CompletionStatus.COMPLETE and _cli_tool_name in API_TOOLS:
            _file_write_errors = self._apply_llm_file_output(
                codex_result.stdout, working_dir, on_stdout
            )
            if _file_write_errors:
                for _e in _file_write_errors:
                    logger.warning("[%s] file-write error: %s", _tool_label, _e)

        result = CodeGenResult(
            completion=completion,
            codex_result=codex_result,
            summary_text="",
            retried=False,
        )

        # Only run git ops when the tool succeeded
        if completion.status == CompletionStatus.COMPLETE:
            if getattr(self._config, "pipeline_mode", "standard") == "github_review":
                git_errors = self._git_operations_fork_mode(
                    working_dir, iteration, pr_number, result,
                    story_context=story_context or {},
                    tool_label=_tool_label,
                )
            else:
                git_errors = self._git_operations(working_dir, iteration, pr_number, result)
            result.git_errors = git_errors

        return result

    # ── Git / GitHub operations (fork mode — GitHub Review) ───────────────────

    # ── API-tool file output parser ─────────────────────────────────────────

    _FILE_BLOCK_RE = None  # kept for backward compat if tests reference it

    def _apply_llm_file_output(
        self,
        stdout: str,
        working_dir: Path,
        emit: Callable[[str], None] | None = None,
    ) -> list[str]:
        """Delegates to file_ops.apply_llm_file_output."""
        from .file_ops import apply_llm_file_output
        return apply_llm_file_output(stdout, working_dir, emit)

    def _git_operations_fork_mode(
        self,
        working_dir: Path,
        iteration: int,
        pr_number: int | None,
        result: CodeGenResult,
        story_context: dict | None = None,
        tool_label: str = "AI tool",
    ) -> list[str]:
        """Fork-aware git ops — delegates to strategy classes."""
        from .git_strategies import (
            ForkModeFirstIterationGitOps,
            ForkModeSubsequentIterationGitOps,
            GitOpsContext,
        )

        cfg = self._config
        ctx = story_context or {}
        story_id = ctx.get("story_id", "")
        feature_branch = (
            getattr(cfg.project, "feature_branch", None) or f"story-{story_id or 'unknown'}"
        )
        repo_name = getattr(cfg.project, "repo_name", None) or ""

        gh: VCSClient | None = self._vcs_client
        if gh is None:
            from ..vcs.factory import make_vcs_client
            gh = make_vcs_client(cfg)
        if gh is None:
            logger.info("[GHR] VCS credentials not configured — skipping git ops")
            return []
        if repo_name and hasattr(gh, "for_repo") and repo_name != getattr(gh, "_repo", ""):
            gh = gh.for_repo(repo_name)

        ops_ctx = GitOpsContext(
            working_dir=working_dir,
            iteration=iteration,
            pr_number=pr_number,
            feature_branch=feature_branch,
            repo_name=repo_name,
            vcs_client=gh,
            config=cfg,
            story_context=ctx,
            tool_label=tool_label,
        )

        if iteration == 1:
            strategy = ForkModeFirstIterationGitOps()
        else:
            strategy = ForkModeSubsequentIterationGitOps()

        git_result = strategy.execute(ops_ctx)
        result.pr_number = git_result.pr_number
        result.pr_url = git_result.pr_url
        result.branch_pushed = git_result.branch_pushed
        return git_result.errors

    # ── Pre-commit sanitisation ────────────────────────────────────────────

    _GITIGNORE_ENTRIES: tuple[str, ...] = DEFAULT_GITIGNORE_PATTERNS

    def _sanitise_before_commit(self, working_dir: Path, git: GitOpsManager) -> None:
        """Delegates to git_strategies._sanitise_before_commit."""
        from .git_strategies import _sanitise_before_commit
        _sanitise_before_commit(working_dir, git)

    # ── Git / GitHub operations ────────────────────────────────────────────

    def _git_operations(
        self,
        working_dir: Path,
        iteration: int,
        pr_number: int | None,
        result: CodeGenResult,
    ) -> list[str]:
        """Standard-mode git ops — delegates to strategy classes."""
        import re as _re

        from .git_strategies import (
            GitOpsContext,
            StandardFirstIterationGitOps,
            StandardSubsequentIterationGitOps,
        )

        cfg = self._config
        feature_branch = (
            getattr(cfg.project, "feature_branch", None)
            or getattr(getattr(cfg, "github", None), "feature_branch", None)
            or "agent-os/dev"
        )
        repo_name = getattr(cfg.project, "repo_name", None) or ""
        if not repo_name:
            project_name = getattr(cfg.project, "name", "") or ""
            if project_name:
                repo_name = _re.sub(r"[^a-z0-9]+", "-", project_name.lower()).strip("-")
                with contextlib.suppress(Exception):
                    cfg.project.repo_name = repo_name
            else:
                repo_name = getattr(getattr(cfg, "github", None), "repo", None) or ""

        gh: VCSClient | None = self._vcs_client
        if gh is None:
            from ..vcs.factory import make_vcs_client
            gh = make_vcs_client(cfg)
        if gh is None:
            logger.info("VCS credentials not configured — skipping git operations")
            return []
        if repo_name and hasattr(gh, "for_repo") and repo_name != getattr(gh, "_repo", ""):
            gh = gh.for_repo(repo_name)

        ops_ctx = GitOpsContext(
            working_dir=working_dir,
            iteration=iteration,
            pr_number=pr_number,
            feature_branch=feature_branch,
            repo_name=repo_name,
            vcs_client=gh,
            config=cfg,
        )

        if iteration == 1:
            strategy = StandardFirstIterationGitOps()
        else:
            strategy = StandardSubsequentIterationGitOps()

        git_result = strategy.execute(ops_ctx)
        result.pr_number = git_result.pr_number
        result.pr_url = git_result.pr_url
        result.branch_pushed = git_result.branch_pushed
        return git_result.errors

    # ── Helpers ───────────────────────────────────────────────────────────

    _API_TOOL_FILE_FORMAT_INSTRUCTIONS = """
## FILE OUTPUT FORMAT — REQUIRED
This tool streams its output directly; it does NOT have automatic file-write
capability.  You MUST output every file you create or modify using EXACTLY
this block format (one block per file):

### FILE: relative/path/from/project/root/filename.ext
```
full file content here
```

Rules:
- The path is relative to the project root — no leading slash.
- Put the ENTIRE file content inside the code fence, not just the changed lines.
- After all FILE blocks you may include a brief plain-text summary.
- Do NOT use any other format for outputting file contents.
"""

    def _build_prompt(self, prompt_path: Path, iteration: int,
                      api_tool: bool = False) -> str:
        """Prepend identity preamble and guardrails to the prompt file."""
        module_prompt = prompt_path.read_text(encoding="utf-8")
        parts: list[str] = []
        if self._identity_ctx:
            preamble = self._identity_ctx.build_preamble()
            if preamble:
                parts.append(preamble)
        # Inject current iteration number so the tool knows which rules apply
        parts.append(f"<!-- Agent OS: iteration={iteration} -->")
        parts.append(GUARDRAIL_PROMPT)
        if api_tool:
            parts.append(self._API_TOOL_FILE_FORMAT_INSTRUCTIONS)
        parts.append(module_prompt)
        return "\n\n".join(parts)

    def _execute(
        self,
        prompt: str,
        working_dir: Path,
        *,
        on_stdout: Callable[[str], None] | None = None,
        on_stderr: Callable[[str], None] | None = None,
    ) -> CodexResult:
        return self._codex.execute(
            prompt=prompt,
            working_dir=working_dir,
            session_type=SessionType.CODE_GENERATOR,
            on_stdout=on_stdout,
            on_stderr=on_stderr,
        )
