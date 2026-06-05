"""Pipeline control routes — start/stop/pause/reset."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_orchestrator, orch_holder
from ..schemas import ApproveGateResponse
from ...orchestrator.engine import Orchestrator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/orchestrator", tags=["orchestrator"])


@router.post("/start", response_model=ApproveGateResponse)
def start_pipeline(orch: Orchestrator = Depends(get_orchestrator)) -> ApproveGateResponse:
    """Start (or resume) the pipeline in a background thread."""
    from ...services.pipeline_service import PipelineService, PipelineAlreadyRunningError

    svc = PipelineService(orch)
    try:
        msg = svc.start()
    except PipelineAlreadyRunningError:
        raise HTTPException(status_code=409, detail="Pipeline is already running")
    return ApproveGateResponse(approved=True, message=msg)


@router.post("/pause", response_model=ApproveGateResponse)
def pause_pipeline(orch: Orchestrator = Depends(get_orchestrator)) -> ApproveGateResponse:
    """Request the pipeline to pause after the current step."""
    orch.pause()
    return ApproveGateResponse(approved=True, message="Pause requested")


@router.post("/stop", response_model=ApproveGateResponse)
def stop_code_generation(orch: Orchestrator = Depends(get_orchestrator)) -> ApproveGateResponse:
    """Kill the active code-generation subprocess mid-flight."""
    ok = orch.stop_code_generation()
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="Cannot stop — pipeline is not currently in a code-generation state.",
        )
    return ApproveGateResponse(approved=True, message="Stop signal sent — killing code generation subprocess")


@router.post("/stop-rollback", response_model=ApproveGateResponse)
def stop_rollback(orch: Orchestrator = Depends(get_orchestrator)) -> ApproveGateResponse:
    """Roll back partial code-gen changes after a stop."""
    ok = orch.rollback_after_stop()
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="Cannot roll back — pipeline is not at CODE_GEN_STOPPED.",
        )
    return ApproveGateResponse(approved=True, message="Partial changes discarded — returned to prompt review")


@router.post("/stop-continue", response_model=ApproveGateResponse)
def stop_continue(orch: Orchestrator = Depends(get_orchestrator)) -> ApproveGateResponse:
    """Save partial code-gen progress and continue to code review."""
    ok = orch.continue_after_stop()
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="Cannot continue — pipeline is not at CODE_GEN_STOPPED.",
        )
    return ApproveGateResponse(approved=True, message="Partial changes committed — proceeding to code review")


@router.post("/reset", response_model=ApproveGateResponse)
def reset_pipeline(orch: Orchestrator = Depends(get_orchestrator)) -> ApproveGateResponse:
    """Reset the pipeline to IDLE, discarding in-progress state."""
    orch.reset()

    # ── Rotate project folder ────────────────────────────────────────────
    old_root = getattr(orch.config.project, "root_path", "") or ""
    if old_root:
        old_path = Path(old_root)
        name = old_path.name
        parent = old_path.parent

        m = re.search(r"_v(\d+)$", name)
        if m:
            ver = int(m.group(1)) + 1
            new_name = name[: m.start()] + f"_v{ver}"
        else:
            new_name = f"{name}_v1"

        new_path = parent / new_name
        new_path.mkdir(parents=True, exist_ok=True)

        orch.config.project.root_path = str(new_path)

        from ..routes.settings import _write_config_yaml
        _write_config_yaml(orch.config, orch_holder.config_path)

        return ApproveGateResponse(
            approved=True,
            message=f"Pipeline reset to IDLE — new project folder: {new_path.name}",
        )

    return ApproveGateResponse(approved=True, message="Pipeline reset to IDLE")
