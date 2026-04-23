from hermit_agent.codex_interaction_contract import (
    CODEX_COMMAND_APPROVAL_REQUEST_METHOD,
    CODEX_ELICITATION_REQUEST_METHOD,
    CODEX_FILE_CHANGE_REQUEST_METHOD,
    CODEX_PERMISSIONS_REQUEST_METHOD,
    CODEX_USER_INPUT_REQUEST_METHOD,
    build_tool_user_input_result,
    codex_channels_interaction_kind_for_prompt,
    default_tool_name_for_prompt,
    extract_answer_from_codex_result,
    is_codex_approval_request_method,
    is_interactive_codex_request_method,
)


def test_contract_helpers_recognize_interactive_codex_methods():
    assert is_interactive_codex_request_method(CODEX_COMMAND_APPROVAL_REQUEST_METHOD) is True
    assert is_interactive_codex_request_method(CODEX_FILE_CHANGE_REQUEST_METHOD) is True
    assert is_interactive_codex_request_method(CODEX_PERMISSIONS_REQUEST_METHOD) is True
    assert is_interactive_codex_request_method(CODEX_USER_INPUT_REQUEST_METHOD) is True
    assert is_interactive_codex_request_method(CODEX_ELICITATION_REQUEST_METHOD) is True
    assert is_interactive_codex_request_method("thread/start") is False


def test_contract_helpers_only_mark_command_and_file_change_as_approval_methods():
    assert is_codex_approval_request_method(CODEX_COMMAND_APPROVAL_REQUEST_METHOD) is True
    assert is_codex_approval_request_method(CODEX_FILE_CHANGE_REQUEST_METHOD) is True
    assert is_codex_approval_request_method(CODEX_PERMISSIONS_REQUEST_METHOD) is False


def test_default_tool_name_for_prompt_preserves_current_hermit_behavior():
    assert default_tool_name_for_prompt(prompt_kind="permission_ask", method=None) == "bash"
    assert default_tool_name_for_prompt(prompt_kind="waiting", method=CODEX_COMMAND_APPROVAL_REQUEST_METHOD) == "bash"
    assert default_tool_name_for_prompt(prompt_kind="waiting", method=CODEX_PERMISSIONS_REQUEST_METHOD) == "bash"
    assert default_tool_name_for_prompt(prompt_kind="waiting", method=CODEX_FILE_CHANGE_REQUEST_METHOD) == "ask"


def test_codex_channels_interaction_kind_for_prompt_matches_canonical_contract():
    assert codex_channels_interaction_kind_for_prompt(
        prompt_kind="permission_ask",
        method=CODEX_COMMAND_APPROVAL_REQUEST_METHOD,
    ) == "approval_request"
    assert codex_channels_interaction_kind_for_prompt(
        prompt_kind="waiting",
        method=CODEX_FILE_CHANGE_REQUEST_METHOD,
    ) == "approval_request"
    assert codex_channels_interaction_kind_for_prompt(
        prompt_kind="permission_ask",
        method=CODEX_PERMISSIONS_REQUEST_METHOD,
    ) == "permissions_request"
    assert codex_channels_interaction_kind_for_prompt(
        prompt_kind="waiting",
        method=CODEX_USER_INPUT_REQUEST_METHOD,
    ) == "user_input_request"
    assert codex_channels_interaction_kind_for_prompt(
        prompt_kind="waiting",
        method=CODEX_ELICITATION_REQUEST_METHOD,
    ) == "elicitation_request"


def test_build_tool_user_input_result_preserves_question_ids():
    assert build_tool_user_input_result(
        {"questions": [{"id": "target"}, {"id": "confirm"}]},
        {"target": ["staging"]},
    ) == {
        "answers": {
            "target": {"answers": ["staging"]},
            "confirm": {"answers": []},
        }
    }


def test_extract_answer_from_codex_result_matches_canonical_shapes():
    assert extract_answer_from_codex_result(
        method=CODEX_COMMAND_APPROVAL_REQUEST_METHOD,
        result={"decision": "acceptForSession"},
    ) == "Always allow (session)"
    assert extract_answer_from_codex_result(
        method=CODEX_FILE_CHANGE_REQUEST_METHOD,
        result={"decision": "decline"},
    ) == "No"
    assert extract_answer_from_codex_result(
        method=CODEX_PERMISSIONS_REQUEST_METHOD,
        result={"permissions": {"shell": {"execute": True}}, "scope": "session"},
    ) == "Always allow (session)"
    assert extract_answer_from_codex_result(
        method=CODEX_USER_INPUT_REQUEST_METHOD,
        result={"answers": {"target": {"answers": ["staging"]}}},
    ) == "staging"
    assert extract_answer_from_codex_result(
        method=CODEX_ELICITATION_REQUEST_METHOD,
        result={"action": "accept", "content": {"answer": "staging"}},
    ) == "staging"
    assert extract_answer_from_codex_result(
        method=CODEX_ELICITATION_REQUEST_METHOD,
        result={"action": "cancel"},
    ) == "cancel"
