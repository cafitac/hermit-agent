"""HermitAgent Gateway HTTP client.

Used by bridge.py. Synchronous client based on httpx.
Parses SSE stream and yields dict events.
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Iterator

logger = logging.getLogger("hermit_agent.bridge_client")


class GatewayClient:
    """Gateway HTTP client. Synchronous code. Uses httpx."""

    CONNECT_TIMEOUT = 5.0   # Gateway connection timeout (seconds)
    READ_TIMEOUT = 60.0     # SSE read timeout — 2x keepalive ping (30s)

    def __init__(self, base_url: str, api_key: str):
        import httpx
        self.base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._client = httpx.Client(
            timeout=httpx.Timeout(connect=self.CONNECT_TIMEOUT, read=self.READ_TIMEOUT, write=10.0, pool=5.0),
        )
        self._current_response: "httpx.Response | None" = None  # for forced shutdown

    def check_gateway(self) -> bool:
        """Check whether the gateway is reachable."""
        try:
            r = self._client.get(f"{self.base_url}/auth", headers=self._headers)
            return r.status_code in (200, 302)
        except Exception:
            return False

    def create_task(self, task: str, cwd: str, model: str, max_turns: int, parent_session_id: str | None = None) -> str:
        """POST /tasks → returns task_id."""
        return self.create_task_payload(
            task=task,
            cwd=cwd,
            model=model,
            max_turns=max_turns,
            parent_session_id=parent_session_id,
        )["task_id"]

    def create_task_payload(
        self,
        task: str,
        cwd: str,
        model: str,
        max_turns: int,
        parent_session_id: str | None = None,
    ) -> dict:
        """POST /tasks → returns the full response payload."""
        body: dict = {"task": task, "cwd": cwd, "model": model, "max_turns": max_turns}
        if parent_session_id is not None:
            body["parent_session_id"] = parent_session_id
        r = self._client.post(
            f"{self.base_url}/tasks",
            json=body,
            headers=self._headers,
        )
        r.raise_for_status()
        return r.json()

    def stream_events(self, task_id: str, shutdown_event: threading.Event) -> Iterator[dict]:
        """GET /tasks/{id}/stream → yield SSE events as dicts.

        Terminate via shutdown_event.set() + close_stream().
        On ReadTimeout, yields an error event then exits.
        """
        import httpx

        with self._client.stream(
            "GET",
            f"{self.base_url}/tasks/{task_id}/stream",
            headers=self._headers,
        ) as resp:
            self._current_response = resp
            try:
                for line in resp.iter_lines():
                    if shutdown_event.is_set():
                        break
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        try:
                            yield json.loads(data_str)
                        except json.JSONDecodeError:
                            pass
                    # ignore ": ping" lines
            except httpx.ReadTimeout:
                yield {"type": "error", "message": "SSE connection timeout (no server response)"}
            except Exception:
                pass
            finally:
                self._current_response = None

    def close_stream(self) -> None:
        """Force-close the SSE stream (for interrupt handling).

        httpx.Response.close() unblocks iter_lines().
        """
        resp = self._current_response
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass

    def reply(self, task_id: str, message: str) -> None:
        """POST /tasks/{id}/reply."""
        try:
            self._client.post(
                f"{self.base_url}/tasks/{task_id}/reply",
                json={"message": message},
                headers=self._headers,
            )
        except Exception as e:
            logger.warning("reply failed for task %s: %s", task_id, e)

    def cancel(self, task_id: str) -> None:
        """DELETE /tasks/{id}."""
        try:
            self._client.delete(
                f"{self.base_url}/tasks/{task_id}",
                headers=self._headers,
            )
        except Exception:
            pass

    def close(self) -> None:
        """Close the HTTP client."""
        try:
            self._client.close()
        except Exception:
            pass
