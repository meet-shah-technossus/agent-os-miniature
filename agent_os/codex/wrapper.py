"""Wrapper for invoking Codex CLI as a subprocess with streaming output capture."""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Callable, Optional

from .session import CodexResult, CodexSession, SessionType
from .streaming import kill_process
from .cli_adapter import build_command, executable_name, UnsupportedToolError
from .executors import WindowsPipeExecutor, UnixPTYExecutor
from ..constants import DEFAULT_CODEX_TIMEOUT

_IS_WINDOWS = sys.platform == "win32"

logger = logging.getLogger(__name__)


class CodexWrapper:
    """Manages Codex CLI subprocess invocations with streaming output and timeout."""

    def __init__(
        self,
        timeout_seconds: int = DEFAULT_CODEX_TIMEOUT,
        max_retries: int = 2,
        openai_api_key: str = "",
        project_root: str = ".",
        model_routing: dict[str, str] | None = None,
        default_model: str = "",
        cli_routing: dict[str, str] | None = None,
        github_token: str = "",
    ) -> None:
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._openai_api_key = openai_api_key
        self._project_root = project_root
        self._model_routing = model_routing or {}
        self._default_model = default_model
        self._cli_routing = cli_routing or {}
        self._github_token = github_token
        self._active_sessions: dict[SessionType, CodexSession] = {}

    def execute(
        self,
        prompt: str,
        working_dir: str | Path,
        session_type: SessionType,
        on_stdout: Optional[Callable[[str], None]] = None,
        on_stderr: Optional[Callable[[str], None]] = None,
    ) -> CodexResult:
        """Execute a Codex CLI command with retry logic and exponential backoff."""
        from ..utils.retry import compute_backoff

        last_result = None
        for attempt in range(1, self._max_retries + 2):
            logger.info(
                "Codex exec attempt %d/%d for %s",
                attempt, self._max_retries + 1, session_type.value,
            )
            result = self._run_once(prompt, working_dir, session_type, on_stdout, on_stderr)
            last_result = result

            if result.exit_code == 0:
                logger.info(
                    "Codex exec succeeded for %s in %.1fs",
                    session_type.value,
                    result.duration_seconds,
                    extra={"duration_ms": round(result.duration_seconds * 1000, 1), "agent": session_type.value},
                )
                return result

            if result.timed_out:
                logger.warning("Codex exec timed out for %s (attempt %d)", session_type.value, attempt)
            else:
                logger.warning(
                    "Codex exec failed for %s with exit code %d (attempt %d)",
                    session_type.value, result.exit_code, attempt,
                )
                # Log the actual output so the error is visible in server logs
                if result.stdout:
                    for line in result.stdout.splitlines()[-30:]:
                        logger.warning("[codex output] %s", line)

            if attempt <= self._max_retries:
                backoff = compute_backoff(attempt - 1, base_delay=2.0, max_delay=30.0)
                logger.info("Retrying in %.1fs...", backoff)
                time.sleep(backoff)

        return last_result  # type: ignore[return-value]

    def _run_once(
        self,
        prompt: str,
        working_dir: str | Path,
        session_type: SessionType,
        on_stdout: Optional[Callable[[str], None]],
        on_stderr: Optional[Callable[[str], None]],
    ) -> CodexResult:
        """Single invocation of a CLI tool via platform-specific executor."""
        working_dir = Path(working_dir).resolve()
        if not working_dir.exists():
            working_dir.mkdir(parents=True, exist_ok=True)

        # Build command using the configured CLI tool for this agent
        tool = self._cli_routing.get(session_type.value, "codex")
        model = self._model_routing.get(session_type.value) or self._default_model
        start_time = time.monotonic()
        use_stdin_for_prompt = _IS_WINDOWS
        try:
            cmd = build_command(tool, model, prompt, working_dir=str(working_dir),
                                use_stdin=use_stdin_for_prompt)
        except UnsupportedToolError as exc:
            logger.error("Unsupported tool '%s' for %s: %s", tool, session_type.value, exc)
            return CodexResult(
                exit_code=-1, stdout="", stderr=str(exc),
                duration_seconds=time.monotonic() - start_time,
            )
        _exec_name = executable_name(tool)

        session = CodexSession(
            session_type=session_type,
            _on_stdout=on_stdout,
            _on_stderr=on_stderr,
        )
        self._active_sessions[session_type] = session

        try:
            from ..config.env import build_codex_env
            env = build_codex_env(self._openai_api_key, self._project_root)
            if self._github_token:
                env["GITHUB_TOKEN"] = self._github_token

            prompt_bytes = prompt.encode("utf-8") if use_stdin_for_prompt else None
            executor = WindowsPipeExecutor() if _IS_WINDOWS else UnixPTYExecutor()
            result = executor.execute(
                cmd=cmd,
                working_dir=working_dir,
                env=env,
                timeout=self._timeout,
                prompt_bytes=prompt_bytes,
                on_stdout=on_stdout,
                executable_name=_exec_name,
            )

            session.stdout_lines = result.stdout_lines
            return CodexResult(
                exit_code=result.exit_code,
                stdout="\n".join(result.stdout_lines),
                stderr="",
                timed_out=result.timed_out,
                duration_seconds=result.duration_seconds,
            )

        except FileNotFoundError:
            logger.error("'%s' CLI not found. Is it installed and on PATH?", _exec_name)
            return CodexResult(exit_code=-127, stdout="", stderr=f"{_exec_name}: command not found",
                               duration_seconds=time.monotonic() - start_time)
        except Exception as e:
            logger.exception("Unexpected error running %s CLI", _exec_name)
            return CodexResult(exit_code=-1, stdout="", stderr=str(e),
                               duration_seconds=time.monotonic() - start_time)
        finally:
            self._active_sessions.pop(session_type, None)

    def get_active_session(self, session_type: SessionType) -> Optional[CodexSession]:
        return self._active_sessions.get(session_type)

    def kill_session(self, session_type: SessionType) -> bool:
        session = self._active_sessions.get(session_type)
        if session and session.process:
            kill_process(session.process)
            self._active_sessions.pop(session_type, None)
            return True
        return False
