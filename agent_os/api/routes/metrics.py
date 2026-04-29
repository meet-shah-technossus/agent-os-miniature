"""Metrics routes — aggregate pipeline metrics and budget info."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...hardening.token_budget import TokenBudgetTracker
from ...storage.iteration_repo import IterationRepository
from ...storage.models import ModuleStatus
from ...storage.module_repo import ModuleRepository
from ..deps import get_orchestrator
from ..schemas import MetricsResponse, ModuleBudgetResponse

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("", response_model=MetricsResponse)
def get_metrics(orch=Depends(get_orchestrator)):
    mod_repo = ModuleRepository(orch.db.conn)
    iter_repo = IterationRepository(orch.db.conn)
    modules = mod_repo.get_all()
    state = orch.state_mgr.state

    total_iterations = 0
    total_tokens = 0
    for m in modules:
        iters = iter_repo.get_for_module(m.id)
        total_iterations += len(iters)
        total_tokens += sum(it.token_usage for it in iters)

    cost_per_1k = orch.config.budget.cost_per_1k_tokens
    total_cost = (total_tokens / 1000.0) * cost_per_1k

    return MetricsResponse(
        total_modules=len(modules),
        completed_modules=sum(1 for m in modules if m.status == ModuleStatus.COMPLETED),
        failed_modules=sum(1 for m in modules if m.status == ModuleStatus.FAILED),
        total_iterations=total_iterations,
        total_token_usage=total_tokens,
        pipeline_status=state.pipeline_status.value,
        total_cost=round(total_cost, 4),
        budget_per_module=orch.config.budget.token_budget_per_module,
    )


@router.get("/budget/{module_id}", response_model=ModuleBudgetResponse)
def get_module_budget(module_id: str, orch=Depends(get_orchestrator)):
    iter_repo = IterationRepository(orch.db.conn)
    tracker = TokenBudgetTracker(
        config=orch.config.budget,
        iter_repo=iter_repo,
        bus=orch.bus,
    )
    summary = tracker.get_summary(module_id)
    return ModuleBudgetResponse(**summary)
