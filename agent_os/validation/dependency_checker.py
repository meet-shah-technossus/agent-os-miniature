"""Dependency checker — verifies that project dependencies install cleanly."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from .schema import Severity, ToolResult, ValidationIssue

logger = logging.getLogger(__name__)

_TOOL = "dependency_checker"


def run_dependency_check(working_dir: str) -> ToolResult:
    """Dry-run pip install of a requirements.txt if present."""
    pip = shutil.which("pip")
    if not pip:
        return ToolResult(
            tool=_TOOL, passed=True, skipped=True,
            skip_reason="pip not found on PATH",
        )

    req_file = Path(working_dir) / "requirements.txt"
    if not req_file.exists():
        return ToolResult(
            tool=_TOOL, passed=True, skipped=True,
            skip_reason="No requirements.txt found",
        )

    cmd = [pip, "install", "--dry-run", "-r", str(req_file)]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=working_dir, timeout=120,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            tool=_TOOL, passed=False,
            raw_output="pip dry-run timed out after 120s",
            error_count=1,
        )

    issues: list[ValidationIssue] = []
    if proc.returncode != 0:
        issues.append(ValidationIssue(
            tool=_TOOL,
            file="requirements.txt",
            message=proc.stderr.strip()[:500] if proc.stderr else "pip install failed",
            severity=Severity.ERROR,
        ))

    return ToolResult(
        tool=_TOOL,
        passed=proc.returncode == 0,
        issues=issues,
        raw_output=(proc.stdout + proc.stderr)[:2000],
        error_count=len(issues),
        warning_count=0,
    )
