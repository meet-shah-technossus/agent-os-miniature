"""Validation runner — orchestrates all validation tools and aggregates results."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable, Optional

from ..comms.bus import AgentCommBus
from ..comms.messages import ValidationResultMessage
from ..config.schema import ValidationConfig
from .dependency_checker import run_dependency_check
from .linter import run_linter
from .schema import ToolResult, ValidationResult
from .security import run_security_scan
from .test_runner import run_tests
from .type_checker import run_type_checker

logger = logging.getLogger(__name__)


class ValidationRunner:
    """Runs enabled validators, streams per-tool results on the Comm Bus,
    and returns an aggregated ValidationResult."""

    def __init__(
        self,
        config: ValidationConfig,
        bus: Optional[AgentCommBus] = None,
    ) -> None:
        self._config = config
        self._bus = bus

    def run(
        self,
        working_dir: str,
        module_id: str,
        iteration: int,
        file_paths: list[str] | None = None,
    ) -> ValidationResult:
        result = ValidationResult(module_id=module_id, iteration=iteration)

        runners: list[tuple[str, Callable[[], ToolResult]]] = []

        if self._config.lint:
            runners.append(("lint", lambda: run_linter(working_dir, file_paths)))
        if self._config.type_check:
            runners.append(("type_check", lambda: run_type_checker(working_dir, file_paths)))
        if self._config.tests:
            runners.append(("tests", lambda: run_tests(working_dir)))
        if self._config.security_scan:
            runners.append(("security", lambda: run_security_scan(working_dir, file_paths)))

        # Dependency check always runs (no toggle)
        runners.append(("deps", lambda: run_dependency_check(working_dir)))

        for label, fn in runners:
            logger.info("Running validator: %s", label)
            try:
                tool_result = fn()
            except Exception as exc:
                logger.warning("Validator %s crashed: %s", label, exc)
                tool_result = ToolResult(
                    tool=label,
                    passed=False,
                    skipped=True,
                    skip_reason=f"Tool error: {str(exc)[:200]}",
                )
            result.tools.append(tool_result)
            self._publish_tool_result(tool_result, module_id, iteration)

        result.compute_summary()
        return result

    def _publish_tool_result(
        self,
        tool_result: ToolResult,
        module_id: str,
        iteration: int,
    ) -> None:
        """Publish a per-tool result on the Comm Bus (streaming)."""
        if not self._bus:
            return
        self._bus.publish(ValidationResultMessage(
            sender="validation_runner",
            module_id=module_id,
            iteration=iteration,
            payload={
                "tool": tool_result.tool,
                "passed": tool_result.passed,
                "skipped": tool_result.skipped,
                "error_count": tool_result.error_count,
                "warning_count": tool_result.warning_count,
            },
        ))


def store_validation_result(result: ValidationResult) -> Path:
    """Persist aggregated validation JSON to disk."""
    out_dir = Path(f"data/validations/{result.module_id}")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"iteration-{result.iteration}.json"
    out_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return out_path
