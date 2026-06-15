"""Unit tests for agent_os.code_generator.completion — CompletionStatus detection."""
from __future__ import annotations

import pytest

from agent_os.code_generator.completion import (
    CompletionResult,
    CompletionStatus,
    detect_completion,
)


# ---------------------------------------------------------------------------
# Exit code 0 → COMPLETE
# ---------------------------------------------------------------------------


class TestSuccessfulCompletion:
    def test_exit_zero_returns_complete(self, tmp_path):
        result = detect_completion(exit_code=0, working_dir=str(tmp_path))
        assert result.status == CompletionStatus.COMPLETE

    def test_exit_zero_has_empty_reason(self, tmp_path):
        result = detect_completion(exit_code=0, working_dir=str(tmp_path))
        assert result.reason == ""


# ---------------------------------------------------------------------------
# Non-zero exit codes → FAILED
# ---------------------------------------------------------------------------


class TestFailedCompletion:
    @pytest.mark.parametrize("code", [1, 2, 127, 128, 255])
    def test_nonzero_exit_returns_failed(self, tmp_path, code):
        result = detect_completion(exit_code=code, working_dir=str(tmp_path))
        assert result.status == CompletionStatus.FAILED

    def test_nonzero_exit_mentions_code_in_reason(self, tmp_path):
        result = detect_completion(exit_code=42, working_dir=str(tmp_path))
        assert "42" in result.reason

    def test_negative_exit_code_returns_failed(self, tmp_path):
        result = detect_completion(exit_code=-1, working_dir=str(tmp_path))
        assert result.status == CompletionStatus.FAILED


# ---------------------------------------------------------------------------
# Timeout → FAILED
# ---------------------------------------------------------------------------


class TestTimeoutCompletion:
    def test_timed_out_returns_failed(self, tmp_path):
        result = detect_completion(exit_code=0, working_dir=str(tmp_path), timed_out=True)
        assert result.status == CompletionStatus.FAILED

    def test_timed_out_reason_mentions_timeout(self, tmp_path):
        result = detect_completion(exit_code=0, working_dir=str(tmp_path), timed_out=True)
        assert "timed out" in result.reason.lower()

    def test_timed_out_takes_priority_over_exit_zero(self, tmp_path):
        # Even though exit code is 0, timeout should force FAILED
        result = detect_completion(exit_code=0, working_dir=str(tmp_path), timed_out=True)
        assert result.status == CompletionStatus.FAILED


# ---------------------------------------------------------------------------
# CompletionResult dataclass
# ---------------------------------------------------------------------------


class TestCompletionResult:
    def test_attributes_set_correctly(self):
        r = CompletionResult(CompletionStatus.COMPLETE, summary_text="All good", reason="")
        assert r.status == CompletionStatus.COMPLETE
        assert r.summary_text == "All good"
        assert r.reason == ""

    def test_default_empty_strings(self):
        r = CompletionResult(CompletionStatus.FAILED)
        assert r.summary_text == ""
        assert r.reason == ""


# ---------------------------------------------------------------------------
# CompletionStatus enum values
# ---------------------------------------------------------------------------


class TestCompletionStatusEnum:
    def test_complete_value(self):
        assert CompletionStatus.COMPLETE == "complete"

    def test_partial_value(self):
        assert CompletionStatus.PARTIAL == "partial"

    def test_failed_value(self):
        assert CompletionStatus.FAILED == "failed"
