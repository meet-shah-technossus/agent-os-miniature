"""Configuration loading from YAML files."""

from __future__ import annotations

from pathlib import Path

import yaml

from .schema import AgentOSConfig


def load_config(config_path: str | Path) -> AgentOSConfig:
    """Load and validate configuration from a YAML file."""
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    return AgentOSConfig(**raw)


def get_default_config() -> AgentOSConfig:
    """Return config with all defaults."""
    return AgentOSConfig()
