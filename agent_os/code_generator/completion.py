"""Completion detection for Code Generator output.

Three-tier detection:
  1. Primary:   Process exit code (0 = success)
  2. Secondary: Check summary.md exists with END marker
  3. Fallback:  Exit 0 but no valid summary → partial completion
"""

from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class CompletionStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class CompletionResult:
    """Result of completion detection."""

    __slots__ = ("status", "summary_text", "reason")

    def __init__(
        self, status: CompletionStatus, summary_text: str = "", reason: str = ""
    ) -> None:
        self.status = status
        self.summary_text = summary_text
        self.reason = reason


def detect_completion(
    exit_code: int,
    working_dir: str | Path,
    timed_out: bool = False,
) -> CompletionResult:
    """Determine completion status using the three-tier strategy."""
    working_dir = Path(working_dir)
    summary_path = working_dir / "summary.md"

    # Tier 1: process exit code
    if timed_out:
        return CompletionResult(
            CompletionStatus.FAILED, reason="Codex CLI timed out."
        )

    if exit_code != 0:
        return CompletionResult(
            CompletionStatus.FAILED,
            reason=f"Codex CLI exited with code {exit_code}.",
        )

    # Tier 1.5: verify source files were actually created in working_dir
    _IGNORE = {".venv", "__pycache__", ".git", "node_modules", ".mypy_cache", ".pytest_cache"}
    source_files = [
        f for f in working_dir.rglob("*")
        if f.is_file()
        and not any(part in _IGNORE for part in f.parts)
        and f.name != "summary.md"
    ]
    if not source_files:
        logger.warning(
            "Codex exited 0 but no source files were created in %s — "
            "likely sandbox permission issue (read-only mode).",
            working_dir,
        )
        return CompletionResult(
            CompletionStatus.FAILED,
            reason=(
                "Codex CLI did not create any source files. "
                "The sandbox may be running in read-only mode. "
                "Ensure --full-auto flag is used."
            ),
        )

    # Tier 2: summary.md with END marker
    if summary_path.exists():
        text = summary_path.read_text(encoding="utf-8").strip()
        if text.endswith("END"):
            logger.info("Completion detected: summary.md with END marker.")
            return CompletionResult(CompletionStatus.COMPLETE, summary_text=text)
        # summary exists but missing END — treat as partial
        logger.warning("summary.md exists but missing END marker.")
        return CompletionResult(
            CompletionStatus.PARTIAL,
            summary_text=text,
            reason="summary.md missing END marker.",
        )

    # Tier 3: exit 0 but no summary → partial
    logger.warning("Codex exited 0 but no summary.md found → partial completion.")
    return CompletionResult(
        CompletionStatus.PARTIAL,
        reason="Process exited 0 but no summary.md found.",
    )


def consume_summary(working_dir: str | Path) -> str:
    """Read and delete summary.md, returning its text."""
    path = Path(working_dir) / "summary.md"
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8").strip()
    path.unlink()
    return text
