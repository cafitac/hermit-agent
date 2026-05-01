from __future__ import annotations

from hermit_agent.interactive_prompts import InteractivePrompt as RuntimeInteractivePrompt
from hermit_agent.interactive_prompts import create_interactive_prompt
from hermit_agent.orchestrators import InteractivePrompt as AdapterInteractivePrompt
from hermit_agent.orchestrators import PromptReply
from hermit_agent.orchestrators.prompts import (
    adapter_prompt_to_runtime_prompt,
    prompt_reply_from_answer,
    runtime_prompt_to_adapter_prompt,
)


def test_runtime_prompt_maps_to_neutral_prompt_without_losing_metadata():
    runtime_prompt = create_interactive_prompt(
        task_id="task-1",
        question="Approve command?",
        options=["Yes", "No"],
        prompt_kind="permission_ask",
        tool_name="bash",
        method="item/commandExecution/requestApproval",
        request_id="req-1",
        thread_id="thread-1",
        turn_id="turn-1",
        params={"command": "pytest", "reason": "Need approval"},
    )

    adapter_prompt = runtime_prompt_to_adapter_prompt(runtime_prompt)

    assert isinstance(adapter_prompt, AdapterInteractivePrompt)
    assert adapter_prompt.task_id == "task-1"
    assert adapter_prompt.question == "Approve command?"
    assert adapter_prompt.options == ("Yes", "No")
    assert adapter_prompt.prompt_kind == "permission_ask"
    assert adapter_prompt.tool_name == "bash"
    assert adapter_prompt.payload == {
        "method": "item/commandExecution/requestApproval",
        "request_id": "req-1",
        "thread_id": "thread-1",
        "turn_id": "turn-1",
        "params": {"command": "pytest", "reason": "Need approval"},
    }


def test_neutral_prompt_maps_back_to_runtime_prompt_and_copies_payload_params():
    adapter_prompt = AdapterInteractivePrompt(
        task_id="task-2",
        question="Where deploy?",
        options=("staging", "prod"),
        prompt_kind="waiting",
        tool_name="deploy",
        payload={
            "method": "item/tool/requestUserInput",
            "request_id": "req-2",
            "thread_id": "thread-2",
            "turn_id": "turn-2",
            "params": {"default": "staging"},
            "extra": "kept-for-adapter-only",
        },
    )

    runtime_prompt = adapter_prompt_to_runtime_prompt(adapter_prompt)

    assert isinstance(runtime_prompt, RuntimeInteractivePrompt)
    assert runtime_prompt.task_id == "task-2"
    assert runtime_prompt.question == "Where deploy?"
    assert runtime_prompt.options == ("staging", "prod")
    assert runtime_prompt.prompt_kind == "waiting"
    assert runtime_prompt.tool_name == "deploy"
    assert runtime_prompt.method == "item/tool/requestUserInput"
    assert runtime_prompt.request_id == "req-2"
    assert runtime_prompt.thread_id == "thread-2"
    assert runtime_prompt.turn_id == "turn-2"
    assert runtime_prompt.params == {"default": "staging"}

    adapter_prompt.payload["params"]["default"] = "prod"
    assert runtime_prompt.params == {"default": "staging"}


def test_prompt_reply_from_answer_preserves_answer_and_approval_hint():
    yes_reply = prompt_reply_from_answer(task_id="task-3", answer="Yes")
    no_reply = prompt_reply_from_answer(task_id="task-3", answer="no")
    custom_reply = prompt_reply_from_answer(task_id="task-3", answer="Use staging")

    assert yes_reply == PromptReply(task_id="task-3", answer="Yes", approved=True)
    assert no_reply == PromptReply(task_id="task-3", answer="no", approved=False)
    assert custom_reply == PromptReply(task_id="task-3", answer="Use staging", approved=None)
