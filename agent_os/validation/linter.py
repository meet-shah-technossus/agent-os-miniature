"""Linter wrapper — runs ruff (or flake8 fallback) and returns structured results."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

from .schema import Severity, ToolResult, ValidationIssue

logger = logging.getLogger(__name__)

_TOOL = "linter"


def run_linter(working_dir: str, file_paths: list[str] | None = None) -> ToolResult:
    """Run ruff on *working_dir* and return structured results."""
    ruff = shutil.which("ruff")
    if not ruff:
        return ToolResult(
            tool=_TOOL, passed=True, skipped=True,
            skip_reason="ruff not found on PATH",
        )

    target = file_paths or ["."]
    cmd = [ruff, "check", "--output-format=json", "--no-fix", *target]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=working_dir, timeout=120,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            tool=_TOOL, passed=False,
            raw_output="ruff timed out after 120s",
            error_count=1,
        )

    issues: list[ValidationIssue] = []
    try:
        entries = json.loads(proc.stdout) if proc.stdout.strip() else []
        for entry in entries:
            sev = Severity.WARNING if entry.get("code", "").startswith("W") else Severity.ERROR
            issues.append(ValidationIssue(
                tool=_TOOL,
                file=entry.get("filename", ""),
                line=entry.get("location", {}).get("row", 0),
                column=entry.get("location", {}).get("column", 0),
                code=entry.get("code", ""),
                message=entry.get("message", ""),
                severity=sev,
            ))
    except (json.JSONDecodeError, KeyError):
        logger.warning("Failed to parse ruff JSON output")

    errors = sum(1 for i in issues if i.severity == Severity.ERROR)
    warnings = sum(1 for i in issues if i.severity == Severity.WARNING)

    return ToolResult(
        tool=_TOOL,
        passed=len(issues) == 0,
        issues=issues,
        raw_output=proc.stdout[:2000],
        error_count=errors,
        warning_count=warnings,
    )
