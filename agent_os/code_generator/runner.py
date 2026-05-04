"""Code Generator runner — generates code from prompts via Codex CLI.

Reads the stamped prompt file, prepends guardrails, invokes Codex in the
project root, detects completion, and stores the summary.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ..codex.session import CodexResult, SessionType
from ..codex.wrapper import CodexWrapper
from ..config.schema import AgentOSConfig
from .completion import CompletionResult, CompletionStatus, consume_summary, detect_completion
from .guardrails import GUARDRAIL_PROMPT

from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class CodeGenResult:
    """Outcome of a code generation run."""
    completion: CompletionResult
    codex_result: CodexResult
    summary_text: str = ""
    retried: bool = False


class CodeGeneratorRunner:
    """Generate code for a single module iteration via Codex CLI."""

    def __init__(self, config: AgentOSConfig, identity_ctx=None) -> None:
        self._config = config
        self._identity_ctx = identity_ctx
        self._codex = CodexWrapper(
            timeout_seconds=config.codex.timeout_seconds,
            max_retries=0,  # We handle retry logic ourselves for partial completion
            openai_api_key=config.secrets.openai_api_key,
            project_root=config.project.root_path or ".",
            model_routing=config.codex.model_routing,
            default_model=config.codex.model,
        )

    def run(self, prompt_path: str | Path, working_dir: str | Path, on_stdout: Optional[Callable[[str], None]] = None, on_stderr: Optional[Callable[[str], None]] = None) -> CodeGenResult:
        """Execute code generation with one automatic retry on partial completion."""
        prompt_path = Path(prompt_path)
        working_dir = Path(working_dir) if working_dir else Path(".")

        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

        prompt_text = self._build_prompt(prompt_path)
        result = self._execute(prompt_text, working_dir, on_stdout=on_stdout, on_stderr=on_stderr)
        completion = detect_completion(
            result.exit_code, working_dir, result.timed_out
        )

        # Retry once on partial completion
        if completion.status == CompletionStatus.PARTIAL:
            logger.info("Partial completion detected — retrying once.")
            retry_prompt = (
                f"{prompt_text}\n\n"
                "# RETRY NOTICE\n"
                "The previous attempt was incomplete. "
                "Continue from where you left off and ensure summary.md "
                "is written with END marker when done.\n"
            )
            result = self._execute(retry_prompt, working_dir, on_stdout=on_stdout, on_stderr=on_stderr)
            completion = detect_completion(
                result.exit_code, working_dir, result.timed_out
            )
            summary = consume_summary(working_dir)
            return CodeGenResult(
                completion=completion,
                codex_result=result,
                summary_text=summary,
                retried=True,
            )

        summary = consume_summary(working_dir)
        return CodeGenResult(
            completion=completion,
            codex_result=result,
            summary_text=summary,
        )

    # ------------------------------------------------------------------

    def _build_prompt(self, prompt_path: Path) -> str:
        """Prepend identity context and guardrails to the module prompt."""
        module_prompt = prompt_path.read_text(encoding="utf-8")
        parts: list[str] = []
        if self._identity_ctx:
            preamble = self._identity_ctx.build_preamble()
            if preamble:
                parts.append(preamble)
        parts.append(GUARDRAIL_PROMPT)
        parts.append(module_prompt)
        return "\n\n".join(parts)

    def _execute(self, prompt: str, working_dir: Path, *, on_stdout: Optional[Callable[[str], None]] = None, on_stderr: Optional[Callable[[str], None]] = None) -> CodexResult:
        return self._codex.execute(
            prompt=prompt,
            working_dir=working_dir,
            session_type=SessionType.CODE_GENERATOR,
            on_stdout=on_stdout,
            on_stderr=on_stderr,
        )
