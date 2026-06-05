"""Project naming service — derives project name from requirements YAML.

Consolidates the duplicate project-name derivation logic that was in both
engine.py and handlers.py.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path
from typing import Optional

from ..constants import PROJECT_NAME_STOP_WORDS

logger = logging.getLogger(__name__)

_GENERIC_TITLES = frozenset({"imported requirements", "general", "imported features", ""})


def derive_name(requirements_path: str | Path) -> tuple[str, str]:
    """Derive a project name and slug from requirements YAML.

    Args:
        requirements_path: Path to the requirements YAML file.

    Returns:
        Tuple of (human_title, slug).
        Falls back to ("Agent OS Project", "agent-os-project") on failure.
    """
    try:
        import yaml

        raw_text = Path(requirements_path).read_text(encoding="utf-8")
        suffix = Path(requirements_path).suffix.lower()

        if suffix == ".md":
            md_match = re.search(r"```yaml\s*\n(.*?)\n```", raw_text, re.DOTALL)
            parsed = yaml.safe_load(md_match.group(1)) if md_match else {}
        else:
            parsed = yaml.safe_load(raw_text)

        epics = (parsed or {}).get("epics", [])
        title = _derive_title_from_epics(epics)

        if not title:
            title = "Agent OS Project"

        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        return title, slug

    except Exception:
        logger.warning("Could not extract project name from requirements", exc_info=True)
        return "Agent OS Project", "agent-os-project"


def _derive_title_from_epics(epics: list) -> str:
    """Extract a meaningful project title from epics structure."""
    if not epics:
        return ""

    epic_title = (epics[0].get("title", "") or "").strip()
    if epic_title.lower() not in _GENERIC_TITLES:
        return epic_title

    # Epic title is generic — derive from story titles using word frequency
    words: list[str] = []
    for ep in epics:
        for feat in ep.get("features", []):
            for story in feat.get("stories", []):
                st = (story.get("title", "") or "").strip()
                if st:
                    for w in re.findall(r"[a-zA-Z]{3,}", st):
                        wl = w.lower()
                        if wl not in PROJECT_NAME_STOP_WORDS:
                            words.append(wl)

    if words:
        top = [w for w, _ in Counter(words).most_common(5)][:3]
        return " ".join(w.capitalize() for w in top)

    return ""
