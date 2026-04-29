"""JSON repair utility — retry invalid JSON from Codex reviewer output."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)


class JSONParseError(Exception):
    """Raised when JSON cannot be extracted or parsed after all attempts."""

    def __init__(self, raw: str, reason: str) -> None:
        self.raw = raw
        self.reason = reason
        super().__init__(f"JSON parse failed: {reason}")


def extract_json(text: str) -> Optional[dict[str, Any]]:
    """Attempt to extract a JSON object from possibly noisy Codex output.

    Strategies (in order):
    1. Direct ``json.loads`` on the full text.
    2. Find the outermost ``{ ... }`` block and parse it.
    3. Strip markdown code fences and retry.
    """
    # Strategy 1: direct parse
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass

    # Strategy 2: extract outermost braces
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            obj = json.loads(match.group(0))
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            pass

    # Strategy 3: strip markdown fences
    stripped = re.sub(r"```(?:json)?\s*", "", text)
    stripped = re.sub(r"```\s*$", "", stripped, flags=re.MULTILINE)
    try:
        obj = json.loads(stripped.strip())
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass

    return None


def repair_json_prompt(original_prompt: str, raw_output: str) -> str:
    """Build a retry prompt that instructs Codex to fix its JSON output.

    Used by the code reviewer when the original output was invalid JSON.
    """
    return (
        f"{original_prompt}\n\n"
        "IMPORTANT: Your previous response was not valid JSON. "
        "You MUST respond with ONLY a valid JSON object — no markdown, "
        "no explanations, no code fences. Start with {{ and end with }}.\n\n"
        f"Your previous (invalid) output was:\n{raw_output[:1000]}"
    )
