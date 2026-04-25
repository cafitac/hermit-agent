from __future__ import annotations

import json
import logging
import os
import select
import subprocess
import sys
import threading
from collections import defaultdict
from queue import Empty
from typing import TYPE_CHECKING, Any, Literal

from .interaction_contract import build_tool_user_input_result
from .channels_adapter import CodexChannelsWaitSession, load_codex_channels_settings
from .app_server_bridge import await_attached_codex_app_server_response
from ..version import VERSION
from ..interactive_prompts import (
    build_codex_channels_interaction,
    create_interactive_prompt,
    waiting_prompt_snapshot,
)
from ..interactive_sinks import maybe_start_codex_channels_wait_session, write_codex_app_server_message

logger = logging.getLogger("hermit_agent.codex_runner")

if TYPE_CHECKING:
    from ..gateway.session_log import GatewaySessionLog

_YES_ANSWERS = {"", "y", "yes", "1", "accept", "approve", "allow"}
_ALWAYS_ANSWERS = {"2", "always", "yolo", "accept for session", "acceptforsession"}
_NO_ANSWERS = {"n", "no", "decline", "deny"}
_CANCEL_ANSWERS = {"cancel", "abort", "__cancelled__"}


def _prepare_codex_task(task: str) -> str:
    guidance = (
        "Hermit interactive-input contract:\n"
        "- If you need missing user input, request it through the host interactive input surface.\n"
        "- Do not claim that ask_user_question is unavailable.\n"
        "- Do not print a question as your final answer when you still need user input.\n"
        "- For free-text questions, request a plain text response from the host.\n"
        "- For choice questions, request host input with the available options.\n"
        "- After the user replies, continue the task and then produce the final answer.\n"
    )
    if not task.strip():
        return guidance
    return f"{guidance}\nTask:\n{task}"


def is_codex_model(model: str) -> bool:
    lowered = (model or "").strip().lower()
    return (
        lowered.startswith("codex/")
        or lowered == "codex"
        or "-codex" in lowered
        or lowered == "gpt-5.4"
        or lowered.startswith("gpt-5.4-")
    )


def normalize_codex_model(model: str) -> str:
    lowered = (model or "").strip()
    if lowered.lower().startswith("codex/"):
        return lowered.split("/", 1)[1]
    if lowered.lower() == "codex":
        return "gpt-5.4"
    return lowered


class CodexTaskInterrupted(Exception):
    pass


class CodexTaskFailed(Exception):
    pass


class CodexAppServerClient:
    def __init__(
        self,
        *,
        command: str,
        cwd: str,
        model: str,
        reasoning_effort: str | None,
        state,
        sse,
        task_id: str,
        gw_log: GatewaySessionLog | None = None,
        codex_channels_cfg: dict[str, Any] | None = None,
    ) -> None:
        self._command = command
        self._cwd = cwd
        self._model = normalize_codex_model(model)
        self._reasoning_effort = _normalize_reasoning_effort(reasoning_effort)
        self._state = state
        self._sse = sse
        self._task_id = task_id
        self._gw_log = gw_log
        self._codex_channels_cfg = codex_channels_cfg or {}
        self._process: subprocess.Popen[str] | None = None
        self._request_id = 0
        self._thread_id: str | None = None
        self._turn_id: str | None = None
        self._latest_result: str | None = None
        self._item_buffers: dict[str, list[str]] = defaultdict(list)
        self._item_phases: dict[str, str] = {}
        self._stderr_thread: threading.Thread | None = None
        self._stdout_lock = threading.Lock()

    def run(self, task: str) -> str:
        self._start_process()
        try:
            self._request(
                "initialize",
                {"clientInfo": {"name": "hermit_agent", "version": VERSION}},
            )
            self._notify("initialized")
            thread = self._request(
                "thread/start",
                {
                    "cwd": self._cwd,
                    "approvalPolicy": "on-request",
                    "sandbox": "workspace-write",
                    "model": self._model,
                    "modelProvider": "openai",
                    "personality": "pragmatic",
                },
            )
            self._thread_id = thread["thread"]["id"]
            turn = self._request(
                "turn/start",
                {
                    "threadId": self._thread_id,
                    "input": [{"type": "text", "text": _prepare_codex_task(task)}],
                    "effort": self._reasoning_effort,
                },
            )
            self._turn_id = turn["turn"]["id"]
            return self._drain_until_complete()
        finally:
            self.close()

    def close(self) -> None:
        proc = self._process
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
                proc.wait(timeout=5)
        self._process = None

    def _start_process(self) -> None:
        env = dict(os.environ)
        self._process = subprocess.Popen(
            _codex_app_server_command(self._command),
            cwd=self._cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr,
            name=f"codex-app-server-stderr-{self._task_id[:8]}",
            daemon=True,
        )
        self._stderr_thread.start()

    def _drain_stderr(self) -> None:
        proc = self._process
        if proc is None or proc.stderr is None:
            return
        for line in proc.stderr:
            text = line.rstrip()
            if not text:
                continue
            logger.debug("codex stderr: %s", text)
            if self._gw_log is not None:
                self._gw_log.write_event({"type": "codex_stderr", "message": text})

    def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._write_message({"method": method, **({"params": params} if params is not None else {})})

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._request_id += 1
        req_id = self._request_id
        self._write_message({"id": req_id, "method": method, "params": params})
        while True:
            message = self._read_message(timeout=0.5)
            if message is None:
                self._check_cancel()
                continue
            if message.get("id") == req_id:
                if "error" in message:
                    raise CodexTaskFailed(f"{method} failed: {message['error']}")
                return message.get("result", {})
            self._dispatch_message(message)

    def _drain_until_complete(self) -> str:
        while True:
            self._check_cancel()
            message = self._read_message(timeout=0.5)
            if message is None:
                continue
            completed = self._dispatch_message(message)
            if completed:
                return self._latest_result or "[task complete]"

    def _check_cancel(self) -> None:
        if not self._state.cancel_event.is_set():
            return
        if self._thread_id and self._turn_id:
            try:
                self._request(
                    "turn/interrupt",
                    {"threadId": self._thread_id, "turnId": self._turn_id},
                )
            except Exception:
                pass
        raise CodexTaskInterrupted("Task cancelled")

    def _read_message(self, timeout: float) -> dict[str, Any] | None:
        proc = self._process
        if proc is None or proc.stdout is None:
            raise CodexTaskFailed("Codex app-server is not running")
        ready, _, _ = select.select([proc.stdout], [], [], timeout)
        if not ready:
            return None
        line = proc.stdout.readline()
        if not line:
            raise CodexTaskFailed("Codex app-server closed stdout unexpectedly")
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise CodexTaskFailed(f"Invalid Codex JSON message: {line!r}") from exc

    def _write_message(self, message: dict[str, Any]) -> None:
        proc = self._process
        if proc is None or proc.stdin is None:
            raise CodexTaskFailed("Codex app-server stdin is unavailable")
        write_codex_app_server_message(proc.stdin, message, lock=self._stdout_lock)

    def _dispatch_message(self, message: dict[str, Any]) -> bool:
        if self._gw_log is not None:
            self._gw_log.write_event({"type": "codex_message", "payload": message})

        if "method" not in message:
            return False

        if "id" in message:
            self._handle_server_request(message)
            return False

        method = message["method"]
        params = message.get("params", {})

        if method == "error":
            raise CodexTaskFailed(params.get("message", "Codex reported an error"))

        if method == "thread/tokenUsage/updated":
            usage = params.get("tokenUsage", {}).get("total", {})
            self._state.token_totals = {
                "prompt_tokens": usage.get("inputTokens", 0),
                "completion_tokens": usage.get("outputTokens", 0),
            }
            return False

        if method == "account/rateLimits/updated":
            rate_limits = params.get("rateLimits") or {}
            credits = rate_limits.get("credits") or {}
            has_credits = credits.get("hasCredits")
            used_percent = ((rate_limits.get("primary") or {}).get("usedPercent"))
            if has_credits is False or (isinstance(used_percent, (int, float)) and used_percent >= 100):
                raise CodexTaskFailed(
                    "Codex account is currently rate-limited or out of credits. "
                    "Please retry later or switch to a non-codex model."
                )
            return False

        if method == "item/started":
            item = params.get("item", {})
            item_id = item.get("id")
            item_type = item.get("type")
            if item_id and item_type == "agentMessage":
                self._item_phases[item_id] = item.get("phase", "")
            if item_type in {"fileChange", "commandExecution"}:
                self._emit_progress(f"codex:{item_type}", "Started")
            return False

        if method == "item/agentMessage/delta":
            item_id = params.get("itemId")
            if item_id:
                self._item_buffers[item_id].append(params.get("delta", ""))
            return False

        if method.endswith("/outputDelta"):
            delta = params.get("delta", "")
            item_id = params.get("itemId")
            item_type = "codex:output"
            self._emit_progress(item_type, delta[:500])
            if item_id:
                self._item_buffers[item_id].append(delta)
            return False

        if method == "item/completed":
            item = params.get("item", {})
            item_id = item.get("id", "")
            item_type = item.get("type")
            if item_type == "agentMessage":
                text = item.get("text") or "".join(self._item_buffers.pop(item_id, []))
                phase = item.get("phase") or self._item_phases.pop(item_id, "")
                if phase == "final_answer":
                    self._latest_result = text
                elif text:
                    self._emit_progress("codex:message", text[:500])
            elif item_type == "fileChange":
                delta = "".join(self._item_buffers.pop(item_id, []))
                if delta:
                    self._emit_progress("codex:fileChange", delta[:500])
            elif item_type == "commandExecution":
                delta = "".join(self._item_buffers.pop(item_id, []))
                if delta:
                    self._emit_progress("codex:command", delta[:500])
            return False

        if method == "turn/completed":
            turn = params.get("turn", {})
            status = turn.get("status")
            if status != "completed":
                error = turn.get("error") or {"message": f"Turn finished with status {status}"}
                raise CodexTaskFailed(str(error))
            return True

        if method == "thread/status/changed":
            status = (params.get("status") or {}).get("type")
            if status == "systemError":
                raise CodexTaskFailed(
                    "Codex thread entered systemError — check credentials, rate limits, or MCP server conflicts."
                )
            if status == "idle" and self._latest_result is not None:
                return True
            return False

        return False

    def _handle_server_request(self, message: dict[str, Any]) -> None:
        method = message["method"]
        request_id = message["id"]
        params = message.get("params", {})
        try:
            if method == "item/commandExecution/requestApproval":
                decision = self._await_review(
                    method=method,
                    request_id=request_id,
                    question=_format_command_approval(params),
                    options=["Yes (once)", "Always allow (session)", "No"],
                    params=params,
                )
                self._send_result(request_id, {"decision": decision})
                return

            if method == "item/fileChange/requestApproval":
                decision = self._await_review(
                    method=method,
                    request_id=request_id,
                    question=_format_file_change_approval(params),
                    options=["Yes (once)", "Always allow (session)", "No"],
                    params=params,
                )
                self._send_result(request_id, {"decision": decision})
                return

            if method == "item/permissions/requestApproval":
                permissions, scope = self._await_permissions(request_id, params)
                self._send_result(request_id, {"permissions": permissions, "scope": scope})
                return

            if method == "item/tool/requestUserInput":
                self._send_result(request_id, build_tool_user_input_result(params, self._await_user_input(request_id, params)))
                return

            if method == "mcpServer/elicitation/request":
                answer = self._await_elicitation(request_id, params)
                self._send_result(request_id, answer)
                return

            self._send_error(request_id, f"Unsupported Codex server request: {method}")
        except CodexTaskInterrupted:
            self._send_error(request_id, "Task cancelled")
            raise
        except Exception as exc:
            self._send_error(request_id, str(exc))
            raise

    def _await_review(
        self,
        *,
        method: str,
        request_id: Any,
        question: str,
        options: list[str],
        params: dict[str, Any],
    ) -> str:
        answer = _wait_for_reply(
            state=self._state,
            sse=self._sse,
            task_id=self._task_id,
            question=question,
            options=options,
            kind="permission_ask" if "commandExecution" in method or "permissions" in method else "waiting",
            method=method,
            request_id=request_id,
            thread_id=self._thread_id,
            turn_id=self._turn_id,
            request_params=params,
            codex_channels_cfg=self._codex_channels_cfg,
            cwd=self._cwd,
        )
        normalized = _normalize_answer(answer)
        if normalized in _ALWAYS_ANSWERS:
            return "acceptForSession"
        if normalized in _CANCEL_ANSWERS:
            return "cancel"
        if normalized in _NO_ANSWERS:
            return "decline"
        return "accept"

    def _await_permissions(self, request_id: Any, params: dict[str, Any]) -> tuple[dict[str, Any], str]:
        permissions = params.get("permissions") or {}
        question = _format_permissions_approval(params)
        answer = _wait_for_reply(
            state=self._state,
            sse=self._sse,
            task_id=self._task_id,
            question=question,
            options=["Yes (once)", "Always allow (session)", "No"],
            kind="permission_ask",
            method="item/permissions/requestApproval",
            request_id=request_id,
            thread_id=self._thread_id,
            turn_id=self._turn_id,
            request_params=params,
            codex_channels_cfg=self._codex_channels_cfg,
            cwd=self._cwd,
        )
        normalized = _normalize_answer(answer)
        if normalized in _CANCEL_ANSWERS:
            raise CodexTaskInterrupted("Task cancelled")
        if normalized in _NO_ANSWERS:
            return {}, "turn"
        return permissions, "session" if normalized in _ALWAYS_ANSWERS else "turn"

    def _await_user_input(self, request_id: Any, params: dict[str, Any]) -> dict[str, list[str]]:
        questions = params.get("questions") or []
        rendered = []
        for q in questions:
            options = q.get("options") or []
            rendered.append(q.get("question", ""))
            if options:
                rendered.append("Options: " + ", ".join(opt.get("label", "") for opt in options))
        answer = _wait_for_reply(
            state=self._state,
            sse=self._sse,
            task_id=self._task_id,
            question="\n".join(rendered).strip() or "Codex requires input.",
            options=[opt.get("label", "") for opt in ((questions[0].get("options") or []) if questions else [])],
            kind="waiting",
            method="item/tool/requestUserInput",
            request_id=request_id,
            thread_id=self._thread_id,
            turn_id=self._turn_id,
            request_params=params,
            codex_channels_cfg=self._codex_channels_cfg,
            cwd=self._cwd,
        )
        answers: dict[str, list[str]] = {}
        for q in questions:
            answers[q["id"]] = [_resolve_option_answer(answer, q.get("options") or [])]
        return answers

    def _await_elicitation(self, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        mode = params.get("mode")
        message = params.get("message", "Codex requested input.")
        if mode == "url":
            answer = _wait_for_reply(
                state=self._state,
                sse=self._sse,
                task_id=self._task_id,
                question=f"{message}\nURL: {params.get('url', '')}",
                options=["Continue", "Cancel"],
                kind="waiting",
                method="mcpServer/elicitation/request",
                request_id=request_id,
                thread_id=self._thread_id,
                turn_id=self._turn_id,
                request_params=params,
                codex_channels_cfg=self._codex_channels_cfg,
            cwd=self._cwd,
            )
            normalized = _normalize_answer(answer)
            if normalized in _CANCEL_ANSWERS or normalized in _NO_ANSWERS:
                return {"action": "cancel"}
            return {"action": "accept", "content": {"url": answer}}

        answer = _wait_for_reply(
            state=self._state,
            sse=self._sse,
            task_id=self._task_id,
            question=message,
            options=["Submit", "Cancel"],
            kind="waiting",
            method="mcpServer/elicitation/request",
            request_id=request_id,
            thread_id=self._thread_id,
            turn_id=self._turn_id,
            request_params=params,
            codex_channels_cfg=self._codex_channels_cfg,
            cwd=self._cwd,
        )
        normalized = _normalize_answer(answer)
        if normalized in _CANCEL_ANSWERS or normalized in _NO_ANSWERS:
            return {"action": "cancel"}
        return {"action": "accept", "content": {"answer": answer}}

    def _send_result(self, request_id: Any, result: dict[str, Any]) -> None:
        self._write_message({"id": request_id, "result": result})

    def _send_error(self, request_id: Any, message: str) -> None:
        self._write_message({"id": request_id, "error": {"code": -32000, "message": message}})

    def _emit_progress(self, step: str, message: str) -> None:
        if not message:
            return
        from ..gateway.sse import SSEEvent
        self._sse.publish_threadsafe(
            self._task_id,
            SSEEvent(type="progress", step=step, message=message[:500]),
        )


def _normalize_answer(answer: str | None) -> str:
    return (answer or "").strip().lower()


def _normalize_reasoning_effort(effort: str | None) -> str | None:
    normalized = (effort or "").strip().lower()
    if normalized in {"none", "low", "medium", "high", "xhigh"}:
        return normalized
    return None


def _resolve_option_answer(answer: str, options: list[dict[str, Any]]) -> str:
    normalized = _normalize_answer(answer)
    if normalized.isdigit():
        idx = int(normalized) - 1
        if 0 <= idx < len(options):
            return options[idx].get("label", answer)
    for option in options:
        label = option.get("label", "")
        if normalized == label.strip().lower():
            return label
    return answer


def _wait_for_reply(
    *,
    state,
    sse,
    task_id: str,
    question: str,
    options: list[str],
    kind: str,
    method: str | None = None,
    request_id: str | int | None = None,
    thread_id: str | None = None,
    turn_id: str | None = None,
    request_params: dict[str, Any] | None = None,
    codex_channels_cfg: dict[str, Any] | None = None,
    cwd: str | None = None,
) -> str:
    from ..gateway.sse import SSEEvent

    prompt = create_interactive_prompt(
        task_id=task_id,
        question=question,
        options=options or [],
        prompt_kind=kind,
        method=method,
        request_id=request_id,
        thread_id=thread_id,
        turn_id=turn_id,
        params=request_params,
    )

    state.status = "waiting"
    state.waiting_kind = prompt.prompt_kind
    state.waiting_prompt = waiting_prompt_snapshot(prompt)
    state.question_queue.put(waiting_prompt_snapshot(prompt))
    event_type: Literal["permission_ask", "waiting"] = (
        "permission_ask" if prompt.prompt_kind == "permission_ask" else "waiting"
    )
    sse.publish_threadsafe(
        task_id,
        SSEEvent(
            type=event_type,
            question=prompt.question,
            options=list(prompt.options),
            tool_name=prompt.tool_name,
        ),
    )

    attached_answer = await_attached_codex_app_server_response(prompt, env=dict(os.environ))
    if attached_answer is not None:
        state.status = "running"
        state.waiting_kind = None
        state.waiting_prompt = None
        sse.publish_threadsafe(task_id, SSEEvent(type="reply_ack", message="reply received"))
        return attached_answer

    session = None
    settings = load_codex_channels_settings(codex_channels_cfg, cwd or os.getcwd())
    session = maybe_start_codex_channels_wait_session(
        prompt,
        settings=settings,
        session_factory=CodexChannelsWaitSession,
        interaction_builder=build_codex_channels_interaction,
    )

    try:
        while True:
            if state.cancel_event.is_set():
                raise CodexTaskInterrupted("Task cancelled")
            if session is not None:
                answer = session.poll_response()
                if answer is not None:
                    state.status = "running"
                    state.waiting_kind = None
                    state.waiting_prompt = None
                    sse.publish_threadsafe(task_id, SSEEvent(type="reply_ack", message="reply received"))
                    return str(answer)
            try:
                answer = state.reply_queue.get(timeout=0.25)
            except Empty:
                continue
            state.status = "running"
            state.waiting_kind = None
            state.waiting_prompt = None
            sse.publish_threadsafe(task_id, SSEEvent(type="reply_ack", message="reply received"))
            return str(answer)
    finally:
        state.waiting_prompt = None
        if session is not None:
            session.terminate()


def _format_command_approval(params: dict[str, Any]) -> str:
    command = params.get("command") or "(unknown command)"
    cwd = params.get("cwd") or ""
    reason = params.get("reason") or ""
    lines = ["[Codex permission request] command execution", command]
    if cwd:
        lines.append(f"cwd: {cwd}")
    if reason:
        lines.append(reason)
    return "\n".join(lines)


def _format_file_change_approval(params: dict[str, Any]) -> str:
    reason = params.get("reason") or "Codex wants approval to apply file changes."
    grant_root = params.get("grantRoot")
    lines = ["[Codex permission request] file changes", reason]
    if grant_root:
        lines.append(f"root: {grant_root}")
    return "\n".join(lines)


def _format_permissions_approval(params: dict[str, Any]) -> str:
    reason = params.get("reason") or "Codex requested additional permissions."
    permissions = json.dumps(params.get("permissions") or {}, ensure_ascii=False)
    return f"[Codex permission request] additional permissions\n{reason}\n{permissions}"

def _codex_app_server_command(command: str) -> list[str]:
    ask_server_name = "hermit_ask_user"
    python = json.dumps(sys.executable)
    args = json.dumps(["-m", "hermit_agent.codex_ask_mcp"])
    return [
        command,
        "app-server",
        "-c",
        "mcp_servers={}",
        "-c",
        f"mcp_servers.{ask_server_name}.command={python}",
        "-c",
        f"mcp_servers.{ask_server_name}.args={args}",
        "--disable",
        "codex_hooks",
        "--listen",
        "stdio://",
    ]


def wait_for_codex_host_reply(
    *,
    state,
    sse,
    task_id: str,
    question: str,
    cwd: str,
) -> str:
    return _wait_for_reply(
        state=state,
        sse=sse,
        task_id=task_id,
        question=question,
        options=[],
        kind="waiting",
        method="item/tool/requestUserInput",
        request_id=f"followup-{task_id}",
        request_params={"questions": [{"id": "followup", "question": question}]},
        codex_channels_cfg={},
        cwd=cwd,
    )


def run_codex_task(
    *,
    task_id: str,
    task: str,
    cwd: str,
    model: str,
    reasoning_effort: str | None,
    state,
    sse,
    gw_log: GatewaySessionLog | None = None,
    codex_command: str = "codex",
    codex_channels_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    client = CodexAppServerClient(
        command=codex_command,
        cwd=cwd,
        model=model,
        reasoning_effort=reasoning_effort,
        state=state,
        sse=sse,
        task_id=task_id,
        gw_log=gw_log,
        codex_channels_cfg=codex_channels_cfg,
    )
    result = client.run(task)
    state.result = result or "[task complete]"
    state.result_queue.put({"status": "done", "result": state.result})
    return {
        "token_totals": state.token_totals,
        "status": "done" if not state.cancel_event.is_set() else "cancelled",
        "model": normalize_codex_model(model),
        "result": state.result,
    }
