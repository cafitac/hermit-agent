"""US-001/US-002: ProjectConfigLoader and TaskStateManager class extraction."""
from __future__ import annotations

import os
from pathlib import Path


# ─── US-001: ProjectConfigLoader ────────────────────────────────────────────


def test_project_config_loader_find_config_returns_content(tmp_path):
    """ProjectConfigLoader.find_config() returns content from HERMIT.md files."""
    from hermit_agent.loop_context import ProjectConfigLoader

    hermit_md = tmp_path / "HERMIT.md"
    hermit_md.write_text("# Project Rules\nAlways test first.", encoding="utf-8")

    loader = ProjectConfigLoader(cwd=str(tmp_path))
    result = loader.find_config(depth="shallow")
    assert "Always test first." in result


def test_project_config_loader_shallow_ignores_parent(tmp_path):
    """depth='shallow' should not walk up to parent directories."""
    from hermit_agent.loop_context import ProjectConfigLoader

    parent = tmp_path
    child = tmp_path / "sub"
    child.mkdir()
    (parent / "HERMIT.md").write_text("parent content", encoding="utf-8")

    loader = ProjectConfigLoader(cwd=str(child))
    result = loader.find_config(depth="shallow")
    assert "parent content" not in result


def test_project_config_loader_deep_walks_up(tmp_path):
    """depth='deep' should walk up and include parent HERMIT.md."""
    from hermit_agent.loop_context import ProjectConfigLoader

    parent = tmp_path
    child = tmp_path / "sub"
    child.mkdir()
    (parent / "HERMIT.md").write_text("parent config", encoding="utf-8")

    loader = ProjectConfigLoader(cwd=str(child))
    result = loader.find_config(depth="deep")
    assert "parent config" in result


def test_project_config_loader_find_rules_loads_md_files(tmp_path):
    """ProjectConfigLoader.find_rules() loads .md files from .hermit/rules/."""
    from hermit_agent.loop_context import ProjectConfigLoader

    rules_dir = tmp_path / ".hermit" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "01-style.md").write_text("# Style\nUse snake_case.", encoding="utf-8")

    loader = ProjectConfigLoader(cwd=str(tmp_path))
    result = loader.find_rules(depth="shallow")
    assert "Use snake_case." in result


def test_module_shim_find_project_config_delegates(tmp_path):
    """_find_project_config() module function still works (backward compat)."""
    from hermit_agent.loop_context import _find_project_config

    (tmp_path / "HERMIT.md").write_text("shim test", encoding="utf-8")
    result = _find_project_config(str(tmp_path), depth="shallow")
    assert "shim test" in result


# ─── US-002: TaskStateManager ────────────────────────────────────────────────


def test_task_state_manager_path(tmp_path):
    """TaskStateManager.path() returns .hermit/task_state.md."""
    from hermit_agent.loop_context import TaskStateManager

    mgr = TaskStateManager(cwd=str(tmp_path))
    assert mgr.path() == str(tmp_path / ".hermit" / "task_state.md")


def test_task_state_manager_read_empty_when_missing(tmp_path):
    """TaskStateManager.read() returns empty string when file missing."""
    from hermit_agent.loop_context import TaskStateManager

    mgr = TaskStateManager(cwd=str(tmp_path))
    assert mgr.read() == ""


def test_task_state_manager_write_and_read(tmp_path):
    """TaskStateManager.write() creates file, read() retrieves it."""
    from hermit_agent.loop_context import TaskStateManager

    mgr = TaskStateManager(cwd=str(tmp_path))
    mgr.write(skill_name="feature-develop", args="123", skill_content="- [ ] Write tests\n- [ ] Implement")
    content = mgr.read()
    assert "feature-develop" in content
    assert "- [ ] Write tests" in content


def test_module_shim_read_task_state_delegates(tmp_path):
    """_read_task_state() module function still works (backward compat)."""
    from hermit_agent.loop_context import _read_task_state, _write_task_state

    _write_task_state(str(tmp_path), "test-skill", "arg1", "- [ ] Step 1")
    result = _read_task_state(str(tmp_path))
    assert "test-skill" in result


# ─── US-002 continued: DynamicContextBuilder ────────────────────────────────


def test_dynamic_context_builder_includes_date_and_cwd(tmp_path):
    """DynamicContextBuilder.build() includes current date and cwd."""
    from hermit_agent.loop_context import DynamicContextBuilder

    builder = DynamicContextBuilder(cwd=str(tmp_path))
    result = builder.build()
    assert "Date:" in result
    assert str(tmp_path) in result


def test_dynamic_context_builder_includes_project_meta(tmp_path):
    """DynamicContextBuilder.build() includes pyproject.toml project name."""
    from hermit_agent.loop_context import DynamicContextBuilder

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = \"my-test-project\"\ndescription = \"A test.\"\n",
        encoding="utf-8",
    )
    builder = DynamicContextBuilder(cwd=str(tmp_path))
    result = builder.build()
    assert "my-test-project" in result


def test_dynamic_context_builder_includes_top_level_layout(tmp_path):
    """DynamicContextBuilder.build() includes top-level directory entries."""
    from hermit_agent.loop_context import DynamicContextBuilder

    (tmp_path / "src").mkdir()
    (tmp_path / "README.md").write_text("# Hello", encoding="utf-8")
    builder = DynamicContextBuilder(cwd=str(tmp_path))
    result = builder.build()
    assert "src/" in result


def test_dynamic_context_builder_shim_delegates(tmp_path):
    """_build_dynamic_context() shim returns identical output to builder."""
    from hermit_agent.loop_context import DynamicContextBuilder, _build_dynamic_context

    result_direct = DynamicContextBuilder(cwd=str(tmp_path)).build()
    result_shim = _build_dynamic_context(str(tmp_path))
    assert result_direct == result_shim
