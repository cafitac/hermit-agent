from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from hermit_agent.llm_client import LLMResponse, StreamChunk
from hermit_agent.interactive_prompts import create_interactive_prompt
from hermit_agent.permissions import PermissionMode
from hermit_agent.session_store import SessionStore


class _DummyAgent:
    MAX_TURNS = 50  # class default — same as AgentLoop

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.messages = []
        self.turn_count = 0
        self.session_id = kwargs["session_id"]
        self.session_kind = kwargs["session_kind"]


class _ScriptedLLM:
    def __init__(self, responses: list[str]):
        self.model = "glm-5.1"
        self._responses = list(responses)
        self.session_logger = None
        self._cancel_event = None

    def chat(self, *args, **kwargs) -> LLMResponse:
        return LLMResponse(content="ACK", tool_calls=[])

    def chat_stream(self, *args, **kwargs):
        text = self._responses.pop(0)
        yield StreamChunk(type="text", text=text)
        yield StreamChunk(type="done")


def test_create_interactive_session_runtime_persists_empty_transcript(tmp_path):
    from hermit_agent.gateway.interactive_session_runtime import create_interactive_session_runtime

    store = SessionStore(root=str(tmp_path / "logs"))
    llm = SimpleNamespace(model="glm-5.1")

    runtime = create_interactive_session_runtime(
        session_id="interactive-1",
        cwd="/tmp/project",
        llm=llm,
        tools=[],
        store=store,
        agent_factory=_DummyAgent,
    )

    meta = store.get_meta(runtime.session_dir)
    messages = json.loads((Path(runtime.session_dir) / "messages.json").read_text(encoding="utf-8"))

    assert meta["mode"] == "interactive"
    assert meta["status"] == "active"
    assert meta["turn_count"] == 0
    assert meta["preview"] == ""
    assert runtime.agent.session_kind == "interactive"
    assert messages == []


def test_load_interactive_session_runtime_reconstructs_messages_and_turn_count(tmp_path):
    from hermit_agent.gateway.interactive_session_runtime import (
        create_interactive_session_runtime,
        load_interactive_session_runtime,
    )

    store = SessionStore(root=str(tmp_path / "logs"))
    llm = SimpleNamespace(model="glm-5.1")

    created = create_interactive_session_runtime(
        session_id="interactive-2",
        cwd="/tmp/project",
        llm=llm,
        tools=[],
        store=store,
        parent_session_id="parent-1",
        permission_mode=PermissionMode.ACCEPT_EDITS,
        agent_factory=_DummyAgent,
    )
    created.agent.messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "world"},
    ]
    created.agent.turn_count = 2
    created.persist(status="completed")

    loaded = load_interactive_session_runtime(
        session_id="interactive-2",
        cwd="/tmp/project",
        llm=llm,
        tools=[],
        store=store,
        permission_mode=PermissionMode.ACCEPT_EDITS,
        agent_factory=_DummyAgent,
    )

    assert loaded.agent.messages == created.agent.messages
    assert loaded.agent.turn_count == 2
    assert loaded.agent.session_id == "interactive-2"
    assert loaded.parent_session_id == "parent-1"
    assert loaded.status == "completed"


def test_interactive_session_runtime_sets_unlimited_max_turns(tmp_path):
    """Interactive sessions must not be limited by the 50-turn CLI default.
    Compaction handles long sessions; turn limit should be effectively disabled."""
    from hermit_agent.gateway.interactive_session_runtime import create_interactive_session_runtime

    store = SessionStore(root=str(tmp_path / "logs"))
    llm = SimpleNamespace(model="glm-5.1")

    runtime = create_interactive_session_runtime(
        session_id="interactive-turns",
        cwd="/tmp/project",
        llm=llm,
        tools=[],
        store=store,
        agent_factory=_DummyAgent,
    )

    assert runtime.agent.MAX_TURNS >= 500, (
        f"Interactive session MAX_TURNS should be >= 500 (got {runtime.agent.MAX_TURNS}); "
        "use compaction for long sessions, not turn limits"
    )


def test_interactive_session_runtime_waiting_prompt_uses_snapshot_and_persists_status(tmp_path):
    from hermit_agent.gateway.interactive_session_runtime import create_interactive_session_runtime

    store = SessionStore(root=str(tmp_path / "logs"))
    llm = SimpleNamespace(model="glm-5.1")
    runtime = create_interactive_session_runtime(
        session_id="interactive-3",
        cwd="/tmp/project",
        llm=llm,
        tools=[],
        store=store,
        agent_factory=_DummyAgent,
    )
    runtime.agent.messages = [{"role": "user", "content": "need input"}]
    runtime.agent.turn_count = 1

    prompt = create_interactive_prompt(
        task_id="interactive-3",
        question="Which environment should we use?",
        options=["staging", "prod"],
        prompt_kind="waiting",
        tool_name="ask",
        method="item/tool/requestUserInput",
    )

    snapshot = runtime.set_waiting_prompt(prompt)
    meta = store.get_meta(runtime.session_dir)

    assert snapshot == {
        "question": "Which environment should we use?",
        "options": ["staging", "prod"],
        "tool_name": "ask",
        "method": "item/tool/requestUserInput",
    }
    assert runtime.waiting_prompt == prompt
    assert meta["status"] == "waiting"
    assert meta["turn_count"] == 1
    assert meta["preview"] == "need input"

    runtime.clear_waiting_prompt(status="active")
    assert runtime.waiting_prompt is None
    assert store.get_meta(runtime.session_dir)["status"] == "active"


def test_session_recap_saved_to_meta_after_completion(tmp_path):
    """After a session completes with turn_count >= 3, meta.json must have a 'recap' field."""
    import json
    from pathlib import Path
    from unittest.mock import patch

    from hermit_agent.gateway.interactive_session_runtime import (
        create_interactive_session_runtime,
        submit_interactive_turn,
    )

    store = SessionStore(root=str(tmp_path / "logs"))
    llm = _ScriptedLLM(["turn1", "turn2", "turn3"])

    runtime = create_interactive_session_runtime(
        session_id="interactive-recap",
        cwd=str(tmp_path),
        llm=llm,
        store=store,
    )

    # Simulate 3 turns so recap threshold is met
    runtime.agent.turn_count = 3
    runtime.agent.messages = [
        {"role": "user", "content": "GLM 3자 토론 시작해줘"},
        {"role": "assistant", "content": "알겠습니다. 토론을 시작합니다."},
        {"role": "user", "content": "계속해줘"},
        {"role": "assistant", "content": "토론 계속 진행중..."},
        {"role": "user", "content": "정리해줘"},
        {"role": "assistant", "content": "토론 요약: ..."},
    ]

    with patch(
        "hermit_agent.gateway.interactive_session_runtime._generate_session_recap",
        return_value="GLM 3자 토론 세션. AI 모델 간 주제 토론 진행 및 정리 완료.",
    ):
        submit_interactive_turn(runtime, "마무리")
        assert runtime.current_thread is not None
        runtime.current_thread.join(timeout=5)
        # Wait briefly for the async recap thread
        import time
        time.sleep(0.3)

    meta = json.loads((Path(runtime.session_dir) / "meta.json").read_text(encoding="utf-8"))
    assert "recap" in meta, "meta.json must have 'recap' field after session completion"
    assert "GLM" in meta["recap"], "recap must contain the session summary"


def test_interactive_session_resume_filters_zero_turn_sessions(tmp_path):
    """Sessions with 0 turns must not appear in the /resume picker."""
    import time
    from types import SimpleNamespace
    from unittest.mock import patch

    from hermit_agent.gateway.interactive_session_runtime import (
        create_interactive_session_runtime,
        submit_interactive_turn,
    )

    store = SessionStore(root=str(tmp_path / "logs"))

    class FakeEmpty:
        session_id = "empty000"
        turn_count = 0
        updated_at = time.time() - 100
        preview = ""

    class FakeReal:
        session_id = "real1234"
        turn_count = 3
        updated_at = time.time() - 200
        preview = "some work"

    runtime = create_interactive_session_runtime(
        session_id="interactive-filter",
        cwd=str(tmp_path),
        llm=SimpleNamespace(model="glm-5.1"),
        store=store,
        agent_factory=_DummyAgent,
    )

    captured_options: list[list] = []

    def _capture_publish(session_id, event):
        if event.type == "waiting":
            captured_options.append(list(event.options))

    import hermit_agent.gateway.interactive_session_runtime as _rt_mod
    original = _rt_mod.sse_manager.publish_threadsafe

    _rt_mod.sse_manager.publish_threadsafe = _capture_publish
    runtime.reply_queue.put("Cancel")

    try:
        with patch("hermit_agent.session.list_sessions", return_value=[FakeEmpty(), FakeReal()]):
            submit_interactive_turn(runtime, "/resume")
            runtime.current_thread.join(timeout=5)
    finally:
        _rt_mod.sse_manager.publish_threadsafe = original

    assert captured_options, "waiting SSE event was not published"
    options = captured_options[0]
    assert not any("empty000" in o for o in options), "0-turn session must not appear in resume list"
    assert any("real1234" in o for o in options), "non-zero turn session must appear in resume list"


def test_interactive_session_cleanup_zero_turn_on_done(tmp_path):
    """A completed interactive session with 0 turns must not persist to disk."""
    from pathlib import Path

    from hermit_agent.gateway.interactive_session_runtime import (
        create_interactive_session_runtime,
    )

    store = SessionStore(root=str(tmp_path / "logs"))
    llm = _ScriptedLLM(["ACK"])

    runtime = create_interactive_session_runtime(
        session_id="interactive-zero",
        cwd=str(tmp_path),
        llm=llm,
        store=store,
    )

    session_dir = Path(runtime.session_dir)
    assert session_dir.exists(), "session dir created at startup"

    # Complete session without any turns (never call submit_interactive_turn)
    runtime.persist(status="completed")

    assert not session_dir.exists(), (
        "session directory must be deleted when turn_count == 0 and session completes"
    )


def test_interactive_session_resume_shows_selection_prompt_and_handles_cancel(tmp_path):
    """'/resume' with no args must show an interactive selection prompt (not just print text).
    Cancel reply must complete without error."""
    import time
    from types import SimpleNamespace
    from unittest.mock import patch

    from hermit_agent.gateway.interactive_session_runtime import (
        create_interactive_session_runtime,
        submit_interactive_turn,
    )

    store = SessionStore(root=str(tmp_path / "logs"))

    class FakeSession:
        session_id = "abc123def456"
        turn_count = 5
        updated_at = time.time() - 3600
        preview = "test preview"

    runtime = create_interactive_session_runtime(
        session_id="interactive-resume",
        cwd=str(tmp_path),
        llm=SimpleNamespace(model="glm-5.1"),
        store=store,
        agent_factory=_DummyAgent,
    )

    # Pre-populate reply so the blocking queue.get() returns immediately
    runtime.reply_queue.put("Cancel")

    with patch("hermit_agent.session.list_sessions", return_value=[FakeSession()]):
        submit_interactive_turn(runtime, "/resume")
        assert runtime.current_thread is not None
        runtime.current_thread.join(timeout=5)

    assert runtime.status == "completed"
    assert runtime.waiting_prompt is None
    # If the interactive selector was triggered, it consumed "Cancel" from the reply_queue.
    # If not triggered, the reply_queue still contains the unconsumed "Cancel".
    assert runtime.reply_queue.empty(), (
        "reply_queue was not consumed — /resume did not show an interactive selection prompt"
    )


def test_interactive_session_slash_command_intercepted_without_calling_llm(tmp_path):
    """Slash commands must be intercepted before reaching the LLM.
    Built-in commands like /help must return a result without any LLM call."""
    from hermit_agent.gateway.interactive_session_runtime import (
        create_interactive_session_runtime,
        submit_interactive_turn,
    )

    store = SessionStore(root=str(tmp_path / "logs"))

    class _NeverCallLLM:
        model = "glm-5.1"
        session_logger = None
        _cancel_event = None

        def chat_stream(self, *args, **kwargs):
            raise AssertionError("LLM must not be called for built-in slash commands")

    llm = _NeverCallLLM()

    class _CapturingAgent(_DummyAgent):
        def run(self, message: str) -> str:
            if message:
                raise AssertionError(f"agent.run() must not be called with message for built-in slash commands, got: {message!r}")
            return ""

    runtime = create_interactive_session_runtime(
        session_id="interactive-slash",
        cwd=str(tmp_path),
        llm=llm,
        store=store,
        agent_factory=_CapturingAgent,
    )

    submit_interactive_turn(runtime, "/help")
    assert runtime.current_thread is not None
    runtime.current_thread.join(timeout=5)

    assert runtime.status == "completed"
    assert len(runtime.agent.messages) == 0, "LLM messages must be empty for built-in slash commands"


def test_interactive_session_runtime_persists_simple_text_turns_with_real_agentloop(tmp_path):
    from hermit_agent.gateway.interactive_session_runtime import (
        create_interactive_session_runtime,
        submit_interactive_turn,
    )

    store = SessionStore(root=str(tmp_path / "logs"))
    llm = _ScriptedLLM(["ACK"])
    runtime = create_interactive_session_runtime(
        session_id="interactive-real-1",
        cwd=str(tmp_path),
        llm=llm,
        store=store,
    )

    submit_interactive_turn(runtime, "Remember kiwi. Reply with ACK.")
    assert runtime.current_thread is not None
    runtime.current_thread.join(timeout=5)

    assert len(runtime.agent.messages) == 2
    assert runtime.agent.messages[0]["role"] == "user"
    assert "Remember kiwi. Reply with ACK." in runtime.agent.messages[0]["content"]
    assert runtime.agent.messages[1] == {"role": "assistant", "content": "ACK"}
    persisted = json.loads((Path(runtime.session_dir) / "messages.json").read_text(encoding="utf-8"))
    assert persisted == runtime.agent.messages
    assert "Remember kiwi. Reply with ACK." in store.get_meta(runtime.session_dir)["preview"]
