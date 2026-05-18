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
    _GENERIC_TITLES = {"imported requirements", "general", "imported features", ""}
    try:
        import re as _re
        import yaml as _yaml
        from collections import Counter as _Counter

        raw = _yaml.safe_load(Path(req_path).read_text(encoding="utf-8"))
        epics = (raw or {}).get("epics", [])
        title = ""
        if epics:
            epic_title = (epics[0].get("title", "") or "").strip()
            if epic_title.lower() not in _GENERIC_TITLES:
                title = epic_title
            else:
                _STOP_WORDS = {
                    "a", "an", "the", "and", "or", "of", "to", "in", "for",
                    "is", "as", "so", "that", "can", "be", "with", "on", "by",
                    "i", "my", "we", "our", "from", "its", "it", "at", "all",
                    "view", "manage", "create", "update", "delete", "get",
                    "want", "should", "display", "show", "see", "add", "set",
                    "list", "allow", "able", "user", "system", "using", "use",
                }
                words: list[str] = []
                for ep in epics:
                    for feat in ep.get("features", []):
                        for story in feat.get("stories", []):
                            st = (story.get("title", "") or "").strip()
                            if st:
                                for w in _re.findall(r"[a-zA-Z]{3,}", st):
                                    wl = w.lower()
                                    if wl not in _STOP_WORDS:
                                        words.append(wl)
                if words:
                    top = [w for w, _ in _Counter(words).most_common(5)][:3]
                    title = " ".join(w.capitalize() for w in top)

        if title:
            ctx.config.project.name = title
            slug = _re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
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


def _stub(ctx: HandlerContext) -> None:
    logger.info("Stub handler for state: %s", ctx.state_mgr.state.status.value)


# Handler registry: state → function
HANDLER_REGISTRY: dict[PipelineStatus, object] = {
    PipelineStatus.IDLE: handle_idle,
    PipelineStatus.LOADING_REQUIREMENTS: handle_loading_requirements,
    PipelineStatus.PROMPT_GENERATION: _stub,
    PipelineStatus.HITL_PROMPT_REVIEW: _stub,
    PipelineStatus.CODE_GENERATION: _stub,
    PipelineStatus.CODE_REVIEW: _stub,
    PipelineStatus.HITL_REVIEW_DECISION: _stub,
}
