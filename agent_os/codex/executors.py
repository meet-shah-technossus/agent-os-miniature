"""Platform-specific subprocess executors — extracted from CodexWrapper (Phase 10.1).

Each executor encapsulates how to spawn and stream output from a subprocess
on a specific platform. CodexWrapper._run_once() selects the appropriate
executor based on the current OS.
"""
from __future__ import annotations

import contextlib
import logging
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..constants import PTY_COLS, PTY_ROWS
from .streaming import kill_process, stream_pty

_IS_WINDOWS = sys.platform == "win32"
if not _IS_WINDOWS:
    import fcntl
    import pty
    import struct
    import termios

logger = logging.getLogger(__name__)

# Patterns that indicate a fatal, unrecoverable codex tool-router error.
_FATAL_STDOUT_PATTERNS: tuple[str, ...] = (
    "failed to parse function arguments",
    "invalid type: sequence, expected a string",
    "invalid type: map, expected a string",
)


@dataclass
class ExecutionResult:
    """Result from a platform executor."""
    exit_code: int
    stdout_lines: list[str] = field(default_factory=list)
    timed_out: bool = False
    duration_seconds: float = 0.0


def _set_pty_size(fd: int, rows: int, cols: int) -> None:
    """Set the terminal size on a PTY file descriptor. Unix only."""
    if _IS_WINDOWS:
        return
    try:
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
    except OSError:
        logger.debug("PTY size set failed for fd=%d", fd, exc_info=True)


class WindowsPipeExecutor:
    """Execute a subprocess on Windows using pipes for output streaming."""

    def execute(
        self,
        cmd: list[str],
        working_dir: Path,
        env: dict[str, str],
        timeout: int,
        prompt_bytes: bytes | None,
        on_stdout: Callable[[str], None] | None,
        executable_name: str,
    ) -> ExecutionResult:
        start_time = time.monotonic()
        stdout_lines: list[str] = []
        win_cmd = ["cmd", "/c"] + cmd

        proc = subprocess.Popen(
            win_cmd,
            stdin=subprocess.PIPE if prompt_bytes else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(working_dir),
            env=env,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )

        logger.info("Started %s CLI (PID %d) via pipe", executable_name, proc.pid)

        # Writer thread: send prompt then close stdin
        if prompt_bytes:
            def _write_stdin() -> None:
                try:
                    proc.stdin.write(prompt_bytes)  # type: ignore[union-attr]
                    proc.stdin.close()              # type: ignore[union-attr]
                except (OSError, BrokenPipeError):
                    pass
            threading.Thread(target=_write_stdin, daemon=True).start()

        fatal_event = threading.Event()

        def _stream_bytes(output_pipe, line_buffer, callback):
            try:
                for raw in output_pipe:
                    if isinstance(raw, bytes):
                        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                    else:
                        line = str(raw).rstrip("\r\n")
                    line_buffer.append(line)
                    if callback:
                        with contextlib.suppress(Exception):
                            callback(line)
                    if any(p in line for p in _FATAL_STDOUT_PATTERNS):
                        if not fatal_event.is_set():
                            fatal_event.set()
                            logger.warning(
                                "%s fatal tool-router error detected — "
                                "aborting process %d early: %s",
                                executable_name, proc.pid, line.strip(),
                            )
                            kill_process(proc)
                        break
            except (ValueError, OSError):
                pass

        reader = threading.Thread(
            target=_stream_bytes,
            args=(proc.stdout, stdout_lines, on_stdout),
            daemon=True,
        )
        reader.start()

        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.warning("%s CLI (PID %d) timed out after %ds", executable_name, proc.pid, timeout)
            kill_process(proc)
            reader.join(timeout=5)
            return ExecutionResult(
                exit_code=-1,
                stdout_lines=stdout_lines,
                timed_out=True,
                duration_seconds=time.monotonic() - start_time,
            )

        reader.join(timeout=10)

        if fatal_event.is_set():
            return ExecutionResult(
                exit_code=1,
                stdout_lines=stdout_lines,
                timed_out=False,
                duration_seconds=time.monotonic() - start_time,
            )

        return ExecutionResult(
            exit_code=proc.returncode,
            stdout_lines=stdout_lines,
            timed_out=False,
            duration_seconds=time.monotonic() - start_time,
        )


class UnixPTYExecutor:
    """Execute a subprocess on Unix using a PTY for streaming."""

    def execute(
        self,
        cmd: list[str],
        working_dir: Path,
        env: dict[str, str],
        timeout: int,
        prompt_bytes: bytes | None,
        on_stdout: Callable[[str], None] | None,
        executable_name: str,
    ) -> ExecutionResult:
        start_time = time.monotonic()
        stdout_lines: list[str] = []

        env.setdefault("TERM", "xterm-256color")
        master_fd, slave_fd = pty.openpty()
        _set_pty_size(master_fd, PTY_ROWS, PTY_COLS)

        proc = subprocess.Popen(
            cmd,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=str(working_dir),
            env=env,
            close_fds=True,
            start_new_session=True,
        )
        os.close(slave_fd)

        logger.info("Started %s CLI (PID %d) via PTY", executable_name, proc.pid)

        pty_thread = threading.Thread(
            target=stream_pty,
            args=(master_fd, stdout_lines, on_stdout),
            daemon=True,
        )
        pty_thread.start()

        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.warning("%s CLI (PID %d) timed out after %ds", executable_name, proc.pid, timeout)
            kill_process(proc)
            pty_thread.join(timeout=5)
            if pty_thread.is_alive():
                logger.warning("PTY reader thread did not exit within 5s (PID %d)", proc.pid)
            return ExecutionResult(
                exit_code=-1,
                stdout_lines=stdout_lines,
                timed_out=True,
                duration_seconds=time.monotonic() - start_time,
            )
        finally:
            with contextlib.suppress(OSError):
                os.close(master_fd)

        pty_thread.join(timeout=10)
        if pty_thread.is_alive():
            logger.warning("PTY reader thread did not exit within 10s (PID %d)", proc.pid)

        return ExecutionResult(
            exit_code=proc.returncode,
            stdout_lines=stdout_lines,
            timed_out=False,
            duration_seconds=time.monotonic() - start_time,
        )
