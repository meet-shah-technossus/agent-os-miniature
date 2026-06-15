"""Unit tests for agent_os.config.loader — config loading and defaults."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from agent_os.config.loader import get_default_config, load_config
from agent_os.config.schema import AgentOSConfig, ConvergenceRule, PromptFramework


MINIMAL_YAML = textwrap.dedent("""\
    project:
      name: "Test Project"
      language: python
    orchestrator:
      max_iterations: 3
""")

FULL_YAML = textwrap.dedent("""\
    project:
      name: "Full Project"
      language: python
      root_path: "/tmp/test"
    orchestrator:
      max_iterations: 5
      auto_approve_hitl: true
      convergence_rule: no_high_severity
    git:
      enabled: false
      main_branch: "main"
    storage:
      db_path: "data/test.db"
""")


class TestGetDefaultConfig:
    def test_returns_agent_os_config(self):
        cfg = get_default_config()
        assert isinstance(cfg, AgentOSConfig)

    def test_default_max_iterations(self):
        cfg = get_default_config()
        assert cfg.orchestrator.max_iterations == 5

    def test_default_auto_approve_is_false(self):
        cfg = get_default_config()
        assert cfg.orchestrator.auto_approve_hitl is False

    def test_default_language_is_python(self):
        cfg = get_default_config()
        assert cfg.project.language == "python"

    def test_default_db_path(self):
        cfg = get_default_config()
        assert cfg.storage.db_path == "data/agent_os.db"

    def test_default_git_enabled(self):
        cfg = get_default_config()
        assert cfg.git.enabled is True

    def test_default_convergence_rule(self):
        cfg = get_default_config()
        assert cfg.orchestrator.convergence_rule == ConvergenceRule.NO_HIGH_SEVERITY


class TestLoadConfig:
    def test_load_minimal_yaml(self, tmp_path: Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(MINIMAL_YAML, encoding="utf-8")
        cfg = load_config(config_file)
        assert isinstance(cfg, AgentOSConfig)
        assert cfg.project.name == "Test Project"

    def test_load_overrides_max_iterations(self, tmp_path: Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(MINIMAL_YAML, encoding="utf-8")
        cfg = load_config(config_file)
        assert cfg.orchestrator.max_iterations == 3

    def test_load_full_yaml(self, tmp_path: Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(FULL_YAML, encoding="utf-8")
        cfg = load_config(config_file)
        assert cfg.project.name == "Full Project"
        assert cfg.orchestrator.auto_approve_hitl is True
        assert cfg.git.enabled is False
        assert cfg.storage.db_path == "data/test.db"

    def test_missing_file_raises_file_not_found(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.yaml")

    def test_empty_yaml_returns_defaults(self, tmp_path: Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("{}", encoding="utf-8")
        cfg = load_config(config_file)
        assert isinstance(cfg, AgentOSConfig)
        assert cfg.orchestrator.max_iterations == 5

    def test_accepts_path_string(self, tmp_path: Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(MINIMAL_YAML, encoding="utf-8")
        cfg = load_config(str(config_file))
        assert cfg.project.name == "Test Project"

    def test_max_iterations_bounds(self, tmp_path: Path):
        yaml_content = "orchestrator:\n  max_iterations: 25\n"
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content, encoding="utf-8")
        with pytest.raises(Exception):
            load_config(config_file)

    def test_git_main_branch_override(self, tmp_path: Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(FULL_YAML, encoding="utf-8")
        cfg = load_config(config_file)
        assert cfg.git.main_branch == "main"
