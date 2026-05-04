"""Agents routes — CRUD for agent identity files and registry mapping."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ...agents.store import (
    AGENT_FILES,
    AgentIdentityStore,
    AgentNotFoundError,
    AgentRegistry,
)
from ..schemas import (
    AgentDetailResponse,
    AgentFileResponse,
    AgentListResponse,
    AgentRegistryResponse,
    CreateAgentRequest,
    UpdateAgentFileRequest,
    UpdateRegistryRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agents", tags=["agents"])

_AGENTS_DIR = Path(__file__).resolve().parents[3] / "agents"


def _store() -> AgentIdentityStore:
    return AgentIdentityStore(_AGENTS_DIR)


def _registry() -> AgentRegistry:
    return AgentRegistry(_AGENTS_DIR / "registry.json")


# ---------------------------------------------------------------------------
# List all agents
# ---------------------------------------------------------------------------


@router.get("", response_model=AgentListResponse)
def list_agents():
    """Return metadata for every agent (built-in and custom)."""
    agents = _store().list_agents()
    return AgentListResponse(agents=agents)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@router.get("/registry", response_model=AgentRegistryResponse)
def get_registry():
    """Return the current pipeline-post → agent mapping."""
    return AgentRegistryResponse(mapping=_registry().get_registry())


@router.put("/registry", response_model=AgentRegistryResponse)
def update_registry(body: UpdateRegistryRequest):
    """Update one or more pipeline-post → agent mappings."""
    reg = _registry()
    reg.update_registry(body.mapping)
    return AgentRegistryResponse(mapping=reg.get_registry())


# ---------------------------------------------------------------------------
# Single agent — read all files
# ---------------------------------------------------------------------------


@router.get("/{agent_name:path}", response_model=AgentDetailResponse)
def get_agent(agent_name: str):
    """Return all file contents for a single agent."""
    try:
        files = _store().get_agent(agent_name)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AgentDetailResponse(
        name=agent_name,
        files=files,
        is_builtin=agent_name.split("/")[-1] in {"module_maker", "prompt_generator", "code_generator", "code_reviewer"},
    )


# ---------------------------------------------------------------------------
# Single agent file — read / write
# ---------------------------------------------------------------------------


@router.get("/{agent_name:path}/{file_name}", response_model=AgentFileResponse)
def get_agent_file(agent_name: str, file_name: str):
    """Return the content of a single .md file for an agent."""
    if file_name not in AGENT_FILES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid file '{file_name}'. Valid files: {list(AGENT_FILES)}",
        )
    try:
        content = _store().get_file(agent_name, file_name)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AgentFileResponse(agent_name=agent_name, file_name=file_name, content=content)


@router.put("/{agent_name:path}/{file_name}", response_model=AgentFileResponse)
def update_agent_file(agent_name: str, file_name: str, body: UpdateAgentFileRequest):
    """Overwrite a single .md file for an agent."""
    if file_name not in AGENT_FILES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid file '{file_name}'. Valid files: {list(AGENT_FILES)}",
        )
    try:
        _store().update_file(agent_name, file_name, body.content)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AgentFileResponse(agent_name=agent_name, file_name=file_name, content=body.content)


# ---------------------------------------------------------------------------
# Custom agent lifecycle
# ---------------------------------------------------------------------------


@router.post("", response_model=AgentDetailResponse, status_code=201)
def create_agent(body: CreateAgentRequest):
    """Create a new custom agent with optional initial file contents."""
    try:
        _store().create_agent(body.name, body.files or {})
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    files = _store().get_agent(f"custom/{body.name}")
    return AgentDetailResponse(name=f"custom/{body.name}", files=files, is_builtin=False)


@router.delete("/{agent_name}", status_code=204)
def delete_agent(agent_name: str):
    """Delete a custom agent. Built-in agents cannot be deleted."""
    try:
        _store().delete_agent(agent_name)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
