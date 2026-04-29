"""Validation result schemas — structured output from each validation tool."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ValidationIssue(BaseModel):
    """A single issue found by a validation tool."""

    tool: str
    file: str = ""
    line: int = 0
    column: int = 0
    code: str = ""
    message: str = ""
    severity: Severity = Severity.ERROR


class ToolResult(BaseModel):
    """Output from a single validation tool."""

    tool: str
    passed: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
    raw_output: str = ""
    skipped: bool = False
    skip_reason: str = ""
    error_count: int = 0
    warning_count: int = 0


class ValidationResult(BaseModel):
    """Aggregated validation output across all tools."""

    module_id: str
    iteration: int
    tools: list[ToolResult] = Field(default_factory=list)
    all_passed: bool = False
    total_errors: int = 0
    total_warnings: int = 0

    def compute_summary(self) -> None:
        """Recompute aggregate fields from individual tool results."""
        self.total_errors = sum(t.error_count for t in self.tools)
        self.total_warnings = sum(t.warning_count for t in self.tools)
        self.all_passed = all(t.passed or t.skipped for t in self.tools)
