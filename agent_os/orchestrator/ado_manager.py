"""ADO work item manager — extracted from Orchestrator (Phase 8.3).

Handles transitioning Azure DevOps work items between states
(New → Active, Active → Closed) via the ADO REST API.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ADOWorkItemManager:
    """Manages Azure DevOps work item state transitions."""

    def __init__(self, state_mgr: Any, config: Any) -> None:
        self._state_mgr = state_mgr
        self._config = config

    def activate_work_items(self) -> None:
        """Transition ADO work items from New → Active when code generation starts.

        In GHR mode the current story's ID is the ADO work item ID, so only that
        item is activated.  In standard mode all imported work items are activated.
        Credentials fall back from state metadata to config.requirements.
        """
        self._transition_work_items("Active")

    def close_work_items(self, story_id: Optional[str] = None) -> None:
        """Transition ADO work items to Closed.

        When *story_id* is given (GHR per-story completion), only that item is
        closed.  Without *story_id* all items from state metadata are closed.
        """
        self._transition_work_items("Closed", story_id=story_id)

    def _transition_work_items(
        self,
        target_state: str,
        story_id: Optional[str] = None,
    ) -> None:
        """Generic work item state transition via ADO REST API."""
        meta = self._state_mgr.state.metadata
        # Credential fallback: metadata (set via ADO import API) → config.requirements
        ado_org = meta.get("ado_org", "") or getattr(self._config.requirements, "ado_org", "")
        ado_token = meta.get("ado_token", "") or getattr(self._config.requirements, "ado_token", "")
        if not ado_org or not ado_token:
            logger.debug("[ADO] No credentials — skipping %s transition", target_state)
            return

        # Determine which work items to update
        if story_id and str(story_id).isdigit():
            work_item_ids: list[int] = [int(story_id)]
        else:
            # For activate: only the current story should transition, not ALL items.
            # For close without explicit story_id: close all (pipeline-complete scenario).
            current_story = self._state_mgr.state.current_story_id
            if current_story and str(current_story).isdigit():
                work_item_ids = [int(current_story)]
            elif target_state == "Active":
                # Safety: never activate ALL items at once in GHR mode.
                # If current_story is unavailable, skip activation.
                logger.warning(
                    "[ADO] Cannot determine current story for activation — skipping"
                )
                return
            else:
                work_item_ids = meta.get("ado_work_item_ids", [])

        if not work_item_ids:
            logger.debug("[ADO] No work item IDs — skipping %s transition", target_state)
            return

        try:
            import base64
            import httpx
            from urllib.parse import quote

            token_b64 = base64.b64encode(f":{ado_token}".encode()).decode()
            headers = {
                "Authorization": f"Basic {token_b64}",
                "Content-Type": "application/json-patch+json",
            }
            org_enc = quote(ado_org, safe="")
            patch_body = [{"op": "replace", "path": "/fields/System.State", "value": target_state}]

            with httpx.Client(headers=headers, timeout=15, follow_redirects=False) as client:
                for wi_id in work_item_ids:
                    try:
                        resp = client.patch(
                            f"https://dev.azure.com/{org_enc}/_apis/wit/workitems/{wi_id}?api-version=7.1",
                            json=patch_body,
                        )
                        logger.debug(
                            "[ADO] %s work item %s → HTTP %s",
                            target_state,
                            wi_id,
                            resp.status_code,
                        )
                    except Exception:
                        logger.debug(
                            "Failed to set ADO work item %s to %s",
                            wi_id,
                            target_state,
                            exc_info=True,
                        )

            logger.info(
                "[ADO] Set %d work item(s) to %s: %s",
                len(work_item_ids),
                target_state,
                work_item_ids,
            )
        except Exception:
            logger.warning("Failed to transition ADO work items to %s", target_state, exc_info=True)
