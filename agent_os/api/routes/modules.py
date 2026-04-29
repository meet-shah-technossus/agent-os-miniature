"""Module routes — list modules, get detail, get iterations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...comms.channels import Channel
from ...storage.iteration_repo import IterationRepository
from ...storage.module_repo import ModuleRepository
from ..deps import get_orchestrator
from ..schemas import IterationResponse, ModuleResponse

router = APIRouter(prefix="/api/modules", tags=["modules"])


def _build_pr_map(orch) -> dict[str, tuple[int | None, str]]:
    """Scan bus history for git_commit events and extract PR info per module."""
    pr_map: dict[str, tuple[int | None, str]] = {}
    for msg in orch.bus.history_for_channel(Channel.PIPELINE_EVENTS):
        payload = msg.payload
        if payload.get("event") == "git_commit" and msg.module_id:
            pr_num = payload.get("pr_number")
            pr_url = payload.get("pr_url", "")
            if pr_num:
                pr_map[msg.module_id] = (pr_num, pr_url)
    return pr_map


# ---------------------------------------------------------------------------
# Full module definitions (read/write the JSON blueprint files)
# NOTE: these MUST be registered before /{module_id} to avoid "definitions"
# being treated as a path parameter.
# ---------------------------------------------------------------------------

def _get_definitions_dir(orch) -> Path:
    """Resolve the absolute path to the module definitions directory."""
    return orch.config.storage.data_dir / "modules"


class ModuleDefinitionsResponse(BaseModel):
    modules: list[dict[str, Any]]
    project_folder_structure: list[str]


class ModuleDefinitionsSaveRequest(BaseModel):
    modules: list[dict[str, Any]]
    project_folder_structure: list[str] = []


@router.get("/definitions/all", response_model=ModuleDefinitionsResponse)
def get_module_definitions(_orch=Depends(get_orchestrator)):
    """Return the full blueprint JSON for every module in execution order."""
    defs_dir = _get_definitions_dir(_orch)

    raw: list[dict[str, Any]] = []
    if defs_dir.exists():
        for path in sorted(defs_dir.glob("mod-*.json")):
            try:
                raw.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                pass

    # Fall back to DB definition_json when no JSON files exist on disk
    if not raw:
        from ...storage.module_repo import ModuleRepository
        mod_repo = ModuleRepository(_orch.db.conn)
        for rec in mod_repo.get_all():
            if rec.definition_json:
                try:
                    raw.append(json.loads(rec.definition_json))
                except Exception:
                    pass

    raw.sort(key=lambda m: (
        int(m.get("module_id", "mod-999").split("-")[-1]),
    ))

    struct_path = defs_dir / "_project_structure.json"
    project_structure: list[str] = []
    if struct_path.exists():
        try:
            project_structure = json.loads(struct_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    return ModuleDefinitionsResponse(modules=raw, project_folder_structure=project_structure)


@router.put("/definitions/all", response_model=ModuleDefinitionsResponse)
def save_module_definitions(body: ModuleDefinitionsSaveRequest, _orch=Depends(get_orchestrator)):
    """Persist edited module definitions back to disk (from HITL editor)."""
    defs_dir = _get_definitions_dir(_orch)
    defs_dir.mkdir(parents=True, exist_ok=True)

    new_ids = {m.get("module_id") for m in body.modules if m.get("module_id")}
    for existing in defs_dir.glob("mod-*.json"):
        if existing.stem not in new_ids:
            existing.unlink()

    for mod in body.modules:
        mod_id = mod.get("module_id")
        if not mod_id:
            continue
        path = defs_dir / f"{mod_id}.json"
        path.write_text(json.dumps(mod, indent=2, ensure_ascii=False), encoding="utf-8")

    if body.project_folder_structure:
        struct_path = defs_dir / "_project_structure.json"
        struct_path.write_text(
            json.dumps(body.project_folder_structure, indent=2),
            encoding="utf-8",
        )

    return get_module_definitions(_orch)


# ---------------------------------------------------------------------------
# Module summary routes (DB records)
# ---------------------------------------------------------------------------

@router.get("", response_model=list[ModuleResponse])
def list_modules(orch=Depends(get_orchestrator)):
    repo = ModuleRepository(orch.db.conn)
    modules = repo.get_all()
    pr_map = _build_pr_map(orch)
    return [
        ModuleResponse(
            id=m.id, name=m.name, feature_name=m.feature_name,
            status=m.status.value, dependency_ids=m.dependency_ids,
            version=m.version, execution_order=m.execution_order,
            created_at=m.created_at, updated_at=m.updated_at,
            pr_number=pr_map.get(m.id, (None, ""))[0],
            pr_url=pr_map.get(m.id, (None, ""))[1],
        )
        for m in modules
    ]


@router.get("/{module_id}", response_model=ModuleResponse)
def get_module(module_id: str, orch=Depends(get_orchestrator)):
    repo = ModuleRepository(orch.db.conn)
    m = repo.get(module_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Module not found")
    pr_map = _build_pr_map(orch)
    pr_num, pr_url = pr_map.get(module_id, (None, ""))
    return ModuleResponse(
        id=m.id, name=m.name, feature_name=m.feature_name,
        status=m.status.value, dependency_ids=m.dependency_ids,
        version=m.version, execution_order=m.execution_order,
        created_at=m.created_at, updated_at=m.updated_at,
        pr_number=pr_num, pr_url=pr_url,
    )


@router.get("/{module_id}/iterations", response_model=list[IterationResponse])
def get_module_iterations(module_id: str, orch=Depends(get_orchestrator)):
    repo = IterationRepository(orch.db.conn)
    iters = repo.get_for_module(module_id)
    return [
        IterationResponse(
            id=it.id, module_id=it.module_id,
            iteration_number=it.iteration_number,
            status=it.status.value, prompt_path=it.prompt_path,
            review_json_path=it.review_json_path,
            summary_path=it.summary_path, token_usage=it.token_usage,
            started_at=it.started_at, completed_at=it.completed_at,
        )
        for it in iters
    ]


# ---------------------------------------------------------------------------
# Module detail — definition JSON + prompts + reviews (for module card modal)
# ---------------------------------------------------------------------------

class PromptEntry(BaseModel):
    iteration: int
    content: str


class ReviewEntry(BaseModel):
    iteration: int
    content: Dict[str, Any]


class ModuleDetailResponse(BaseModel):
    module: ModuleResponse
    definition: Optional[Dict[str, Any]] = None
    prompts: List[PromptEntry] = []
    reviews: List[ReviewEntry] = []
    iterations: List[IterationResponse] = []


@router.get("/{module_id}/detail", response_model=ModuleDetailResponse)
def get_module_detail(module_id: str, orch=Depends(get_orchestrator)):
    """Full detail view for a single module: definition, prompts, reviews, iterations."""
    mod_repo = ModuleRepository(orch.db.conn)
    m = mod_repo.get(module_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Module not found")

    pr_map = _build_pr_map(orch)
    pr_num, pr_url = pr_map.get(module_id, (None, ""))
    module_resp = ModuleResponse(
        id=m.id, name=m.name, feature_name=m.feature_name,
        status=m.status.value, dependency_ids=m.dependency_ids,
        version=m.version, execution_order=m.execution_order,
        created_at=m.created_at, updated_at=m.updated_at,
        pr_number=pr_num, pr_url=pr_url,
    )

    data_dir = orch.config.storage.data_dir

    # Module definition JSON — try file first, fall back to DB
    definition: dict[str, Any] | None = None
    def_path = data_dir / "modules" / f"{module_id}.json"
    if def_path.exists():
        try:
            definition = json.loads(def_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    if definition is None and m.definition_json:
        try:
            definition = json.loads(m.definition_json)
        except Exception:
            pass

    # Iteration records from DB (needed for fallback prompt/review content)
    iter_repo = IterationRepository(orch.db.conn)
    iters = iter_repo.get_for_module(module_id)

    # All prompts for this module — try files first, fall back to DB
    prompts: list[PromptEntry] = []
    prompts_dir = data_dir / "prompts" / f"module-{module_id}"
    seen_prompt_iters: set[int] = set()
    if prompts_dir.exists():
        for pf in sorted(prompts_dir.glob("iteration-*.md")):
            try:
                iter_num = int(pf.stem.split("-")[-1])
                content = pf.read_text(encoding="utf-8")
                prompts.append(PromptEntry(iteration=iter_num, content=content))
                seen_prompt_iters.add(iter_num)
            except Exception:
                pass
    # Fill from DB for iterations not found on disk
    for it in iters:
        if it.iteration_number not in seen_prompt_iters and it.prompt_content:
            prompts.append(PromptEntry(iteration=it.iteration_number, content=it.prompt_content))
    prompts.sort(key=lambda p: p.iteration)

    # All review JSONs for this module — try files first, fall back to DB
    reviews: list[ReviewEntry] = []
    reviews_dir = data_dir / "reviews" / module_id
    seen_review_iters: set[int] = set()
    if reviews_dir.exists():
        for rf in sorted(reviews_dir.glob("iteration-*.json")):
            try:
                iter_num = int(rf.stem.split("-")[-1])
                content = json.loads(rf.read_text(encoding="utf-8"))
                reviews.append(ReviewEntry(iteration=iter_num, content=content))
                seen_review_iters.add(iter_num)
            except Exception:
                pass
    # Fill from DB for iterations not found on disk
    for it in iters:
        if it.iteration_number not in seen_review_iters and it.review_content:
            try:
                content = json.loads(it.review_content)
                reviews.append(ReviewEntry(iteration=it.iteration_number, content=content))
            except Exception:
                pass
    reviews.sort(key=lambda r: r.iteration)

    iterations = [
        IterationResponse(
            id=it.id, module_id=it.module_id,
            iteration_number=it.iteration_number,
            status=it.status.value, prompt_path=it.prompt_path,
            review_json_path=it.review_json_path,
            summary_path=it.summary_path, token_usage=it.token_usage,
            started_at=it.started_at, completed_at=it.completed_at,
        )
        for it in iters
    ]

    return ModuleDetailResponse(
        module=module_resp,
        definition=definition,
        prompts=prompts,
        reviews=reviews,
        iterations=iterations,
    )
