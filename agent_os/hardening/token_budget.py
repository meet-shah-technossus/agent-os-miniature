"""Token budget tracker — per-module budget enforcement with alerts."""

from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

from ..comms.bus import AgentCommBus
from ..comms.messages import ErrorAlertMessage, PipelineEventMessage
from ..config.schema import BudgetConfig
from ..storage.iteration_repo import IterationRepository

logger = logging.getLogger(__name__)


class BudgetStatus(str, Enum):
    OK = "ok"
    WARNING = "warning"
    EXCEEDED = "exceeded"


class TokenBudgetTracker:
    """Tracks token usage per module and enforces budget limits.

    Reads cumulative usage from the iterations table and compares
    against the configured per-module budget.
    """

    def __init__(
        self,
        config: BudgetConfig,
        iter_repo: IterationRepository,
        bus: Optional[AgentCommBus] = None,
    ) -> None:
        self._config = config
        self._iter_repo = iter_repo
        self._bus = bus

    def module_usage(self, module_id: str) -> int:
        """Total tokens consumed across all iterations for a module."""
        iters = self._iter_repo.get_for_module(module_id)
        return sum(it.token_usage for it in iters)

    def module_cost(self, module_id: str) -> float:
        """Estimated cost for a module based on token usage."""
        usage = self.module_usage(module_id)
        return (usage / 1000.0) * self._config.cost_per_1k_tokens

    def check_budget(self, module_id: str) -> BudgetStatus:
        """Check if the module is within budget.

        Returns OK, WARNING (>=alert_threshold_pct), or EXCEEDED (>=100%).
        """
        if self._config.token_budget_per_module <= 0:
            return BudgetStatus.OK

        usage = self.module_usage(module_id)
        pct = (usage / self._config.token_budget_per_module) * 100

        if pct >= 100:
            return BudgetStatus.EXCEEDED
        if pct >= self._config.alert_threshold_pct:
            return BudgetStatus.WARNING
        return BudgetStatus.OK

    def record_usage(self, module_id: str, iteration: int, tokens: int) -> BudgetStatus:
        """Record token usage for an iteration and return updated budget status.

        Updates the iteration record in the database and publishes alerts
        on the communication bus when thresholds are crossed.
        """
        record = self._iter_repo.get(module_id, iteration)
        if record:
            record.token_usage = tokens
            self._iter_repo.update(record)

        status = self.check_budget(module_id)

        if status == BudgetStatus.WARNING:
            self._publish_alert(module_id, "budget_warning", tokens)
        elif status == BudgetStatus.EXCEEDED:
            self._publish_alert(module_id, "budget_exceeded", tokens)

        return status

    def should_pause(self, module_id: str) -> bool:
        """Return True if the module has exceeded its budget and pause is enabled."""
        if not self._config.pause_at_limit:
            return False
        return self.check_budget(module_id) == BudgetStatus.EXCEEDED

    def get_summary(self, module_id: str) -> dict:
        """Return a summary dict suitable for API responses."""
        usage = self.module_usage(module_id)
        budget = self._config.token_budget_per_module
        pct = (usage / budget * 100) if budget > 0 else 0
        return {
            "module_id": module_id,
            "tokens_used": usage,
            "token_budget": budget,
            "usage_pct": round(pct, 1),
            "cost": round(self.module_cost(module_id), 4),
            "status": self.check_budget(module_id).value,
        }

    def _publish_alert(self, module_id: str, event: str, tokens: int) -> None:
        if not self._bus:
            return
        self._bus.publish(ErrorAlertMessage(
            sender="token_budget",
            module_id=module_id,
            payload={
                "event": event,
                "tokens_used": self.module_usage(module_id),
                "budget": self._config.token_budget_per_module,
                "iteration_tokens": tokens,
            },
        ))
