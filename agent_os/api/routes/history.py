"""History & query routes — status, iterations, bus-history, story-queue, prompts, reviews."""

from __future__ import annotations

import hashlib
import json as _json
import logging
import time
from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from ..deps import get_orchestrator, orch_holder
from ..schemas import (
    ApproveGateResponse,
    CurrentPromptResponse,
    CurrentReviewResponse,
    IterationListResponse,
    IterationResponse,
    OrchestratorStatusResponse,
    StoryQueueDetailResponse,
    StoryQueueReorderRequest,
)
from ...orchestrator.engine import Orchestrator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/orchestrator", tags=["orchestrator"])

# ── Status endpoint TTL cache (Phase 14.1) ─────────────────────────────────
_status_cache: dict[str, Any] = {"result": None, "etag": "", "ts": 0.0}
_STATUS_TTL = 1.0  # seconds


def invalidate_status_cache() -> None:
    """Called by state manager on transitions to bust the cache immediately."""
    _status_cache["ts"] = 0.0


@router.get("/status", response_model=OrchestratorStatusResponse)
def get_status(
    request: Request,
    response: Response,
    orch: Orchestrator = Depends(get_orchestrator),
) -> OrchestratorStatusResponse:
    """Return the current pipeline status with ETag + TTL cache."""
    now = time.monotonic()

    # Serve from cache if still fresh
    if _status_cache["result"] is not None and (now - _status_cache["ts"]) < _STATUS_TTL:
        etag = _status_cache["etag"]
        response.headers["ETag"] = f'"{etag}"'
        if_none_match = request.headers.get("if-none-match", "")
        if if_none_match == f'"{etag}"':
            return Response(status_code=304)
        return _status_cache["result"]

    state = orch.state_mgr.state
    result = OrchestratorStatusResponse(
        pipeline_status=state.pipeline_status.value,
        current_iteration=state.current_iteration,
        last_checkpoint=state.last_checkpoint,
        metadata=state.metadata,
        is_hitl_gate=orch.state_mgr.is_hitl_gate(),
        mode=getattr(orch.config, "pipeline_mode", "standard") or "standard",
        current_story_id=getattr(state, "current_story_id", None),
        stories_completed=getattr(state, "stories_completed", 0),
        stories_total=getattr(state, "stories_total", 0),
    )

    # ETag: hash of the response body for conditional GETs
    body_bytes = result.model_dump_json().encode()
    etag = hashlib.md5(body_bytes).hexdigest()  # noqa: S324 — not security-critical
    response.headers["ETag"] = f'"{etag}"'

    # Store in cache
    _status_cache["result"] = result
    _status_cache["etag"] = etag
    _status_cache["ts"] = now

    if_none_match = request.headers.get("if-none-match", "")
    if if_none_match == f'"{etag}"':
        return Response(status_code=304)

    return result


@router.get("/iterations", response_model=IterationListResponse)
def get_iterations(
    limit: int = Query(default=0, ge=0, description="Max results (0=all)"),
    offset: int = Query(default=0, ge=0, description="Skip N results"),
    orch: Orchestrator = Depends(get_orchestrator),
) -> IterationListResponse:
    """Return iteration records with optional pagination."""
    rows = orch.get_iterations()
    if offset:
        rows = rows[offset:]
    if limit:
        rows = rows[:limit]
    items = []
    for row in rows:
        try:
            items.append(IterationResponse(**row))
        except Exception:
            logger.debug("Skipping malformed iteration row: %s", row, exc_info=True)
    return IterationListResponse(iterations=items)


@router.get("/current-prompt", response_model=CurrentPromptResponse)
def get_current_prompt(orch: Orchestrator = Depends(get_orchestrator)) -> CurrentPromptResponse:
    """Return the latest generated prompt."""
    state = orch.state_mgr.state
    prompt_content: str = state.metadata.get("prompt_content", "") or ""
    prompt_path: str = getattr(orch.config.project, "prompt_file_path", "") or ""
    # In GHR mode, current_iteration stays 0 — use story_iteration instead
    iteration: int = state.current_iteration or state.metadata.get("story_iteration", 0) or 0

    if not prompt_content and prompt_path:
        from pathlib import Path as _Path
        try:
            prompt_content = _Path(prompt_path).read_text(encoding="utf-8")
        except Exception:
            pass

    return CurrentPromptResponse(
        iteration=iteration,
        content=prompt_content,
        path=prompt_path,
    )


@router.get("/current-review", response_model=CurrentReviewResponse)
def get_current_review(orch: Orchestrator = Depends(get_orchestrator)) -> CurrentReviewResponse:
    """Return the latest code review JSON."""
    state = orch.state_mgr.state
    review_content: str = state.metadata.get("review_json_content", "") or ""
    # In GHR mode, use story_iteration; standard mode uses current_iteration - 1
    iteration: int = state.metadata.get("story_iteration", 0) or max(0, (state.current_iteration or 1) - 1)

    return CurrentReviewResponse(
        iteration=iteration,
        content=review_content,
        path="",
    )


@router.get("/bus-history")
def get_bus_history(
    channel: str = Query(..., description="Channel name: 'review_feedback' or 'validation_results'"),
    limit: int = Query(default=0, ge=0, description="Max results (0=all)"),
    offset: int = Query(default=0, ge=0, description="Skip N results"),
    orch: Orchestrator = Depends(get_orchestrator),
) -> List[Any]:
    """Return historical BusMessage-shaped records for a given channel."""
    from datetime import datetime, timezone

    rows = orch.db.conn.execute(
        "SELECT iteration_number, review_json_content, ci_result, status "
        "FROM iterations ORDER BY iteration_number ASC"
    ).fetchall()

    messages: List[dict] = []
    for row in rows:
        iteration = row["iteration_number"]
        ts = datetime.now(timezone.utc).isoformat()

        if channel == "review_feedback":
            raw = (row["review_json_content"] or "").strip()
            if not raw:
                continue
            try:
                payload = _json.loads(raw)
            except _json.JSONDecodeError:
                payload = {"raw": raw}
            messages.append({
                "channel": "review_feedback",
                "sender": "code_reviewer",
                "timestamp": ts,
                "module_id": "code_reviewer",
                "iteration": iteration,
                "payload": payload,
            })

        elif channel == "validation_results":
            raw = (row["ci_result"] or "").strip()
            if not raw:
                continue
            try:
                payload = _json.loads(raw)
            except _json.JSONDecodeError:
                payload = {"raw": raw, "status": row["status"]}
            messages.append({
                "channel": "validation_results",
                "sender": "ci_runner",
                "timestamp": ts,
                "module_id": "ci_runner",
                "iteration": iteration,
                "payload": payload,
            })

    # Apply pagination
    if offset:
        messages = messages[offset:]
    if limit:
        messages = messages[:limit]

    return messages


@router.get("/story-queue")
def get_story_queue(orch: Orchestrator = Depends(get_orchestrator)) -> dict:
    """Return the current story queue state (GitHub Review mode)."""
    from ...orchestrator.story_queue import StoryQueueManager

    mgr = StoryQueueManager(orch.db)
    stories = mgr.get_queue_state()
    state = orch.state_mgr.state
    return {
        "mode": getattr(orch.config, "pipeline_mode", "standard") or "standard",
        "current_story_id": getattr(state, "current_story_id", None),
        "stories_completed": getattr(state, "stories_completed", 0),
        "stories_total": getattr(state, "stories_total", 0),
        "stories": stories,
    }


@router.get("/story-queue/{story_id}", response_model=StoryQueueDetailResponse)
def get_story_queue_item(
    story_id: str,
    orch: Orchestrator = Depends(get_orchestrator),
) -> StoryQueueDetailResponse:
    """Return a single story-queue item by story_id."""
    from ...orchestrator.story_queue import StoryQueueManager

    mgr = StoryQueueManager(orch.db)
    item = mgr.get_item(story_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Story '{story_id}' not found in queue.")
    return StoryQueueDetailResponse(**item.model_dump(mode="json"))


@router.post("/story-queue/reorder", response_model=ApproveGateResponse)
def reorder_story_queue(
    body: StoryQueueReorderRequest,
    orch: Orchestrator = Depends(get_orchestrator),
) -> ApproveGateResponse:
    """Manually reorder the story queue."""
    from ...orchestrator.story_queue import StoryQueueManager

    mgr = StoryQueueManager(orch.db)
    queue = mgr.get_queue_state()

    id_to_pos = {sid: idx for idx, sid in enumerate(body.story_ids)}

    conn = orch.db.conn
    updated = 0
    for row in queue:
        sid = row["story_id"]
        if sid in id_to_pos and row["status"] == "queued":
            conn.execute(
                "UPDATE story_queue SET position = ? WHERE story_id = ?",
                (id_to_pos[sid], sid),
            )
            updated += 1
    conn.commit()
    return ApproveGateResponse(
        approved=True,
        message=f"Reordered {updated} queued stories.",
    )
