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

    def create_interactive_session_payload(
        self,
        *,
        cwd: str,
        model: str,
        parent_session_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        body: dict = {"cwd": cwd, "model": model}
        if parent_session_id is not None:
            body["parent_session_id"] = parent_session_id
        if session_id is not None:
            body["session_id"] = session_id
        r = self._client.post(
            f"{self.base_url}/internal/interactive-sessions",
            json=body,
            headers=self._headers,
        )
        r.raise_for_status()
        return r.json()

    def send_interactive_message(self, session_id: str, message: str) -> dict:
        r = self._client.post(
            f"{self.base_url}/internal/interactive-sessions/{session_id}/messages",
            json={"message": message},
            headers=self._headers,
        )
        r.raise_for_status()
        return r.json()

    def get_interactive_session(self, session_id: str) -> dict:
        r = self._client.get(
            f"{self.base_url}/internal/interactive-sessions/{session_id}",
            headers=self._headers,
        )
        r.raise_for_status()
        return r.json()

    def stream_interactive_events(self, session_id: str, shutdown_event: threading.Event) -> Iterator[dict]:
        import httpx

        with self._client.stream(
            "GET",
            f"{self.base_url}/internal/interactive-sessions/{session_id}/stream",
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

    def reply_interactive_session(self, session_id: str, message: str) -> None:
        try:
            self._client.post(
                f"{self.base_url}/internal/interactive-sessions/{session_id}/reply",
                json={"message": message},
                headers=self._headers,
            ).raise_for_status()
        except Exception as e:
            logger.warning("interactive reply failed for session %s: %s", session_id, e)

    def cancel_interactive_session(self, session_id: str) -> None:
        try:
            self._client.delete(
                f"{self.base_url}/internal/interactive-sessions/{session_id}",
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
