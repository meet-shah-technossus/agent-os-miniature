"""Type checker wrapper — runs mypy and returns structured results."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess

from .schema import Severity, ToolResult, ValidationIssue

logger = logging.getLogger(__name__)

_TOOL = "type_checker"

# mypy output line pattern: file.py:10: error: Message  [error-code]
_LINE_RE = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+):\s*(?P<severity>error|warning|note):\s*(?P<message>.+?)(?:\s+\[(?P<code>[^\]]+)\])?$"
)


def run_type_checker(working_dir: str, file_paths: list[str] | None = None) -> ToolResult:
    """Run mypy on *working_dir* and return structured results."""
    mypy = shutil.which("mypy")
    if not mypy:
        return ToolResult(
            tool=_TOOL, passed=True, skipped=True,
            skip_reason="mypy not found on PATH",
        )

    target = file_paths or ["."]
    cmd = [
        mypy, "--no-color-output", "--no-error-summary",
        "--show-column-numbers", *target,
    ]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=working_dir, timeout=180,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            tool=_TOOL, passed=False,
            raw_output="mypy timed out after 180s",
            error_count=1,
        )

    issues: list[ValidationIssue] = []
    for line in proc.stdout.splitlines():
        m = _LINE_RE.match(line)
        if not m:
            continue
        sev_str = m.group("severity")
        if sev_str == "note":
            sev = Severity.INFO
        elif sev_str == "warning":
            sev = Severity.WARNING
        else:
            sev = Severity.ERROR
        issues.append(ValidationIssue(
            tool=_TOOL,
            file=m.group("file"),
            line=int(m.group("line")),
            code=m.group("code") or "",
            message=m.group("message"),
            severity=sev,
        ))

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
