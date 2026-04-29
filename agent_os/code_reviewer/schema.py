"""Code review structured output schemas."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class IssueSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class IssueCategory(str, Enum):
    BUG = "bug"
    SECURITY = "security"
    PERFORMANCE = "performance"
    DESIGN = "design"
    STYLE = "style"
    TESTING = "testing"
    DOCUMENTATION = "documentation"
    OTHER = "other"


class FileAction(str, Enum):
    ACCEPT = "accept"
    PATCH = "patch"
    REGENERATE = "regenerate"


class ReviewIssue(BaseModel):
    """A single issue identified during code review."""

    id: str = ""
    file: str = ""
    line_start: int = 0
    line_end: int = 0
    severity: IssueSeverity = IssueSeverity.MEDIUM
    category: IssueCategory = IssueCategory.OTHER
    issue: str = ""
    suggested_fix: str = ""


class FileReviewResult(BaseModel):
    """Review result for a single file."""

    file_path: str
    action: FileAction = FileAction.ACCEPT
    issues: list[ReviewIssue] = Field(default_factory=list)
    comments: list[str] = Field(default_factory=list)


class ACVerification(BaseModel):
    """Pass/fail status for one acceptance criterion."""

    ac_id: str = ""
    description: str = ""
    passed: bool = False
    evidence: str = ""


class AreaScore(BaseModel):
    """Score for a review area (0-100)."""

    area: str
    score: int = 0
    notes: str = ""


class CodeReviewResult(BaseModel):
    """Full structured output from the Code Reviewer."""

    module_id: str
    iteration: int
    overall_status: str = "needs_work"  # "accepted" | "needs_work" | "rejected"
    convergence_score: int = Field(default=0, ge=0, le=100)
    files: list[FileReviewResult] = Field(default_factory=list)
    acceptance_criteria: list[ACVerification] = Field(default_factory=list)
    area_scores: list[AreaScore] = Field(default_factory=list)
    summary: str = ""
    blocking_issues: int = 0

    def compute_summary_fields(self) -> None:
        """Recompute blocking_issues from file issues."""
        self.blocking_issues = sum(
            1
            for f in self.files
            for i in f.issues
            if i.severity in (IssueSeverity.CRITICAL, IssueSeverity.HIGH)
        )
