from hermit_agent.interactive_prompts import (
    build_codex_app_server_request,
    build_codex_channels_interaction,
    channel_notification_meta,
    codex_channels_interaction_kind,
    create_interactive_prompt,
    waiting_prompt_snapshot,
)


def test_create_interactive_prompt_defaults_tool_name_from_prompt_kind():
    prompt = create_interactive_prompt(
        task_id="task-1",
        question="Allow?",
        options=["Yes", "No"],
        prompt_kind="permission_ask",
    )

    assert prompt.tool_name == "bash"
    assert prompt.options == ("Yes", "No")


def test_codex_channels_interaction_kind_prefers_method_specific_mappings():
    permissions_prompt = create_interactive_prompt(
        task_id="task-2",
        question="Permissions?",
        options=["Yes", "No"],
        prompt_kind="permission_ask",
        method="item/permissions/requestApproval",
        request_id="req-2",
    )
    elicitation_prompt = create_interactive_prompt(
        task_id="task-3",
        question="Need URL",
        options=["Submit", "Cancel"],
        prompt_kind="waiting",
        method="mcpServer/elicitation/request",
        request_id="req-3",
    )

    assert codex_channels_interaction_kind(permissions_prompt) == "permissions_request"
    assert codex_channels_interaction_kind(elicitation_prompt) == "elicitation_request"


def test_prompt_helpers_build_stable_notification_and_interaction_payloads():
    prompt = create_interactive_prompt(
        task_id="task-9",
        question="Choose one",
        options=["A", "B"],
        prompt_kind="waiting",
        tool_name="ask",
        method="item/tool/requestUserInput",
        request_id="req-9",
        thread_id="thread-1",
        turn_id="turn-1",
    )

    assert waiting_prompt_snapshot(prompt) == {
        "question": "Choose one",
        "options": ["A", "B"],
        "tool_name": "ask",
        "method": "item/tool/requestUserInput",
    }
    assert channel_notification_meta(prompt) == {
        "task_id": "task-9",
        "kind": "waiting",
        "options": "A,B",
        "prompt_kind": "waiting",
        "tool_name": "ask",
    }

    interaction = build_codex_channels_interaction(prompt)
    assert interaction["kind"] == "user_input_request"
    assert interaction["codex"] == {
        "threadId": "thread-1",
        "turnId": "turn-1",
        "requestId": "req-9",
        "method": "item/tool/requestUserInput",
    }


def test_build_codex_app_server_request_preserves_params_and_injects_thread_metadata():
    prompt = create_interactive_prompt(
        task_id="task-10",
        question="Approve?",
        options=["Yes", "No"],
        prompt_kind="permission_ask",
        method="item/commandExecution/requestApproval",
        request_id="req-10",
        thread_id="thread-10",
        turn_id="turn-10",
        params={"command": "ls", "reason": "Need approval"},
    )

    assert build_codex_app_server_request(prompt) == {
        "id": "req-10",
        "method": "item/commandExecution/requestApproval",
        "params": {
            "command": "ls",
            "reason": "Need approval",
            "threadId": "thread-10",
            "turnId": "turn-10",
        },
    }
