"""Output streaming helpers for Codex CLI subprocesses."""

from __future__ import annotations

import signal
import subprocess
from typing import Callable, Optional


def stream_pipe(
    pipe,
    line_buffer: list[str],
    callback: Optional[Callable[[str], None]],
) -> None:
    """Read lines from a pipe, store them, and optionally invoke a callback."""
    if pipe is None:
        return
    try:
        for line in pipe:
            stripped = line.rstrip("\n")
            line_buffer.append(stripped)
            if callback:
                try:
                    callback(stripped)
                except Exception:
                    pass  # Don't let callback errors break streaming
    except (ValueError, OSError):
        pass  # Pipe closed


def kill_process(proc: subprocess.Popen) -> None:
    """Gracefully terminate, then force-kill a process."""
    try:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    except (ProcessLookupError, OSError):
        pass  # Already dead
