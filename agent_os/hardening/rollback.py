"""Git rollback manager — checkpoint and restore for iteration safety."""

from __future__ import annotations

import logging
from typing import Optional

from ..git_ops.manager import GitOpsManager, GitResult

logger = logging.getLogger(__name__)


class RollbackManager:
    """Manages Git checkpoint/rollback for catastrophic failure recovery.

    Creates lightweight tags at iteration start so the working tree can
    be reset to a known-clean state if an unrecoverable error occurs.
    """

    CHECKPOINT_PREFIX = "checkpoint/"

    def __init__(self, git: GitOpsManager) -> None:
        self._git = git

    def checkpoint_tag(self, module_id: str, iteration: int) -> str:
        return f"{self.CHECKPOINT_PREFIX}{module_id}/iter-{iteration}"

    def create_checkpoint(self, module_id: str, iteration: int) -> Optional[str]:
        """Create a checkpoint tag at the current HEAD.

        Returns the tag name on success, or None if Git is unavailable.
        """
        if not self._git.is_repo():
            logger.debug("Not a git repo — skipping checkpoint")
            return None

        # Stage + commit any outstanding changes so the checkpoint is clean
        if self._git.has_changes():
            msg = f"checkpoint: {module_id} iter-{iteration} start"
            self._git.commit_all(msg)

        tag = self.checkpoint_tag(module_id, iteration)
        result = self._git.tag(tag, f"Checkpoint before {module_id} iteration {iteration}")

        if result.success:
            logger.info("Checkpoint created: %s", tag)
            return tag

        logger.warning("Failed to create checkpoint tag: %s", result.stderr)
        return None

    def rollback_to_checkpoint(self, module_id: str, iteration: int) -> GitResult:
        """Hard-reset the working tree to a checkpoint.

        Returns the GitResult from the reset operation.
        """
        tag = self.checkpoint_tag(module_id, iteration)
        logger.warning("Rolling back to checkpoint: %s", tag)
        return self._git.reset_hard(tag)

    def rollback_to_latest_checkpoint(self, module_id: str) -> GitResult:
        """Find the most recent checkpoint for a module and reset to it."""
        prefix = f"{self.CHECKPOINT_PREFIX}{module_id}/"
        tags = self._git.list_tags(prefix)
        if not tags:
            logger.warning("No checkpoints found for module %s", module_id)
            return GitResult(success=False, command="rollback", stderr="no checkpoints found")

        latest_tag = tags[-1]
        logger.warning("Rolling back to latest checkpoint: %s", latest_tag)
        return self._git.reset_hard(latest_tag)
