"""Decision logic — convergence rules for the iteration loop."""

from __future__ import annotations

from typing import Any

from ..config.schema import ConvergenceRule


def decide_iteration(
    review_json: dict[str, Any],
    iteration: int,
    max_iterations: int,
    convergence_rule: ConvergenceRule,
) -> str:
    """Decide whether to accept the module, iterate, or escalate.

    Returns one of: "MODULE_COMPLETE", "HITL_4_MAX_ITERATIONS", "ITERATE".
    """
    overall = review_json.get("overall_status", "")

    if overall == "accepted":
        return "MODULE_COMPLETE"

    if iteration > max_iterations:
        return "HITL_4_MAX_ITERATIONS"

    files = review_json.get("files", [])

    if convergence_rule == ConvergenceRule.ALL_ACCEPTED:
        all_accepted = all(f.get("action") == "accept" for f in files)
        if all_accepted:
            return "MODULE_COMPLETE"

    elif convergence_rule == ConvergenceRule.NO_HIGH_SEVERITY:
        has_blocking = _has_severity(files, {"critical", "high"})
        if not has_blocking:
            return "MODULE_COMPLETE"

    elif convergence_rule == ConvergenceRule.NO_CRITICAL:
        has_critical = _has_severity(files, {"critical"})
        if not has_critical:
            return "MODULE_COMPLETE"

    return "ITERATE"


def _has_severity(files: list[dict], severities: set[str]) -> bool:
    """Check if any file has issues at the given severity levels."""
    for f in files:
        for issue in f.get("issues", []):
            if issue.get("severity") in severities:
                return True
    return False
