from __future__ import annotations

import json
from unittest.mock import Mock

import httpx

from hermit_agent.mcp_tool_handlers import (
    cancel_task_request,
    check_task_request,
    reply_task_request,
    run_task_request,
)


def _result_to_text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def test_run_task_request_handles_gateway_unavailable():
    text = run_task_request(
        task='hello',
        cwd='/tmp',
        model='',
        max_turns=5,
        proxy=Mock(),
        result_to_text=_result_to_text,
        gateway_health_check=lambda: False,
        resolve_git_cwd=lambda cwd: cwd,
        log_fn=lambda _: None,
    )

    parsed = json.loads(text)
    assert parsed['status'] == 'error'
    assert 'Gateway' in parsed['message']


def test_run_task_request_resolves_cwd_and_formats_http_errors():
    proxy = Mock()
    response = httpx.Response(503, request=httpx.Request('POST', 'http://test'))
    proxy.run_task.side_effect = httpx.HTTPStatusError('boom', request=response.request, response=response)
    logs: list[str] = []

    text = run_task_request(
        task='hello',
        cwd='/tmp',
        model='m',
        max_turns=5,
        proxy=proxy,
        result_to_text=_result_to_text,
        gateway_health_check=lambda: True,
        resolve_git_cwd=lambda cwd: cwd + '/resolved',
        log_fn=logs.append,
    )

    parsed = json.loads(text)
    assert parsed == {'status': 'error', 'message': 'Gateway HTTP error: 503'}
    proxy.run_task.assert_called_once_with(task='hello', cwd='/tmp/resolved', model='m', max_turns=5)
    assert logs and '[err] run_task:' in logs[0]


def test_reply_check_cancel_task_requests_map_404_to_not_found():
    response = httpx.Response(404, request=httpx.Request('POST', 'http://test'))
    error = httpx.HTTPStatusError('missing', request=response.request, response=response)

    for fn, kwargs in [
        (reply_task_request, {'task_id': 't1', 'message': 'yes'}),
        (check_task_request, {'task_id': 't1', 'full': False}),
        (cancel_task_request, {'task_id': 't1'}),
    ]:
        proxy = Mock()
        method_name = fn.__name__.replace('_request', '')
        getattr(proxy, method_name).side_effect = error
        text = fn(proxy=proxy, result_to_text=_result_to_text, log_fn=lambda _: None, **kwargs)
        assert json.loads(text) == {'status': 'not_found', 'message': 'Task not found: t1'}
