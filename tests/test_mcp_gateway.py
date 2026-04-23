from __future__ import annotations

import httpx

from hermit_agent.mcp_gateway import gateway_health_check


def test_gateway_health_check_accepts_gateway_health_and_tasks_contract():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (
                httpx.Response(
                    200,
                    headers={"content-type": "application/json"},
                    json={"service": "hermit_agent-gateway"},
                    request=request,
                )
                if request.url.path == "/health"
                else httpx.Response(
                    405,
                    headers={"allow": "POST", "content-type": "application/json"},
                    json={"detail": "Method Not Allowed"},
                    request=request,
                )
            )
        )
    )
    healthy, failures, checked_at = gateway_health_check(
        gateway_url="http://gateway.test",
        gateway_client=client,
        consecutive_failures=2,
        last_health_check=0.0,
        max_consecutive_failures=3,
        force=True,
        log_fn=lambda _: None,
    )

    assert healthy is True
    assert failures == 0
    assert checked_at > 0


def test_gateway_health_check_rejects_html_dashboard_impostor():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (
                httpx.Response(
                    200,
                    headers={"content-type": "application/json"},
                    json={"service": "hermit_agent-gateway"},
                    request=request,
                )
                if request.url.path == "/health"
                else httpx.Response(
                    200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    text="<html>dashboard</html>",
                    request=request,
                )
            )
        )
    )
    healthy, failures, checked_at = gateway_health_check(
        gateway_url="http://gateway.test",
        gateway_client=client,
        consecutive_failures=0,
        last_health_check=0.0,
        max_consecutive_failures=3,
        force=True,
        log_fn=lambda _: None,
    )

    assert healthy is False
    assert failures == 1
    assert checked_at > 0


def test_gateway_health_check_retries_transient_connection_failure():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.ConnectError("connection refused", request=request)
        if request.url.path == "/health":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={"service": "hermit_agent-gateway"},
                request=request,
            )
        return httpx.Response(
            405,
            headers={"allow": "POST", "content-type": "application/json"},
            json={"detail": "Method Not Allowed"},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))

    healthy, failures, checked_at = gateway_health_check(
        gateway_url="http://gateway.test",
        gateway_client=client,
        consecutive_failures=0,
        last_health_check=0.0,
        max_consecutive_failures=3,
        force=True,
        log_fn=lambda _: None,
    )

    assert healthy is True
    assert failures == 0
    assert checked_at > 0
