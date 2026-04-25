from __future__ import annotations

import json
import threading
import time

import httpx

from ..channels_core.event_adapters import channel_action_from_sse_event


class _SSEBridge:
    """Consume the Gateway SSE stream and forward channel actions via callbacks."""

    def __init__(
        self,
        task_id: str,
        client: httpx.Client,
        gateway_url: str | None = None,
        gateway_api_key: str | None = None,
        log_fn=None,
        on_action=None,
        on_cleanup=None,
    ):
        self.task_id = task_id
        self.client = client
        self.shutdown_event = threading.Event()
        self.thread: threading.Thread | None = None
        self._last_event_time = time.time()
        self._gateway_url = gateway_url
        self._gateway_api_key = gateway_api_key
        self._log = log_fn or (lambda _msg: None)
        self._on_action = on_action or (lambda *_args, **_kwargs: None)
        self._on_cleanup = on_cleanup or (lambda *_args, **_kwargs: None)

    def _bridge_log(self, msg: str) -> None:
        self._log(f"[sse-bridge {self.task_id[:8]}] {msg}")

    def start(self) -> None:
        self.thread = threading.Thread(
            target=self._consume_sse,
            name=f"sse-bridge-{self.task_id[:8]}",
            daemon=True,
        )
        self.thread.start()
        self._bridge_log("started")

    def shutdown(self) -> None:
        self.shutdown_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5.0)
            if self.thread.is_alive():
                self._bridge_log("thread did not exit gracefully")
        self._bridge_log("shutdown")

    def _consume_sse(self) -> None:
        url = f"{self._gateway_url}/tasks/{self.task_id}/stream"
        headers = {}
        if self._gateway_api_key:
            headers["Authorization"] = f"Bearer {self._gateway_api_key}"

        try:
            with self.client.stream("GET", url, headers=headers, timeout=None) as resp:
                resp.raise_for_status()

                for line in resp.iter_lines():
                    if self.shutdown_event.is_set():
                        break

                    self._last_event_time = time.time()

                    if not line:
                        continue

                    if line.startswith("data: "):
                        data_str = line[6:]
                        try:
                            event = json.loads(data_str)
                            self._handle_sse_event(event)
                        except json.JSONDecodeError:
                            pass

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                self._bridge_log("task not found (404) -- cleanup")
            else:
                self._bridge_log(f"http error: {e}")
        except Exception as e:
            if not self.shutdown_event.is_set():
                self._bridge_log(f"error: {e}")
        finally:
            self._on_cleanup(self.task_id)

    def _handle_sse_event(self, event: dict) -> None:
        event_type = event.get("type", "")
        self._bridge_log(f"event: {event_type}")

        action = channel_action_from_sse_event(event)
        if action is None:
            return
        self._on_action(self.task_id, action)
