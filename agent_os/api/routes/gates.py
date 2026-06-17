"""HITL gate routes — approve/retry/move-to-next-story."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...orchestrator.engine import Orchestrator
from ..deps import get_orchestrator, orch_holder
from ..schemas import (
    ApproveGateRequest,
    ApproveGateResponse,
    ApprovePromptRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/orchestrator", tags=["orchestrator"])


@router.post("/approve-prompt", response_model=ApproveGateResponse)
def approve_prompt(
    body: ApprovePromptRequest,
    orch: Orchestrator = Depends(get_orchestrator),  # noqa: B008
) -> ApproveGateResponse:
    """Approve the generated prompt and optionally supply an edited version."""
    ok = orch.approve_prompt(
        prompt_content=body.prompt_content,
        cli_tool=body.cli_tool,
        cli_model=body.cli_model,
    )
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="Pipeline is not waiting at HITL_PROMPT_REVIEW gate.",
        )
    return ApproveGateResponse(approved=True, message="Prompt approved — pipeline resumed")


@router.post("/approve-review", response_model=ApproveGateResponse)
def approve_review(orch: Orchestrator = Depends(get_orchestrator)) -> ApproveGateResponse:  # noqa: B008
    """Approve the code review and continue (loop or complete)."""
    ok = orch.approve_review()
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="Pipeline is not waiting at HITL_REVIEW_DECISION gate.",
        )
    return ApproveGateResponse(approved=True, message="Review approved — pipeline resumed")


@router.post("/move-to-next-story", response_model=ApproveGateResponse)
def move_to_next_story(orch: Orchestrator = Depends(get_orchestrator)) -> ApproveGateResponse:  # noqa: B008
    """Merge the current story's PR, delete its branch, then advance to the next story."""
    ok = orch.move_to_next_story()
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="Cannot move to next story — pipeline is not at HITL_REVIEW_DECISION or STORY_COMPLETE.",
        )
    return ApproveGateResponse(approved=True, message="Merging PR and advancing to next story")


@router.post("/approve-gate", response_model=ApproveGateResponse)
def approve_gate(
    body: ApproveGateRequest,
    orch: Orchestrator = Depends(get_orchestrator),  # noqa: B008
) -> ApproveGateResponse:
    """Generic gate approval — kept for backward compatibility."""
    ok = orch.approve_gate(gate=body.gate)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="Could not approve gate — pipeline is not at the expected gate state.",
        )
    return ApproveGateResponse(approved=True, message="Gate approved")


@router.post("/retry-pr", response_model=ApproveGateResponse)
def retry_pr(orch: Orchestrator = Depends(get_orchestrator)) -> ApproveGateResponse:  # noqa: B008
    """Retry pull request creation after a failure."""
    ok = orch.retry_pr()
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="Cannot retry PR — pipeline is not in the expected state or retry failed.",
        )
    return ApproveGateResponse(approved=True, message="PR retry initiated — pipeline resuming")


@router.post("/retry-prompt-generator", response_model=ApproveGateResponse)
def retry_prompt_generator(orch: Orchestrator = Depends(get_orchestrator)) -> ApproveGateResponse:  # noqa: B008
    """Re-run prompt generation from the HITL_PROMPT_REVIEW gate."""
    ok = orch.retry_prompt_generator()
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="Cannot regenerate prompt — pipeline is not at HITL_PROMPT_REVIEW.",
        )
    return ApproveGateResponse(approved=True, message="Prompt generator retry started")


@router.post("/retry-code-generator", response_model=ApproveGateResponse)
def retry_code_generator(
    body: ApprovePromptRequest,
    orch: Orchestrator = Depends(get_orchestrator),  # noqa: B008
) -> ApproveGateResponse:
    """Retry code generation after a failure, optionally with a different tool/model."""
    ok = orch.retry_code_generator(
        cli_tool=body.cli_tool or "",
        cli_model=body.cli_model or "",
    )
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="Cannot retry code generator — not at CODE_GEN_FAILED state.",
        )
    return ApproveGateResponse(approved=True, message="Code generator retry started")


@router.post("/retry-code-reviewer", response_model=ApproveGateResponse)
def retry_code_reviewer(orch: Orchestrator = Depends(get_orchestrator)) -> ApproveGateResponse:  # noqa: B008
    """Retry code review after a failure."""
    ok = orch.retry_code_reviewer()
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="Cannot retry code reviewer — not at HITL_REVIEW_DECISION with a failure.",
        )
    return ApproveGateResponse(approved=True, message="Code reviewer retry started")


# ---------------------------------------------------------------------------
# Review JSON override (HITL edit before approve)
# ---------------------------------------------------------------------------

class _UpdateReviewRequest(BaseModel):
    content: str


@router.put("/review")
def update_review(
    body: _UpdateReviewRequest,
    orch: Orchestrator = Depends(get_orchestrator),  # noqa: B008
) -> dict:
    """Overwrite the pending review JSON before the user hits approve-review."""
    import json as _json_mod

    from ...code_reviewer.schema import ReviewJSON

    raw = body.content.strip()
    if not raw:
        raise HTTPException(status_code=422, detail="content must not be empty")

    try:
        data = _json_mod.loads(raw)
        review = ReviewJSON.model_validate(data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid ReviewJSON: {exc}") from exc

    validated_json = review.model_dump_json()
    orch.state_mgr.update_metadata({
        "review_json_content": validated_json,
        "review_overall_status": review.overall_status,
    })

    return {
        "iteration": orch.state_mgr.state.current_iteration or 0,
        "overall_status": review.overall_status,
        "content": validated_json,
    }


# ---------------------------------------------------------------------------
# CLI tool routing
# ---------------------------------------------------------------------------

class _SetCliToolRequest(BaseModel):
    post: str
    tool: str


@router.put("/cli-tool")
def set_cli_tool(
    body: _SetCliToolRequest,
    orch: Orchestrator = Depends(get_orchestrator),  # noqa: B008
) -> dict:
    """Persist which CLI tool handles a given agent post."""
    from ...codex.cli_adapter import SUPPORTED_TOOLS

    post = body.post.upper()
    tool = body.tool.lower()

    _VALID_POSTS = {"CODE_GENERATOR", "PROMPT_GENERATOR", "CODE_REVIEWER"}
    if post not in _VALID_POSTS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid post '{post}'. Valid values: {sorted(_VALID_POSTS)}",
        )
    if tool not in SUPPORTED_TOOLS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown tool '{tool}'. Supported: {SUPPORTED_TOOLS}",
        )

    orch.config.codex.cli_routing[post] = tool

    if orch_holder.config_path:
        from ..routes.settings import _write_config_yaml
        _write_config_yaml(orch.config, orch_holder.config_path)

    return {
        "post": post,
        "tool": tool,
        "cli_routing": dict(orch.config.codex.cli_routing),
    }
