"""Wrapper for invoking Codex CLI as a subprocess with streaming output capture."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .session import CodexResult, CodexSession, SessionType
from .streaming import kill_process, stream_pipe

logger = logging.getLogger(__name__)


class CodexWrapper:
    """Manages Codex CLI subprocess invocations with streaming output and timeout."""

    def __init__(
        self,
        timeout_seconds: int = 300,
        max_retries: int = 2,
        openai_api_key: str = "",
        project_root: str = ".",
        model_routing: dict[str, str] | None = None,
        default_model: str = "",
    ) -> None:
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._openai_api_key = openai_api_key
        self._project_root = project_root
        self._model_routing = model_routing or {}
        self._default_model = default_model
        self._active_sessions: dict[SessionType, CodexSession] = {}

    def execute(
        self,
        prompt: str,
        working_dir: str | Path,
        session_type: SessionType,
        on_stdout: Optional[Callable[[str], None]] = None,
        on_stderr: Optional[Callable[[str], None]] = None,
    ) -> CodexResult:
        """Execute a Codex CLI command with retry logic."""
        last_result = None
        for attempt in range(1, self._max_retries + 2):
            logger.info(
                "Codex exec attempt %d/%d for %s",
                attempt, self._max_retries + 1, session_type.value,
            )
            result = self._run_once(prompt, working_dir, session_type, on_stdout, on_stderr)
            last_result = result

            if result.exit_code == 0:
                return result

            if result.timed_out:
                logger.warning("Codex exec timed out for %s (attempt %d)", session_type.value, attempt)
            else:
                logger.warning(
                    "Codex exec failed for %s with exit code %d (attempt %d)",
                    session_type.value, result.exit_code, attempt,
                )

            if attempt <= self._max_retries:
                logger.info("Retrying...")

        return last_result  # type: ignore[return-value]

    def _run_once(
        self,
        prompt: str,
        working_dir: str | Path,
        session_type: SessionType,
        on_stdout: Optional[Callable[[str], None]],
        on_stderr: Optional[Callable[[str], None]],
    ) -> CodexResult:
        """Single invocation of codex exec."""
        working_dir = Path(working_dir).resolve()
        if not working_dir.exists():
            working_dir.mkdir(parents=True, exist_ok=True)

        cmd = ["codex", "exec", "--full-auto", "--skip-git-repo-check"]
        model = self._model_routing.get(session_type.value) or self._default_model
        if model:
            cmd.extend(["--model", model])
        cmd.append(prompt)
        session = CodexSession(
            session_type=session_type,
            _on_stdout=on_stdout,
            _on_stderr=on_stderr,
        )
        start_time = time.monotonic()

        try:
            from ..config.env import build_codex_env

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(working_dir),
                text=True,
                env=build_codex_env(self._openai_api_key, self._project_root),
            )
            session.process = proc
            session.pid = proc.pid
            self._active_sessions[session_type] = session

            logger.info("Started Codex CLI (PID %d) for %s", proc.pid, session_type.value)

            stdout_thread = threading.Thread(
                target=stream_pipe, args=(proc.stdout, session.stdout_lines, on_stdout),
                daemon=True,
            )
            stderr_thread = threading.Thread(
                target=stream_pipe, args=(proc.stderr, session.stderr_lines, on_stderr),
                daemon=True,
            )
            stdout_thread.start()
            stderr_thread.start()

            try:
                proc.wait(timeout=self._timeout)
            except subprocess.TimeoutExpired:
                logger.warning("Codex CLI (PID %d) timed out after %ds", proc.pid, self._timeout)
                kill_process(proc)
                stdout_thread.join(timeout=5)
                stderr_thread.join(timeout=5)
                return CodexResult(
                    exit_code=-1,
                    stdout="\n".join(session.stdout_lines),
                    stderr="\n".join(session.stderr_lines),
                    timed_out=True,
                    duration_seconds=time.monotonic() - start_time,
                )

            stdout_thread.join(timeout=10)
            stderr_thread.join(timeout=10)

            return CodexResult(
                exit_code=proc.returncode,
                stdout="\n".join(session.stdout_lines),
                stderr="\n".join(session.stderr_lines),
                timed_out=False,
                duration_seconds=time.monotonic() - start_time,
            )

        except FileNotFoundError:
            logger.error("'codex' CLI not found. Is it installed and on PATH?")
            return CodexResult(exit_code=-127, stdout="", stderr="codex: command not found",
                               duration_seconds=time.monotonic() - start_time)
        except Exception as e:
            logger.exception("Unexpected error running Codex CLI")
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
