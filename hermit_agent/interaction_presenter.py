from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PresentedInteraction:
    title: str
    body: str
    options_line: str
    summary: str
    compact_summary: str


def _normalize(text: str) -> str:
    return "".join(ch for ch in text.strip().lower() if ch.isalnum())


def _bash_command_from_question(question: str) -> str:
    lines = [line.rstrip() for line in question.splitlines()]
    if len(lines) >= 2 and lines[0].strip().lower().startswith("[permission request] bash"):
        return lines[1].strip()
    return ""


def _bash_command_description(command: str) -> str:
    normalized = command.strip()
    if not normalized:
        return ""
    if normalized == "pwd":
        return "현재 작업 디렉터리를 확인하는 명령이야."
    if normalized.startswith("ls"):
        return "현재 경로나 지정한 경로의 파일 목록을 확인하는 명령이야."
    if normalized.startswith("echo ") or normalized.startswith("printf "):
        return "터미널에 텍스트를 출력하는 명령이야."
    if normalized.startswith("pytest") or normalized.startswith("./.venv/bin/pytest"):
        return "테스트를 실행하는 명령이야."
    if normalized.startswith("git status"):
        return "현재 Git 작업 상태를 확인하는 명령이야."
    if normalized.startswith("git diff"):
        return "현재 변경 사항 diff를 확인하는 명령이야."
    return ""


def _localize_waiting_question(question: str) -> str:
    normalized = " ".join(question.strip().split())
    lowered = normalized.lower()
    if lowered == "which environment should we use?":
        return "어느 환경으로 진행할까요?"
    if lowered == "which branch should we use?":
        return "어느 브랜치로 진행할까요?"
    if lowered == "which ticket should we use?":
        return "어느 티켓으로 진행할까요?"
    return question.strip()


def present_interaction(*, question: str, options: tuple[str, ...] | list[str], prompt_kind: str) -> PresentedInteraction:
    normalized_options = tuple(option.strip() for option in options if option.strip())
    if prompt_kind == "permission_ask":
        command = _bash_command_from_question(question)
        body_lines = ["Hermit가 터미널 명령 실행 권한을 요청했어."]
        if command:
            body_lines.append(f"명령: {command}")
            description = _bash_command_description(command)
            if description:
                body_lines.append(f"설명: {description}")
        options_line = "선택지: " + (" / ".join(normalized_options) if normalized_options else "Yes / No")
        return PresentedInteraction(
            title="Hermit 권한 요청",
            body="\n".join(body_lines),
            options_line=options_line,
            summary=f"Hermit 권한 요청\n{'\n'.join(body_lines[1:]) if len(body_lines) > 1 else body_lines[0]}\n{options_line}",
            compact_summary=f"<- [hermit-channel]\n권한 요청: {command or 'bash'}\n{options_line}",
        )

    body = _localize_waiting_question(question) or "Hermit가 입력을 기다리고 있어."
    options_line = "선택지: " + (" / ".join(normalized_options) if normalized_options else "자유 입력")
    return PresentedInteraction(
        title="Hermit 입력 요청",
        body=body,
        options_line=options_line,
        summary=f"Hermit 입력 요청\n{body}\n{options_line}",
        compact_summary=f"<- [hermit-channel]\n입력 요청\n{options_line}",
    )


def canonicalize_reply(*, reply: str, options: tuple[str, ...] | list[str], prompt_kind: str) -> str:
    raw = reply.strip()
    normalized = _normalize(raw)
    normalized_options = { _normalize(option): option for option in options if option.strip() }
    if normalized in normalized_options:
        return normalized_options[normalized]

    if prompt_kind == "permission_ask":
        yes_once = {
            "", "y", "yes", "1", "yesonce", "once", "allow", "approve",
            "응", "예", "허용", "이번만", "이번한번", "한번만", "그래", "ok", "okay",
        }
        always = {
            "2", "always", "alwaysallow", "alwaysallowyolo", "yolo",
            "계속허용", "항상허용", "앞으로도허용", "쭉허용",
        }
        deny = {
            "n", "no", "3", "deny", "decline", "cancel",
            "거절", "허용안함", "안돼", "안됨", "노", "취소",
        }
        if normalized in {_normalize(item) for item in yes_once}:
            return "Yes (once)"
        if normalized in {_normalize(item) for item in always}:
            return "Always allow (yolo)"
        if normalized in {_normalize(item) for item in deny}:
            return "No"

    return raw
