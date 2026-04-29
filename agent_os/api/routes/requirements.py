"""Requirements routes — list all requirements."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...storage.requirement_repo import RequirementRepository
from ..deps import get_orchestrator
from ..schemas import RequirementResponse

router = APIRouter(prefix="/api/requirements", tags=["requirements"])


@router.get("", response_model=list[RequirementResponse])
def list_requirements(orch=Depends(get_orchestrator)):
    repo = RequirementRepository(orch.db.conn)
    reqs = repo.get_all()
    return [
        RequirementResponse(
            id=r.id, type=r.type if isinstance(r.type, str) else r.type.value,
            parent_id=r.parent_id, title=r.title,
            description=r.description, status=r.status,
        )
        for r in reqs
    ]
