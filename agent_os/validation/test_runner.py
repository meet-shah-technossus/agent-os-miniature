"""Test runner wrapper — runs pytest and returns structured results."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

from .schema import Severity, ToolResult, ValidationIssue

logger = logging.getLogger(__name__)

_TOOL = "test_runner"


def run_tests(working_dir: str) -> ToolResult:
    """Run pytest with JSON report and return structured results."""
    pytest_bin = shutil.which("pytest")
    if not pytest_bin:
        return ToolResult(
            tool=_TOOL, passed=True, skipped=True,
            skip_reason="pytest not found on PATH",
        )

    report_path = Path(working_dir) / ".pytest_report.json"
    cmd = [
        pytest_bin, "--tb=short", "-q",
        f"--json-report-file={report_path}",
        "--json-report",
    ]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=working_dir, timeout=300,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            tool=_TOOL, passed=False,
            raw_output="pytest timed out after 300s",
            error_count=1,
        )

    issues: list[ValidationIssue] = []

    # Try to parse JSON report if available
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            for test in report.get("tests", []):
                if test.get("outcome") == "failed":
                    nodeid = test.get("nodeid", "")
                    msg = test.get("call", {}).get("crash", {}).get("message", "test failed")
                    lineno = test.get("call", {}).get("crash", {}).get("lineno", 0)
                    filepath = test.get("call", {}).get("crash", {}).get("path", nodeid)
                    issues.append(ValidationIssue(
                        tool=_TOOL,
                        file=filepath,
                        line=lineno,
                        message=f"{nodeid}: {msg}",
                        severity=Severity.ERROR,
                    ))
        except (json.JSONDecodeError, KeyError):
            logger.warning("Failed to parse pytest JSON report")
        finally:
            report_path.unlink(missing_ok=True)
    elif proc.returncode != 0:
        # Fallback: no JSON report plugin, parse exit code
        issues.append(ValidationIssue(
            tool=_TOOL,
            message=f"pytest exited with code {proc.returncode}",
            severity=Severity.ERROR,
        ))

    errors = sum(1 for i in issues if i.severity == Severity.ERROR)

    return ToolResult(
        tool=_TOOL,
        passed=proc.returncode == 0,
        issues=issues,
        raw_output=proc.stdout[:2000],
        error_count=errors,
        warning_count=0,
    )
