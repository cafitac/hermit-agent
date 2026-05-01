from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from hermit_agent.orchestrators import (
    AdapterHealth,
    AdapterHealthStatus,
    AdapterInstallResult,
    AdapterInstallStatus,
    InteractivePrompt,
    OrchestratorAdapter,
    PromptReply,
    TaskEvent,
    TaskEventKind,
    TaskHandle,
    TaskRequest,
)


def test_task_request_is_orchestrator_neutral_and_immutable():
    request = TaskRequest(
        task="Refactor the adapter boundary",
        cwd="/repo",
        model="gpt-5.5",
        max_turns=12,
        user="hermes",
        parent_session_id="session-1",
        metadata={"source": "test"},
    )

    assert request.task == "Refactor the adapter boundary"
    assert request.cwd == "/repo"
    assert request.model == "gpt-5.5"
    assert request.max_turns == 12
    assert request.user == "hermes"
    assert request.parent_session_id == "session-1"
    assert request.metadata == {"source": "test"}

    with pytest.raises(FrozenInstanceError):
        request.task = "mutated"  # type: ignore[misc]


def test_contract_dtos_have_stable_status_and_event_values():
    handle = TaskHandle(task_id="task-1", status="running", url="http://localhost/task-1")
    event = TaskEvent(
        task_id="task-1",
        kind=TaskEventKind.WAITING,
        message="Approve bash command?",
        payload={"tool_name": "bash"},
    )
    prompt = InteractivePrompt(
        task_id="task-1",
        question="Continue?",
        options=("yes", "no"),
        prompt_kind="permission",
        tool_name="bash",
        payload={"command": "pytest"},
    )
    reply = PromptReply(task_id="task-1", answer="yes", approved=True, payload={"reason": "ok"})
    health = AdapterHealth(
        name="hermes",
        status=AdapterHealthStatus.WARN,
        message="Hermes CLI is not installed",
        details=("install Hermes first",),
    )
    install = AdapterInstallResult(
        name="hermes",
        status=AdapterInstallStatus.UNCHANGED,
        message="hermit-channel is already registered",
        details=("hermes mcp test hermit-channel",),
        changed=False,
    )

    assert handle.task_id == "task-1"
    assert event.kind.value == "waiting"
    assert prompt.options == ("yes", "no")
    assert reply.approved is True
    assert health.status.value == "warn"
    assert install.status.value == "unchanged"
    assert install.changed is False


def test_adapter_protocol_supports_core_lifecycle_shape():
    class RecordingAdapter:
        name = "recording"

        def __init__(self) -> None:
            self.events: list[TaskEvent] = []
            self.cancelled: list[str] = []

        def install_or_print_instructions(self, *, cwd: str, fix: bool) -> AdapterInstallResult:
            return AdapterInstallResult(
                name=self.name,
                status=AdapterInstallStatus.REGISTERED if fix else AdapterInstallStatus.PRINTED,
                message=f"cwd={cwd}",
                changed=fix,
            )

        def health(self, *, cwd: str) -> AdapterHealth:
            return AdapterHealth(name=self.name, status=AdapterHealthStatus.PASS, message=cwd)

        def submit_task(self, request: TaskRequest) -> TaskHandle:
            return TaskHandle(task_id="task-1", status="submitted", url=request.cwd)

        def emit_event(self, task_id: str, event: TaskEvent) -> None:
            assert task_id == event.task_id
            self.events.append(event)

        def wait_for_reply(self, task_id: str, prompt: InteractivePrompt) -> PromptReply | None:
            return PromptReply(task_id=task_id, answer=prompt.options[0], approved=True)

        def cancel(self, task_id: str) -> None:
            self.cancelled.append(task_id)

    adapter: OrchestratorAdapter = RecordingAdapter()
    request = TaskRequest(task="Run tests", cwd="/repo")

    install = adapter.install_or_print_instructions(cwd="/repo", fix=True)
    health = adapter.health(cwd="/repo")
    handle = adapter.submit_task(request)
    event = TaskEvent(task_id=handle.task_id, kind=TaskEventKind.PROGRESS, message="started")
    prompt = InteractivePrompt(task_id=handle.task_id, question="Continue?", options=("yes",))
    adapter.emit_event(handle.task_id, event)
    reply = adapter.wait_for_reply(handle.task_id, prompt)
    adapter.cancel(handle.task_id)

    assert install.status == AdapterInstallStatus.REGISTERED
    assert health.status == AdapterHealthStatus.PASS
    assert handle.url == "/repo"
    assert reply == PromptReply(task_id="task-1", answer="yes", approved=True)
    assert isinstance(adapter, OrchestratorAdapter)
    assert adapter.cancelled == ["task-1"]
