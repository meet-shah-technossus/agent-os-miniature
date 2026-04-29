"""Main orchestrator engine — the central brain of Agent OS.

Owns the main loop, dispatches to handlers, manages state transitions.
All step logic lives in handlers.py. CLI logic lives in cli.py.
"""

from __future__ import annotations

import logging
from typing import Optional

import threading

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..comms.bus import AgentCommBus
from ..config.schema import AgentOSConfig
from ..hardening.error_handler import (
    RecoveryAction,
    classify_error,
    get_recovery_action,
    publish_error,
)
from ..hardening.rollback import RollbackManager
from ..storage.database import Database
from ..storage.models import ModuleStatus, PipelineState, PipelineStatus
from .context import HandlerContext
from .events import EventBus, PipelineEvent
from .handlers import HANDLER_REGISTRY
from .state import StateManager

logger = logging.getLogger(__name__)
console = Console()

# HITL gate → next state mapping
_GATE_TRANSITIONS: dict[PipelineStatus, PipelineStatus] = {
    PipelineStatus.HITL_1_MODULE_REVIEW: PipelineStatus.NEXT_MODULE,
    PipelineStatus.HITL_2_PROMPT_REVIEW: PipelineStatus.CODE_GENERATION,
    PipelineStatus.HITL_3_REVIEW_DECISION: PipelineStatus.DECISION,
    PipelineStatus.HITL_4_MAX_ITERATIONS: PipelineStatus.NEXT_MODULE,
    PipelineStatus.HITL_5_PR_REVIEW: PipelineStatus.INTEGRATION_TEST,
}


class Orchestrator:
    """Autonomous SDLC pipeline orchestrator."""

    def __init__(self, config: AgentOSConfig) -> None:
        self.config = config
        self.db = Database(config.storage.db_path)
        self.db.connect()
        self.state_mgr = StateManager(self.db)
        self.events = EventBus()
        self.bus = AgentCommBus()
        self.ctx = HandlerContext(
            state_mgr=self.state_mgr,
            db=self.db,
            config=config,
            bus=self.bus,
        )
        self._rollback: Optional[RollbackManager] = None
        self._pause_requested = threading.Event()

        # Wire state transitions to event bus
        self.state_mgr.on_transition(self._on_state_transition)

    def _on_state_transition(
        self,
        old_status: PipelineStatus,
        new_status: PipelineStatus,
        state: PipelineState,
    ) -> None:
        self.events.emit(
            PipelineEvent(
                old_status=old_status,
                new_status=new_status,
                module_id=state.current_module_id,
                iteration=state.current_iteration,
            )
        )

    # --- Main loop ---

    def run(self) -> None:
        """Run the pipeline from current state to completion (or HITL pause)."""
        self._pause_requested.clear()
        state = self.state_mgr.state
        if state.pipeline_status != PipelineStatus.IDLE:
            console.print(f"[yellow]Resuming from state: {state.pipeline_status.value}[/yellow]")
        else:
            console.print(Panel("Agent OS — Pipeline Starting", style="bold blue"))
        self._run_loop()

    def _run_loop(self) -> None:
        """Execute state machine steps until paused (HITL), complete, or pause requested."""
        while True:
            # Check for user-requested pause between steps
            if self._pause_requested.is_set():
                console.print("[yellow]Pipeline paused by user.[/yellow]")
                break

            status = self.state_mgr.current_status

            if status == PipelineStatus.PIPELINE_COMPLETE:
                console.print("[bold green]Pipeline complete![/bold green]")
                break

            if status == PipelineStatus.FAILED:
                console.print("[bold red]Pipeline failed. Reset with --reset to restart.[/bold red]")
                break

            if self.state_mgr.is_hitl_gate():
                if self.config.orchestrator.auto_approve_hitl:
                    console.print(f"[dim]Auto-approving HITL gate: {status.value}[/dim]")
                    self._auto_approve_gate(status)
                    continue
                console.print(
                    f"[yellow]Paused at HITL gate: {status.value}[/yellow]\n"
                    "Approve via frontend or CLI to continue."
                )
                break

            handler = HANDLER_REGISTRY.get(status)
            if handler is None:
                logger.error("No handler for state: %s", status.value)
                break

            try:
                handler(self.ctx)
            except Exception as exc:
                self._handle_error(exc, status)

    def request_pause(self) -> bool:
        """Request the pipeline to pause after the current handler finishes.

        Returns True if the pipeline was running (pause will take effect).
        The loop breaks at the top of the next iteration.
        """
        self._pause_requested.set()
        console.print("[yellow]Pause requested — will stop after current step completes.[/yellow]")
        return True

    def _auto_approve_gate(self, status: PipelineStatus) -> None:
        # Merge PR when approving HITL_5 (PR review gate)
        if status == PipelineStatus.HITL_5_PR_REVIEW:
            self._merge_module_pr()
        next_state = _GATE_TRANSITIONS.get(status)
        if next_state:
            self.state_mgr.transition_to(next_state)

    def _merge_module_pr(self) -> None:
        """Merge the module's PR on HITL_5 approval (if one exists)."""
        state = self.state_mgr.state
        pr_number = state.metadata.get("pr_number")
        if not pr_number:
            return

        from .handlers import _create_github_client

        client = _create_github_client(self.ctx)
        if not client:
            return

        module_id = state.current_module_id or "unknown"
        result = client.merge_pr(
            int(pr_number),
            merge_method="squash",
            commit_message=f"feat({module_id}): merge accepted module",
        )
        if result.success:
            console.print(f"  [dim]PR #{pr_number} merged[/dim]")
            from ..comms.messages import PipelineEventMessage

            self.bus.publish(PipelineEventMessage(
                sender="git_ops",
                module_id=module_id,
                payload={
                    "event": "pr_merged",
                    "pr_number": pr_number,
                },
            ))
        else:
            console.print(f"  [yellow]PR merge failed: {result.error[:200]}[/yellow]")

    def _handle_error(self, exc: Exception, status: PipelineStatus) -> None:
        """Classify the error, attempt recovery, or transition to FAILED."""
        category = classify_error(exc, context=status.value)
        action = get_recovery_action(category)

        logger.exception(
            "Error in handler for state %s [%s → %s]",
            status.value, category.value, action.value,
        )
        publish_error(self.bus, category, action, detail=str(exc))

        state = self.state_mgr.state
        module_id = state.current_module_id
        iteration = state.current_iteration or 1

        if action == RecoveryAction.ROLLBACK and module_id and self._rollback:
            console.print(f"[yellow]Rolling back {module_id} to last checkpoint...[/yellow]")
            self._rollback.rollback_to_latest_checkpoint(module_id)

        self.state_mgr.transition_to(PipelineStatus.FAILED)

    def _init_rollback(self) -> None:
        """Lazily initialize the rollback manager when git is enabled."""
        if self._rollback is not None:
            return
        if not self.config.git.enabled:
            return
        from ..git_ops.manager import GitOpsManager

        working_dir = self.config.project.root_path or "."
        git = GitOpsManager(working_dir=working_dir, remote=self.config.git.remote)
        if git.is_repo():
            self._rollback = RollbackManager(git)

    # --- Public API (for frontend/CLI) ---

    def approve_gate(self, gate: Optional[PipelineStatus] = None) -> bool:
        current = self.state_mgr.current_status
        if gate and current != gate:
            logger.warning("Cannot approve gate %s — current state is %s", gate, current)
            return False
        if not self.state_mgr.is_hitl_gate():
            logger.warning("Not at a HITL gate (current: %s)", current)
            return False
        self._auto_approve_gate(current)
        return True

    def get_status_table(self) -> Table:
        state = self.state_mgr.state
        modules = self.db.get_all_modules()

        table = Table(title="Agent OS — Pipeline Status")
        table.add_column("Field", style="cyan")
        table.add_column("Value", style="white")

        table.add_row("Pipeline Status", state.pipeline_status.value)
        table.add_row("Current Module", state.current_module_id or "—")
        table.add_row("Current Iteration", str(state.current_iteration))
        table.add_row("Total Modules", str(len(modules)))

        for m in modules:
            style = {
                ModuleStatus.COMPLETED: "green",
                ModuleStatus.IN_PROGRESS: "yellow",
                ModuleStatus.FAILED: "red",
                ModuleStatus.PENDING: "dim",
            }.get(m.status, "white")
            table.add_row(f"  Module {m.id}", f"[{style}]{m.status.value}[/{style}]")

        return table

    def shutdown(self) -> None:
        self.db.close()
