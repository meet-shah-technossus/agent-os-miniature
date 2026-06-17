"""Unit tests for agent_os.logging_config."""
from __future__ import annotations

import json
import logging
import os
from unittest.mock import patch

import pytest

from agent_os.logging_config import (
    JSONFormatter,
    StepTimer,
    TextFormatter,
    configure_logging,
    correlation_id_var,
    get_correlation_id,
    new_correlation_id,
)


class TestCorrelationID:
    def test_new_correlation_id_returns_12_char_hex(self):
        cid = new_correlation_id()
        assert len(cid) == 12
        int(cid, 16)  # should not raise — valid hex

    def test_get_correlation_id_returns_current(self):
        token = correlation_id_var.set("test-123")
        try:
            assert get_correlation_id() == "test-123"
        finally:
            correlation_id_var.reset(token)

    def test_new_sets_and_returns(self):
        cid = new_correlation_id()
        assert get_correlation_id() == cid


class TestJSONFormatter:
    def test_format_produces_valid_json(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Hello %s",
            args=("world",),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["message"] == "Hello world"
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test.logger"
        assert "timestamp" in parsed

    def test_format_includes_correlation_id(self):
        token = correlation_id_var.set("abc123")
        try:
            formatter = JSONFormatter()
            record = logging.LogRecord(
                name="x", level=logging.INFO, pathname="", lineno=0,
                msg="msg", args=(), exc_info=None,
            )
            output = formatter.format(record)
            parsed = json.loads(output)
            assert parsed["correlation_id"] == "abc123"
        finally:
            correlation_id_var.reset(token)

    def test_format_includes_extra_fields(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="x", level=logging.INFO, pathname="", lineno=0,
            msg="step done", args=(), exc_info=None,
        )
        record.duration_ms = 42.5
        record.step = "code_generation"
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["duration_ms"] == 42.5
        assert parsed["step"] == "code_generation"


class TestTextFormatter:
    def test_format_contains_level_and_message(self):
        formatter = TextFormatter()
        record = logging.LogRecord(
            name="my.logger", level=logging.WARNING, pathname="", lineno=0,
            msg="oops", args=(), exc_info=None,
        )
        output = formatter.format(record)
        assert "WARNING" in output
        assert "oops" in output
        assert "my.logger" in output


class TestStepTimer:
    def test_measures_duration(self):
        import time
        with StepTimer("test_step") as timer:
            time.sleep(0.01)
        assert timer.step == "test_step"
        assert timer.duration_ms >= 5  # at least some time passed

    def test_zero_duration_no_work(self):
        with StepTimer("noop") as timer:
            pass
        assert timer.duration_ms >= 0


class TestConfigureLogging:
    def test_default_sets_info_level(self):
        with patch.dict(os.environ, {"LOG_FORMAT": "text", "LOG_LEVEL": "INFO"}, clear=False):
            configure_logging()
        root = logging.getLogger()
        assert root.level == logging.INFO
        assert len(root.handlers) >= 1

    def test_json_format_uses_json_formatter(self):
        with patch.dict(os.environ, {"LOG_FORMAT": "json", "LOG_LEVEL": "DEBUG"}, clear=False):
            configure_logging()
        root = logging.getLogger()
        assert any(isinstance(h.formatter, JSONFormatter) for h in root.handlers)

    def test_text_format_uses_text_formatter(self):
        with patch.dict(os.environ, {"LOG_FORMAT": "text"}, clear=False):
            configure_logging()
        root = logging.getLogger()
        assert any(isinstance(h.formatter, TextFormatter) for h in root.handlers)
