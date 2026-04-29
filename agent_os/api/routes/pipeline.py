"""Pipeline routes — status, start, approve gate, current prompt."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...storage.models import PipelineStatus
from ..deps import get_orchestrator
from ..schemas import ApproveGateRequest, ApproveGateResponse, PipelineStatusResponse

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


@router.get("/status", response_model=PipelineStatusResponse)
def get_pipeline_status(orch=Depends(get_orchestrator)):
    state = orch.state_mgr.state
    modules = orch.db.get_all_modules()
    return PipelineStatusResponse(
        pipeline_status=state.pipeline_status.value,
        current_module_id=state.current_module_id,
        current_iteration=state.current_iteration,
        last_checkpoint=state.last_checkpoint,
        metadata=state.metadata,
        is_hitl_gate=orch.state_mgr.is_hitl_gate(),
        total_modules=len(modules),
    )


@router.post("/start", response_model=PipelineStatusResponse)
def start_pipeline(orch=Depends(get_orchestrator)):
    """Start or resume the pipeline in a background thread."""
    current = orch.state_mgr.current_status
    # Reset terminal states so the pipeline can start fresh
    if current in (PipelineStatus.PIPELINE_COMPLETE, PipelineStatus.FAILED):
        orch.state_mgr.reset()
    t = threading.Thread(target=orch.run, daemon=True, name="pipeline-run")
    t.start()
    state = orch.state_mgr.state
    modules = orch.db.get_all_modules()
    return PipelineStatusResponse(
        pipeline_status=state.pipeline_status.value,
        current_module_id=state.current_module_id,
        current_iteration=state.current_iteration,
        last_checkpoint=state.last_checkpoint,
        metadata=state.metadata,
        is_hitl_gate=orch.state_mgr.is_hitl_gate(),
        total_modules=len(modules),
    )


@router.post("/approve-gate", response_model=ApproveGateResponse)
def approve_gate(
    body: Optional[ApproveGateRequest] = None,
    orch=Depends(get_orchestrator),
):
    gate: Optional[PipelineStatus] = None
    if body and body.gate:
        try:
            gate = PipelineStatus(body.gate)
        except ValueError:
            return ApproveGateResponse(approved=False, message=f"Invalid gate: {body.gate}")

    approved = orch.approve_gate(gate)
    if approved:
        # Resume pipeline in background after approving
        t = threading.Thread(target=orch.run, daemon=True, name="pipeline-resume")
        t.start()
        return ApproveGateResponse(approved=True, message="Gate approved, pipeline resuming")
    return ApproveGateResponse(approved=False, message="Not at a HITL gate or wrong gate")


@router.post("/pause", response_model=ApproveGateResponse)
def pause_pipeline(orch=Depends(get_orchestrator)):
    """Request the pipeline to pause after the current handler finishes."""
    orch.request_pause()
    return ApproveGateResponse(
        approved=True,
        message="Pause requested — pipeline will stop after the current step completes.",
    )


@router.post("/retry-module-maker", response_model=ApproveGateResponse)
def retry_module_maker(orch=Depends(get_orchestrator)):
    """Re-run Module Maker from HITL_1_MODULE_REVIEW gate or after a FAILED state."""
    current = orch.state_mgr.current_status
    _module_retry_states = {PipelineStatus.HITL_1_MODULE_REVIEW, PipelineStatus.FAILED}
    if current not in _module_retry_states:
        return ApproveGateResponse(
            approved=False,
            message=f"Can only retry from HITL_1_MODULE_REVIEW or FAILED, currently at {current.value}",
        )
    if current == PipelineStatus.FAILED:
        pre = orch.state_mgr.state.metadata.get("pre_failure_status", "")
        allowed_pre = {
            PipelineStatus.MODULE_PLANNING.value,
            PipelineStatus.HITL_1_MODULE_REVIEW.value,
            PipelineStatus.PROMPT_GENERATION.value,
            PipelineStatus.HITL_2_PROMPT_REVIEW.value,
        }
        # Also allow if module JSON files are simply missing (any failure stage)
        data_dir = orch.config.storage.data_dir
        modules_dir = data_dir / "modules"
        json_files_missing = not modules_dir.exists() or not list(modules_dir.glob("mod-*.json"))
        if pre not in allowed_pre and not json_files_missing:
            return ApproveGateResponse(
                approved=False,
                message=(
                    f"Pipeline failed during '{pre}', not during module planning. "
                    "Cannot retry Module Maker."
                ),
            )
    orch.state_mgr.transition_to(PipelineStatus.MODULE_PLANNING)
    t = threading.Thread(target=orch.run, daemon=True, name="pipeline-retry-mm")
    t.start()
    return ApproveGateResponse(approved=True, message="Retrying Module Maker generation")


@router.post("/retry-prompt-generator", response_model=ApproveGateResponse)
def retry_prompt_generator(orch=Depends(get_orchestrator)):
    """Re-run Prompt Generator from HITL_2_PROMPT_REVIEW gate or after a FAILED state."""
    current = orch.state_mgr.current_status
    _prompt_retry_states = {PipelineStatus.HITL_2_PROMPT_REVIEW, PipelineStatus.FAILED}
    if current not in _prompt_retry_states:
        return ApproveGateResponse(
            approved=False,
            message=f"Can only retry from HITL_2_PROMPT_REVIEW or FAILED, currently at {current.value}",
        )
    if current == PipelineStatus.FAILED:
        pre = orch.state_mgr.state.metadata.get("pre_failure_status", "")
        allowed_pre = {PipelineStatus.PROMPT_GENERATION.value, PipelineStatus.HITL_2_PROMPT_REVIEW.value}
        if pre not in allowed_pre:
            return ApproveGateResponse(
                approved=False,
                message=f"Pipeline failed during '{pre}', not during prompt generation. Cannot retry Prompt Generator.",
            )

    # Ensure current_module_id is set — if lost (e.g. first entry from module review),
    # pick the first IN_PROGRESS or PENDING module.
    state = orch.state_mgr.state
    module_id = state.current_module_id
    if not module_id:
        from ...storage.models import ModuleStatus
        from ...storage.module_repo import ModuleRepository

        mod_repo = ModuleRepository(orch.db.conn)
        all_mods = mod_repo.get_all()
        # Prefer IN_PROGRESS, then first PENDING with deps met
        in_progress = [m for m in all_mods if m.status == ModuleStatus.IN_PROGRESS]
        if in_progress:
            module_id = in_progress[0].id
        else:
            completed_ids = {m.id for m in all_mods if m.status == ModuleStatus.COMPLETED}
            for m in all_mods:
                if m.status == ModuleStatus.PENDING and all(
                    dep in completed_ids for dep in m.dependency_ids
                ):
                    module_id = m.id
                    mod_repo.update_status(m.id, ModuleStatus.IN_PROGRESS)
                    break

    if not module_id:
        return ApproveGateResponse(
            approved=False,
            message="No module available for prompt generation.",
        )

    orch.state_mgr.transition_to(
        PipelineStatus.PROMPT_GENERATION,
        module_id=module_id,
        iteration=state.current_iteration or 1,
    )
    t = threading.Thread(target=orch.run, daemon=True, name="pipeline-retry-pg")
    t.start()
    return ApproveGateResponse(approved=True, message="Retrying Prompt Generator")


@router.post("/retry-code-generator", response_model=ApproveGateResponse)
def retry_code_generator(orch=Depends(get_orchestrator)):
    """Re-run Code Generator for the current module from HITL_3, VALIDATION, CODE_REVIEW, or FAILED."""
    current = orch.state_mgr.current_status
    _allowed = {
        PipelineStatus.HITL_3_REVIEW_DECISION,
        PipelineStatus.VALIDATION,
        PipelineStatus.CODE_REVIEW,
        PipelineStatus.FAILED,
    }
    if current not in _allowed:
        return ApproveGateResponse(
            approved=False,
            message=f"Cannot retry Code Generator from {current.value}",
        )

    state = orch.state_mgr.state
    module_id = state.current_module_id

    if not module_id:
        from ...storage.models import ModuleStatus
        from ...storage.module_repo import ModuleRepository
        mod_repo = ModuleRepository(orch.db.conn)
        all_mods = mod_repo.get_all()
        in_progress = [m for m in all_mods if m.status == ModuleStatus.IN_PROGRESS]
        if in_progress:
            module_id = in_progress[0].id

    if not module_id:
        return ApproveGateResponse(approved=False, message="No module available for code generation.")

    orch.state_mgr.transition_to(
        PipelineStatus.CODE_GENERATION,
        module_id=module_id,
        iteration=state.current_iteration or 1,
    )
    t = threading.Thread(target=orch.run, daemon=True, name="pipeline-retry-cg")
    t.start()
    return ApproveGateResponse(approved=True, message="Retrying Code Generator — regenerating source code")


@router.post("/retry-code-reviewer", response_model=ApproveGateResponse)
def retry_code_reviewer(orch=Depends(get_orchestrator)):
    """Re-run Code Reviewer for the current module from HITL_3 or FAILED."""
    current = orch.state_mgr.current_status
    _allowed = {
        PipelineStatus.HITL_3_REVIEW_DECISION,
        PipelineStatus.FAILED,
    }
    if current not in _allowed:
        return ApproveGateResponse(
            approved=False,
            message=f"Cannot retry Code Reviewer from {current.value}",
        )

    state = orch.state_mgr.state
    module_id = state.current_module_id

    if not module_id:
        from ...storage.models import ModuleStatus
        from ...storage.module_repo import ModuleRepository
        mod_repo = ModuleRepository(orch.db.conn)
        all_mods = mod_repo.get_all()
        in_progress = [m for m in all_mods if m.status == ModuleStatus.IN_PROGRESS]
        if in_progress:
            module_id = in_progress[0].id

    if not module_id:
        return ApproveGateResponse(approved=False, message="No module available for code review.")

    orch.state_mgr.transition_to(
        PipelineStatus.CODE_REVIEW,
        module_id=module_id,
        iteration=state.current_iteration or 1,
    )
    t = threading.Thread(target=orch.run, daemon=True, name="pipeline-retry-cr")
    t.start()
    return ApproveGateResponse(approved=True, message="Retrying Code Reviewer — re-reviewing source code")


# ---------------------------------------------------------------------------
# Current prompt at HITL gate
# ---------------------------------------------------------------------------

class CurrentPromptResponse(BaseModel):
    module_id: str
    iteration: int
    content: str
    path: str


class UpdatePromptRequest(BaseModel):
    content: str


@router.get("/current-prompt", response_model=CurrentPromptResponse)
def get_current_prompt(orch=Depends(get_orchestrator)):
    """Return the prompt file for the current module/iteration (file or DB fallback)."""
    state = orch.state_mgr.state
    module_id = state.current_module_id
    iteration = state.current_iteration or 1

    # If no active module in state, try the most recently active module in DB
    if not module_id:
        from ...storage.module_repo import ModuleRepository
        from ...storage.models import ModuleStatus
        mod_repo = ModuleRepository(orch.db.conn)
        all_mods = mod_repo.get_all()
        candidates = [m for m in all_mods if m.status in (ModuleStatus.IN_PROGRESS, ModuleStatus.COMPLETED)]
        if candidates:
            module_id = candidates[-1].id
        else:
            raise HTTPException(status_code=404, detail="No active module")

    data_dir = orch.config.storage.data_dir
    prompt_path = data_dir / "prompts" / f"module-{module_id}" / f"iteration-{iteration}.md"

    # Try file first
    if prompt_path.exists():
        return CurrentPromptResponse(
            module_id=module_id,
            iteration=iteration,
            content=prompt_path.read_text(encoding="utf-8"),
            path=str(prompt_path),
        )

    # Fall back to DB prompt_content
    from ...storage.iteration_repo import IterationRepository
    iter_repo = IterationRepository(orch.db.conn)
    iters = iter_repo.get_for_module(module_id)
    target = next((i for i in reversed(iters) if i.iteration_number == iteration), None)
    if not target:
        target = iters[-1] if iters else None
    if target and target.prompt_content:
        return CurrentPromptResponse(
            module_id=module_id,
            iteration=target.iteration_number,
            content=target.prompt_content,
            path=str(prompt_path),
        )

    raise HTTPException(status_code=404, detail="No prompt found for current module/iteration")


@router.put("/current-prompt", response_model=CurrentPromptResponse)
def update_current_prompt(
    body: UpdatePromptRequest,
    orch=Depends(get_orchestrator),
):
    """Save edited prompt content back to disk."""
    state = orch.state_mgr.state
    module_id = state.current_module_id
    iteration = state.current_iteration or 1

    if not module_id:
        raise HTTPException(status_code=404, detail="No active module")

    data_dir = orch.config.storage.data_dir
    prompt_path = data_dir / "prompts" / f"module-{module_id}" / f"iteration-{iteration}.md"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(body.content, encoding="utf-8")

    return CurrentPromptResponse(
        module_id=module_id,
        iteration=iteration,
        content=body.content,
        path=str(prompt_path),
    )


# ---------------------------------------------------------------------------
# Current review at HITL gate
# ---------------------------------------------------------------------------

class CurrentReviewResponse(BaseModel):
    module_id: str
    iteration: int
    content: str
    path: str


class UpdateReviewRequest(BaseModel):
    content: str


@router.get("/current-review", response_model=CurrentReviewResponse)
def get_current_review(orch=Depends(get_orchestrator)):
    """Return the review JSON for the current module/iteration (file or DB fallback)."""
    state = orch.state_mgr.state
    module_id = state.current_module_id
    iteration = state.current_iteration or 1

    # If not at the review gate, try the most recently reviewed module
    if not module_id:
        from ...storage.module_repo import ModuleRepository
        from ...storage.models import ModuleStatus
        mod_repo = ModuleRepository(orch.db.conn)
        all_mods = mod_repo.get_all()
        reviewed = [m for m in all_mods if m.status in (ModuleStatus.IN_PROGRESS, ModuleStatus.COMPLETED)]
        if reviewed:
            module_id = reviewed[-1].id
        else:
            raise HTTPException(status_code=404, detail="No active module with a review")

    data_dir = orch.config.storage.data_dir
    review_path = data_dir / "reviews" / f"module-{module_id}" / f"iteration-{iteration}.json"

    # Try file first
    if review_path.exists():
        content = review_path.read_text(encoding="utf-8")
        return CurrentReviewResponse(
            module_id=module_id, iteration=iteration, content=content, path=str(review_path)
        )

    # Fall back to DB review_content
    from ...storage.iteration_repo import IterationRepository
    iter_repo = IterationRepository(orch.db.conn)
    iters = iter_repo.get_for_module(module_id)
    target = next((i for i in reversed(iters) if i.iteration_number == iteration), None)
    if not target:
        target = iters[-1] if iters else None
    if target and target.review_content:
        return CurrentReviewResponse(
            module_id=module_id,
            iteration=target.iteration_number,
            content=target.review_content,
            path=str(review_path),
        )

    raise HTTPException(status_code=404, detail="No review found for current module/iteration")


@router.put("/current-review", response_model=CurrentReviewResponse)
def update_current_review(
    body: UpdateReviewRequest,
    orch=Depends(get_orchestrator),
):
    """Save edited review content back to disk and DB."""
    state = orch.state_mgr.state
    module_id = state.current_module_id
    iteration = state.current_iteration or 1

    if not module_id:
        raise HTTPException(status_code=404, detail="No active module")

    data_dir = orch.config.storage.data_dir
    review_path = data_dir / "reviews" / f"module-{module_id}" / f"iteration-{iteration}.json"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(body.content, encoding="utf-8")

    # Also update DB
    from ...storage.iteration_repo import IterationRepository
    iter_repo = IterationRepository(orch.db.conn)
    iters = iter_repo.get_for_module(module_id)
    target = next((i for i in iters if i.iteration_number == iteration), None)
    if target:
        iter_repo.update(target.id, review_content=body.content)

    return CurrentReviewResponse(
        module_id=module_id,
        iteration=iteration,
        content=body.content,
        path=str(review_path),
    )


# ---------------------------------------------------------------------------
# Full pipeline reset
# ---------------------------------------------------------------------------

class ResetResponse(BaseModel):
    success: bool
    message: str


@router.post("/reset", response_model=ResetResponse)
def reset_pipeline(orch=Depends(get_orchestrator)):
    """Fully reset the pipeline: delete all modules, iterations, requirements,
    prompts, reviews, validations from DB and data files. Generated code on
    disk is retained in the current project folder. A new versioned project
    folder (name_v2, name_v3, …) is created and linked for the next session."""
    import re
    import shutil

    try:
        conn = orch.db.conn

        # Delete DB records in dependency order
        conn.execute("DELETE FROM iterations")
        conn.execute("DELETE FROM modules")
        conn.execute("DELETE FROM requirements")
        conn.commit()

        # Reset pipeline state to IDLE
        orch.state_mgr.reset()

        # Clear data files (prompts, reviews, validations, modules JSONs)
        # but leave the DB itself intact
        data_dir = orch.config.storage.data_dir
        for subdir in ("modules", "prompts", "reviews", "validations", "summaries"):
            target = data_dir / subdir
            if target.exists():
                shutil.rmtree(target)

        # ---------------------------------------------------------------
        # Compute next versioned project folder
        # ---------------------------------------------------------------
        # The base slug comes from the current project name (or the
        # existing root_path folder name as fallback).
        prev_root = orch.config.project.root_path
        project_name = orch.config.project.name or ""

        def _slug(name: str) -> str:
            return re.sub(r"[^\w\s-]", "", name).strip().replace(" ", "-").lower() or "agent-os-project"

        if project_name:
            base_slug = _slug(project_name)
        elif prev_root:
            # Strip any existing _vN suffix to find the true base name
            folder_name = Path(prev_root).name
            base_slug = re.sub(r"_v\d+$", "", folder_name) or _slug(folder_name)
        else:
            base_slug = "agent-os-project"

        desktop = Path.home() / "Desktop"

        # Find the next available version number.
        # v1 is the original (un-suffixed) folder; v2 is the first reset copy.
        version = 2
        while (desktop / f"{base_slug}_v{version}").exists():
            version += 1

        new_project_dir = desktop / f"{base_slug}_v{version}"
        new_project_dir.mkdir(parents=True, exist_ok=True)

        # ---------------------------------------------------------------
        # Persist new versioned path to config for the next session
        # ---------------------------------------------------------------
        orch.config.project.root_path = str(new_project_dir)
        # Keep project.name so the next session knows the project identity;
        # the folder name carries the version.
        try:
            from ..deps import orch_holder
            from .settings import _write_config_yaml
            _write_config_yaml(orch.config, orch_holder.config_path)
        except Exception:
            pass

        return ResetResponse(
            success=True,
            message=(
                f"Pipeline reset. Previous code retained in "
                f"{Path(prev_root).name if prev_root else '(none)'}. "
                f"New session will use: {new_project_dir.name}"
            ),
        )
    except Exception as e:
        return ResetResponse(success=False, message=f"Reset failed: {e}")


# ---------------------------------------------------------------------------
# Skip to Next Module — user accepts current code and moves on
# ---------------------------------------------------------------------------

@router.post("/skip-to-next-module", response_model=ApproveGateResponse)
def skip_to_next_module(orch=Depends(get_orchestrator)):
    """Accept current module code as-is and proceed to the next module.

    Marks the current module as COMPLETED and transitions directly to
    NEXT_MODULE, bypassing HITL_5 and integration test.
    """
    current = orch.state_mgr.current_status
    _allowed = {
        PipelineStatus.HITL_3_REVIEW_DECISION,
        PipelineStatus.HITL_4_MAX_ITERATIONS,
    }
    if current not in _allowed:
        return ApproveGateResponse(
            approved=False,
            message=f"Cannot skip module from {current.value}",
        )

    state = orch.state_mgr.state
    module_id = state.current_module_id

    if not module_id:
        return ApproveGateResponse(approved=False, message="No active module to skip.")

    # Mark current iteration and module as completed
    from ...storage.iteration_repo import IterationRepository
    from ...storage.models import IterationStatus, ModuleStatus
    from ...storage.module_repo import ModuleRepository

    iter_repo = IterationRepository(orch.db.conn)
    iteration = state.current_iteration or 1
    iter_record = iter_repo.get(module_id, iteration)
    if iter_record:
        iter_record.status = IterationStatus.COMPLETED
        iter_repo.update(iter_record)

    mod_repo = ModuleRepository(orch.db.conn)
    mod_repo.update_status(module_id, ModuleStatus.COMPLETED)

    # Go directly to NEXT_MODULE — no HITL_5 or integration test
    orch.state_mgr.transition_to(PipelineStatus.NEXT_MODULE)

    import threading
    t = threading.Thread(target=orch.run, daemon=True, name="pipeline-skip-module")
    t.start()

    return ApproveGateResponse(
        approved=True,
        message=f"Accepting {module_id} as-is and proceeding to next module.",
    )
