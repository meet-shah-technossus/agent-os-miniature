"""Framework selection and template loading for prompt generation."""

from __future__ import annotations

from pathlib import Path

from ..config.schema import PromptFramework

_TEMPLATES_DIR = Path(__file__).parent / "templates"

_FRAMEWORK_FILES: dict[PromptFramework, str] = {
    PromptFramework.RCTCF: "rctcf.md",
    PromptFramework.RISEN: "risen.md",
    PromptFramework.COSTAR: "costar.md",
    PromptFramework.CUSTOM: "custom.md",
}


def load_template(framework: PromptFramework) -> str:
    """Load the raw template string for the given framework."""
    filename = _FRAMEWORK_FILES[framework]
    path = _TEMPLATES_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Template not found: {path}")
    return path.read_text(encoding="utf-8")
