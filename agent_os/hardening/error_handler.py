"""Centralized error recovery — categorizes failures and selects recovery strategy."""

from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

from ..comms.bus import AgentCommBus
from ..comms.messages import ErrorAlertMessage

logger = logging.getLogger(__name__)


class ErrorCategory(str, Enum):
    CODEX_CRASH = "codex_crash"
    CODEX_TIMEOUT = "codex_timeout"
    PARTIAL_GENERATION = "partial_generation"
    VALIDATION_TOOL_ERROR = "validation_tool_error"
    GIT_CONFLICT = "git_conflict"
    NETWORK_ERROR = "network_error"
    INVALID_JSON = "invalid_json"
    BUDGET_EXCEEDED = "budget_exceeded"
    UNKNOWN = "unknown"


class RecoveryAction(str, Enum):
    RETRY = "retry"
    SKIP = "skip"
    ROLLBACK = "rollback"
    HITL_ESCALATE = "hitl_escalate"
    FAIL = "fail"


# Category → default recovery mapping
_DEFAULT_RECOVERY: dict[ErrorCategory, RecoveryAction] = {
    ErrorCategory.CODEX_CRASH: RecoveryAction.RETRY,
    ErrorCategory.CODEX_TIMEOUT: RecoveryAction.RETRY,
    ErrorCategory.PARTIAL_GENERATION: RecoveryAction.RETRY,
    ErrorCategory.VALIDATION_TOOL_ERROR: RecoveryAction.SKIP,
    ErrorCategory.GIT_CONFLICT: RecoveryAction.HITL_ESCALATE,
    ErrorCategory.NETWORK_ERROR: RecoveryAction.RETRY,
    ErrorCategory.INVALID_JSON: RecoveryAction.RETRY,
    ErrorCategory.BUDGET_EXCEEDED: RecoveryAction.HITL_ESCALATE,
    ErrorCategory.UNKNOWN: RecoveryAction.FAIL,
}


def classify_error(exc: Exception, context: str = "") -> ErrorCategory:
    """Categorize an exception into an ErrorCategory."""
    msg = str(exc).lower()
    ctx = context.lower()
    exc_type = type(exc).__name__.lower()

    if "timeout" in msg or "timed out" in msg:
        return ErrorCategory.CODEX_TIMEOUT
    if "json" in msg or "decode" in msg or "json" in exc_type:
        return ErrorCategory.INVALID_JSON
    if "merge" in ctx or "conflict" in msg:
        return ErrorCategory.GIT_CONFLICT
    if "network" in msg or "connection" in msg or "http" in msg:
        return ErrorCategory.NETWORK_ERROR
    if "codex" in ctx or "subprocess" in ctx:
        return ErrorCategory.CODEX_CRASH
    if "partial" in msg:
        return ErrorCategory.PARTIAL_GENERATION
    if "validation" in ctx:
        return ErrorCategory.VALIDATION_TOOL_ERROR
    if "budget" in msg or "budget" in ctx:
        return ErrorCategory.BUDGET_EXCEEDED

    return ErrorCategory.UNKNOWN


def get_recovery_action(category: ErrorCategory) -> RecoveryAction:
    """Return the default recovery action for an error category."""
    return _DEFAULT_RECOVERY.get(category, RecoveryAction.FAIL)


def publish_error(
    bus: Optional[AgentCommBus],
    category: ErrorCategory,
    action: RecoveryAction,
    module_id: Optional[str] = None,
    detail: str = "",
) -> None:
    """Broadcast an error alert on the communication bus."""
    if not bus:
        return
    bus.publish(ErrorAlertMessage(
        sender="error_handler",
        module_id=module_id,
        payload={
            "category": category.value,
            "recovery_action": action.value,
            "detail": detail[:500],
        },
    ))
