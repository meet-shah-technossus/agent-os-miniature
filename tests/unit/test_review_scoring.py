"""Unit tests for code review scoring — ReviewJSON.compute_overall_score() and thresholds."""
from __future__ import annotations

import pytest

from agent_os.code_reviewer.schema import (
    ArchitectureIssue,
    GlobalComment,
    IssueSeverity,
    LineComment,
    ReviewJSON,
)
from agent_os.constants import (
    REVIEW_SCORE_APPROVED,
    REVIEW_SCORE_CONDITIONAL,
    REVIEW_SCORE_REJECTED,
)


# ---------------------------------------------------------------------------
# Score computation
# ---------------------------------------------------------------------------


class TestComputeOverallScore:
    def test_empty_checklist_returns_existing_score(self):
        r = ReviewJSON(overall_score=50)
        result = r.compute_overall_score()
        assert result == 50

    def test_computes_average_of_checklist_scores(self):
        r = ReviewJSON(checklist_scores={
            "code_correctness": 80,
            "readability": 90,
            "structure_design": 70,
            "performance": 60,
        })
        expected = (80 + 90 + 70 + 60) // 4
        result = r.compute_overall_score()
        assert result == expected
        assert r.overall_score == expected

    def test_all_perfect_scores(self):
        scores = {k: 100 for k in [
            "code_correctness", "readability", "structure_design", "performance",
            "security", "error_handling", "code_standards", "testing",
            "documentation", "maintainability", "dependencies", "logging",
            "version_control", "ui_ux", "overall_impact",
        ]}
        r = ReviewJSON(checklist_scores=scores)
        assert r.compute_overall_score() == 100

    def test_all_zero_scores(self):
        scores = {k: 0 for k in [
            "code_correctness", "readability", "structure_design", "performance",
            "security", "error_handling", "code_standards",
        ]}
        r = ReviewJSON(checklist_scores=scores)
        assert r.compute_overall_score() == 0

    def test_stores_result_in_overall_score_field(self):
        r = ReviewJSON(checklist_scores={"a": 80, "b": 60})
        r.compute_overall_score()
        assert r.overall_score == 70


# ---------------------------------------------------------------------------
# Score thresholds
# ---------------------------------------------------------------------------


class TestScoreThresholds:
    """Verify the constant thresholds match expectations."""

    def test_approved_threshold(self):
        assert REVIEW_SCORE_APPROVED == 80

    def test_conditional_threshold(self):
        assert REVIEW_SCORE_CONDITIONAL == 70

    def test_rejected_threshold(self):
        assert REVIEW_SCORE_REJECTED == 40

    def test_score_at_approved_boundary(self):
        r = ReviewJSON(overall_score=80)
        assert r.overall_score >= REVIEW_SCORE_APPROVED

    def test_score_below_approved(self):
        r = ReviewJSON(overall_score=79)
        assert r.overall_score < REVIEW_SCORE_APPROVED

    def test_score_in_conditional_range(self):
        r = ReviewJSON(overall_score=75)
        assert REVIEW_SCORE_CONDITIONAL <= r.overall_score < REVIEW_SCORE_APPROVED

    def test_score_below_rejected(self):
        r = ReviewJSON(overall_score=35)
        assert r.overall_score < REVIEW_SCORE_REJECTED


# ---------------------------------------------------------------------------
# Blocking issues detection
# ---------------------------------------------------------------------------


class TestHasBlockingIssues:
    def test_no_issues_returns_false(self):
        r = ReviewJSON()
        assert r.has_blocking_issues is False

    def test_critical_line_comment_blocks(self):
        r = ReviewJSON(line_comments=[
            LineComment(file="test.py", line=1, comment="Bug", severity=IssueSeverity.CRITICAL)
        ])
        assert r.has_blocking_issues is True

    def test_high_line_comment_blocks(self):
        r = ReviewJSON(line_comments=[
            LineComment(file="test.py", line=1, comment="Issue", severity=IssueSeverity.HIGH)
        ])
        assert r.has_blocking_issues is True

    def test_medium_line_comment_does_not_block(self):
        r = ReviewJSON(line_comments=[
            LineComment(file="test.py", line=1, comment="Nit", severity=IssueSeverity.MEDIUM)
        ])
        assert r.has_blocking_issues is False

    def test_critical_global_comment_blocks(self):
        r = ReviewJSON(global_comments=[
            GlobalComment(comment="Security flaw", severity=IssueSeverity.CRITICAL)
        ])
        assert r.has_blocking_issues is True

    def test_critical_architecture_issue_blocks(self):
        r = ReviewJSON(architecture_issues=[
            ArchitectureIssue(description="DB in route", severity=IssueSeverity.CRITICAL)
        ])
        assert r.has_blocking_issues is True

    def test_low_severity_everywhere_does_not_block(self):
        r = ReviewJSON(
            line_comments=[LineComment(file="a.py", line=1, comment="x", severity=IssueSeverity.LOW)],
            global_comments=[GlobalComment(comment="y", severity=IssueSeverity.LOW)],
            architecture_issues=[ArchitectureIssue(description="z", severity=IssueSeverity.LOW)],
        )
        assert r.has_blocking_issues is False


# ---------------------------------------------------------------------------
# Overall status logic
# ---------------------------------------------------------------------------


class TestOverallStatus:
    def test_default_status_is_needs_work(self):
        r = ReviewJSON()
        assert r.overall_status == "needs_work"

    def test_accepted_status(self):
        r = ReviewJSON(overall_status="accepted", overall_score=85)
        assert r.overall_status == "accepted"

    def test_rejected_status(self):
        r = ReviewJSON(overall_status="rejected", overall_score=20)
        assert r.overall_status == "rejected"
