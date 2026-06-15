"""Codex CLI session tracking."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class SessionType(str, Enum):
    PROMPT_GENERATOR = "PROMPT_GENERATOR"
    CODE_GENERATOR = "CODE_GENERATOR"
    CODE_REVIEWER = "CODE_REVIEWER"


@dataclass
class CodexResult:
    """Result from a Codex CLI invocation."""
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    duration_seconds: float = 0.0


@dataclass
class CodexSession:
    """Tracks a running Codex CLI session."""
    session_type: SessionType
    pid: int | None = None
    process: subprocess.Popen | None = None
    stdout_lines: list[str] = field(default_factory=list)
    stderr_lines: list[str] = field(default_factory=list)
    _on_stdout: Callable[[str], None] | None = None
    _on_stderr: Callable[[str], None] | None = None
