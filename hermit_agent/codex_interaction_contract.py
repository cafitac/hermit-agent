from __future__ import annotations

from typing import Any

CODEX_COMMAND_APPROVAL_REQUEST_METHOD = "item/commandExecution/requestApproval"
CODEX_FILE_CHANGE_REQUEST_METHOD = "item/fileChange/requestApproval"
CODEX_PERMISSIONS_REQUEST_METHOD = "item/permissions/requestApproval"
CODEX_USER_INPUT_REQUEST_METHOD = "item/tool/requestUserInput"
CODEX_ELICITATION_REQUEST_METHOD = "mcpServer/elicitation/request"

INTERACTIVE_CODEX_REQUEST_METHODS = (
    CODEX_COMMAND_APPROVAL_REQUEST_METHOD,
    CODEX_FILE_CHANGE_REQUEST_METHOD,
    CODEX_PERMISSIONS_REQUEST_METHOD,
    CODEX_USER_INPUT_REQUEST_METHOD,
    CODEX_ELICITATION_REQUEST_METHOD,
)

CODEX_APPROVAL_REQUEST_METHODS = (
    CODEX_COMMAND_APPROVAL_REQUEST_METHOD,
    CODEX_FILE_CHANGE_REQUEST_METHOD,
)


def is_interactive_codex_request_method(method: str | None) -> bool:
    return method in INTERACTIVE_CODEX_REQUEST_METHODS


def is_codex_approval_request_method(method: str | None) -> bool:
    return method in CODEX_APPROVAL_REQUEST_METHODS


def default_tool_name_for_prompt(*, prompt_kind: str, method: str | None = None) -> str:
    if method in {CODEX_COMMAND_APPROVAL_REQUEST_METHOD, CODEX_PERMISSIONS_REQUEST_METHOD}:
        return "bash"
    if prompt_kind == "permission_ask":
        return "bash"
    return "ask"


def codex_channels_interaction_kind_for_prompt(*, prompt_kind: str, method: str | None = None) -> str:
    if method in CODEX_APPROVAL_REQUEST_METHODS:
        return "approval_request"
    if method == CODEX_PERMISSIONS_REQUEST_METHOD:
        return "permissions_request"
    if method == CODEX_ELICITATION_REQUEST_METHOD:
        return "elicitation_request"
    if prompt_kind == "permission_ask":
        return "approval_request"
    return "user_input_request"


def build_tool_user_input_result(params: dict[str, Any], answers: dict[str, list[str]]) -> dict[str, Any]:
    return {
        "answers": {
            question["id"]: {"answers": answers.get(question["id"], [])}
            for question in (params.get("questions") or [])
        }
    }


def extract_answer_from_codex_result(*, method: str | None, result: dict[str, Any]) -> str:
    if method == CODEX_USER_INPUT_REQUEST_METHOD:
        answers = result.get("answers")
        if isinstance(answers, dict):
            for value in answers.values():
                if isinstance(value, dict):
                    answer_list = value.get("answers")
                    if isinstance(answer_list, list) and answer_list:
                        return str(answer_list[0])
        return ""

    if method in CODEX_APPROVAL_REQUEST_METHODS:
        decision = str(result.get("decision") or "")
        if decision == "acceptForSession":
            return "Always allow (session)"
        if decision == "accept":
            return "Yes (once)"
        if decision == "decline":
            return "No"
        if decision == "cancel":
            return "cancel"
        return decision

    if method == CODEX_PERMISSIONS_REQUEST_METHOD:
        permissions = result.get("permissions")
        scope = str(result.get("scope") or "")
        if permissions and scope == "session":
            return "Always allow (session)"
        if permissions:
            return "Yes (once)"
        return "No"

    if method == CODEX_ELICITATION_REQUEST_METHOD:
        action = str(result.get("action") or "")
        content = result.get("content")
        if action in {"cancel", "decline"}:
            return "cancel"
        if isinstance(content, dict):
            if "answer" in content:
                return str(content["answer"])
            if "url" in content:
                return str(content["url"])
        return action

    return str(result)
