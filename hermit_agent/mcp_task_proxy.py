from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import httpx


@dataclass(frozen=True)
class MCPGatewayProxy:
    gateway_url: str
    gateway_client: httpx.Client
    gateway_headers: Callable[[], dict[str, str]]
    start_sse_bridge: Callable[[str], None]
    cleanup_sse_bridge: Callable[[str], None]
    notify_error: Callable[[str, str], None]
    notify_reply: Callable[[str, str], None]
    notify_channel: Callable[..., None]
    truncate_result: Callable[[str], tuple[str, dict]]
    remember_task_context: Callable[[str, str], None] | None = None

    def run_task(self, *, task: str, cwd: str, model: str, max_turns: int) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "task": task,
            "cwd": cwd,
            "max_turns": max_turns,
        }
        if model:
            payload["model"] = model

        r = self.gateway_client.post(
            f"{self.gateway_url}/tasks",
            json=payload,
            headers=self.gateway_headers(),
            timeout=30.0,
        )
        r.raise_for_status()
        data = r.json()

        task_id = data.get("task_id", "")
        status = data.get("status", "running")

        if status == "done" and task_id == "instant":
            result = data.get("result", "")
            truncated, meta = self.truncate_result(result)
            payload = {"status": "done", "result": truncated}
            if meta:
                payload["_truncation"] = meta
            return payload

        if status == "running":
            if self.remember_task_context is not None:
                self.remember_task_context(task_id, cwd)
            self.start_sse_bridge(task_id)
            return {"status": "running", "task_id": task_id}

        if status == "error":
            message = data.get("message", "")
            self.notify_error(task_id, message)
            return {"status": "error", "message": message}

        return data

    def reply_task(self, *, task_id: str, message: str) -> dict[str, Any]:
        r = self.gateway_client.post(
            f"{self.gateway_url}/tasks/{task_id}/reply",
            json={"message": message},
            headers=self.gateway_headers(),
            timeout=30.0,
        )
        r.raise_for_status()
        self.notify_reply(task_id, message)
        return {"status": "running", "task_id": task_id}

    def check_task(self, *, task_id: str, full: bool = False) -> dict[str, Any]:
        r = self.gateway_client.get(
            f"{self.gateway_url}/tasks/{task_id}",
            headers=self.gateway_headers(),
            timeout=10.0,
        )
        r.raise_for_status()
        data = r.json()

        status = data.get("status")
        if status == "waiting":
            question = data.get("question", "")
            options = data.get("options", [])
            prompt_kind = str(data.get("kind") or "waiting")
            tool_name = str(data.get("tool_name") or ("bash" if prompt_kind == "permission_ask" else "ask"))
            method = str(data.get("method") or "")
            self.notify_channel(
                task_id,
                question,
                options,
                prompt_kind=prompt_kind,
                tool_name=tool_name,
                method=method,
            )

        if status == "done":
            result = data.get("result", "")
            if not full:
                truncated, meta = self.truncate_result(result)
                data["result"] = truncated
                if meta:
                    data["_truncation"] = meta

        return data

    def cancel_task(self, *, task_id: str) -> dict[str, Any]:
        r = self.gateway_client.delete(
            f"{self.gateway_url}/tasks/{task_id}",
            headers=self.gateway_headers(),
            timeout=10.0,
        )
        r.raise_for_status()
        self.cleanup_sse_bridge(task_id)
        return {"status": "cancelled", "task_id": task_id}
