from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from hermit_agent.agent_session import AgentSessionBase
from hermit_agent.loop_commands._workflow import cmd_learn
from hermit_agent.permissions import PermissionMode


class ConcreteSession(AgentSessionBase):
    def _setup_tools(self) -> list:
        return []

    def _execute(self, prompt: str) -> str | None:
        return prompt


def _session_for(cwd: Path) -> AgentSessionBase:
    return ConcreteSession(
        llm=MagicMock(),
        cwd=str(cwd),
        permission_mode=PermissionMode.ALLOW_READ,
    )


def test_prepare_prompt_does_not_fallback_to_legacy_learner_skills(tmp_path: Path) -> None:
    legacy_approved = tmp_path / ".hermit" / "skills" / "learned-feedback" / "approved"
    legacy_approved.mkdir(parents=True)
    (legacy_approved / "legacy.md").write_text(
        "---\nname: legacy\ntriggers: []\n---\n\nLegacy rule must not be injected\n",
        encoding="utf-8",
    )

    prompt = _session_for(tmp_path)._prepare_prompt("do the task")

    assert prompt == "do the task"
    assert "Legacy rule must not be injected" not in prompt


def test_prepare_prompt_still_uses_agent_learner_v2_rules_file(tmp_path: Path) -> None:
    rules_dir = tmp_path / ".hermit" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "agent-learned.md").write_text("Prefer v2 learned rules", encoding="utf-8")

    prompt = _session_for(tmp_path)._prepare_prompt("do the task")

    assert "<learned_feedback>" in prompt
    assert "Prefer v2 learned rules" in prompt
    assert prompt.endswith("do the task")


def test_learn_slash_command_points_to_agent_learner_v2_instead_of_legacy_runtime() -> None:
    agent = SimpleNamespace(llm=MagicMock(), cwd="/tmp/demo", messages=[], _tool_call_count=0)

    result = cmd_learn(agent, "status")

    assert "agent-learner" in result
    assert "legacy" not in result.lower()
    agent.llm.chat.assert_not_called()


def test_runtime_paths_do_not_import_legacy_learner() -> None:
    agent_session_source = Path("hermit_agent/agent_session.py").read_text(encoding="utf-8")
    workflow_source = Path("hermit_agent/loop_commands/_workflow.py").read_text(encoding="utf-8")

    assert "from .learner import Learner" not in agent_session_source
    assert "from ..learner import" not in workflow_source
    assert "Learner(" not in workflow_source
