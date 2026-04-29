"""Security scanner wrapper — runs bandit and returns structured results."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess

from .schema import Severity, ToolResult, ValidationIssue

logger = logging.getLogger(__name__)

_TOOL = "security"

_BANDIT_SEVERITY_MAP = {
    "HIGH": Severity.ERROR,
    "MEDIUM": Severity.WARNING,
    "LOW": Severity.INFO,
}


def run_security_scan(working_dir: str, file_paths: list[str] | None = None) -> ToolResult:
    """Run bandit on *working_dir* and return structured results."""
    bandit = shutil.which("bandit")
    if not bandit:
        return ToolResult(
            tool=_TOOL, passed=True, skipped=True,
            skip_reason="bandit not found on PATH",
        )

    target = file_paths or ["."]
    cmd = [bandit, "-r", "-f", "json", *target]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=working_dir, timeout=120,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            tool=_TOOL, passed=False,
            raw_output="bandit timed out after 120s",
            error_count=1,
        )

    issues: list[ValidationIssue] = []
    try:
        data = json.loads(proc.stdout) if proc.stdout.strip() else {}
        for result in data.get("results", []):
            sev = _BANDIT_SEVERITY_MAP.get(
                result.get("issue_severity", ""), Severity.WARNING,
            )
            issues.append(ValidationIssue(
                tool=_TOOL,
                file=result.get("filename", ""),
                line=result.get("line_number", 0),
                code=result.get("test_id", ""),
                message=result.get("issue_text", ""),
                severity=sev,
            ))
    except (json.JSONDecodeError, KeyError):
        logger.warning("Failed to parse bandit JSON output")

    errors = sum(1 for i in issues if i.severity == Severity.ERROR)
    warnings = sum(1 for i in issues if i.severity == Severity.WARNING)

    return ToolResult(
        tool=_TOOL,
        passed=errors == 0,
        issues=issues,
        raw_output=proc.stdout[:2000],
        error_count=errors,
        warning_count=warnings,
    )
