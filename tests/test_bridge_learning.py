from __future__ import annotations

from types import SimpleNamespace


def test_schedule_bridge_post_task_learning_skips_gateway_like_sessions(monkeypatch):
    from hermit_agent.bridge_learning import schedule_bridge_post_task_learning

    called = {"thread": 0}

    class _Thread:
        def __init__(self, target=None, daemon=None):
            called["thread"] += 1
        def start(self):
            called["thread"] += 100

    monkeypatch.setattr("threading.Thread", _Thread)

    agent = SimpleNamespace(llm=object(), cwd="/tmp", messages=[])
    schedule_bridge_post_task_learning(agent, session_kind="gateway")
    schedule_bridge_post_task_learning(agent, session_kind="mcp")

    assert called["thread"] == 0


def test_schedule_bridge_post_task_learning_runs_learner_and_kb(monkeypatch):
    from hermit_agent.bridge_learning import schedule_bridge_post_task_learning

    calls = {}

    class _Learner:
        def __init__(self, llm=None):
            self.llm = llm
        def get_active_skills(self):
            return [("skill-a", "body")]
        def record_run(self, skills, passed):
            calls["record_run"] = (skills, passed)
        def extract_from_failure(self, messages, output):
            calls["extract"] = (messages, output)
            return {"name": "rule-a"}
        def save_pending(self, skill_data):
            calls["save_pending"] = skill_data
            return "/tmp/rule-a.md"

    class _KB:
        def __init__(self, cwd=None, llm=None):
            calls["kb_init"] = (cwd, llm)
        def post_task_update(self, messages, passed):
            calls["kb_update"] = (messages, passed)

    class _Thread:
        def __init__(self, target=None, daemon=None):
            self._target = target
        def start(self):
            self._target()

    monkeypatch.setattr("hermit_agent.bridge_learning._load_learner_class", lambda: _Learner)
    monkeypatch.setattr("hermit_agent.bridge_learning._load_kb_class", lambda: _KB)
    monkeypatch.setattr("hermit_agent.bridge_learning.run_pytest", lambda cwd: (False, "pytest failed"))
    monkeypatch.setattr("threading.Thread", _Thread)

    agent = SimpleNamespace(llm="llm", cwd="/tmp", messages=[{"role": "user", "content": "hi"}])
    schedule_bridge_post_task_learning(agent, session_kind="tui")

    assert calls["record_run"] == (["skill-a"], False)
    assert calls["extract"][1] == "pytest failed"
    assert calls["save_pending"] == {"name": "rule-a"}
    assert calls["kb_update"] == ([{"role": "user", "content": "hi"}], False)
