"""Step handlers for each pipeline state — Phase 1 stub.

Phase 2+ will flesh out each handler. For now only IDLE and
LOADING_REQUIREMENTS do real work; all others are stubs.
"""

from __future__ import annotations

import logging
from pathlib import Path

from rich.console import Console

from ..storage.models import PipelineStatus
from .context import HandlerContext

logger = logging.getLogger(__name__)
console = Console()

# Absolute path to the agents directory (sibling of orchestrator/)
_AGENTS_DIR = Path(__file__).resolve().parents[1] / "agents"


def handle_idle(ctx: HandlerContext) -> None:
    console.print("[dim]Transitioning from IDLE → LOADING_REQUIREMENTS[/dim]")
    ctx.state_mgr.transition_to(PipelineStatus.LOADING_REQUIREMENTS)


def handle_loading_requirements(ctx: HandlerContext) -> None:
    from ..requirements.parser import RequirementsParser

    req_path = ctx.config.requirements.path
    console.print(f"[cyan]Loading requirements from: {req_path}[/cyan]")

    parser = RequirementsParser(db=ctx.db)
    stats = parser.load_and_store(req_path)

    # Derive project name from requirements content
    try:
        from ..services.project_namer import derive_name
        title, slug = derive_name(req_path)
        if title and title != "Agent OS Project":
            ctx.config.project.name = title
            ctx.config.project.repo_name = slug
            console.print(f"[green]Project name set: {ctx.config.project.name}[/green]")
    except Exception:
        logger.debug("Could not extract project name from requirements", exc_info=True)

    console.print(
        f"[green]Requirements loaded — "
        f"{stats.get('epics', 0)} epics, {stats.get('features', 0)} features, "
        f"{stats.get('stories', 0)} stories[/green]"
    )

    ctx.state_mgr.transition_to(PipelineStatus.PROMPT_GENERATION)
