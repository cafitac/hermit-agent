"""Gateway proxy request handlers for MCP tool surfaces."""

from __future__ import annotations

import httpx


def run_task_request(
    *,
    task: str,
    cwd: str,
    model: str,
    max_turns: int,
    proxy,
    result_to_text,
    gateway_health_check,
    resolve_git_cwd,
    log_fn,
) -> str:
    if not gateway_health_check():
        return result_to_text({
            'status': 'error',
            'message': 'AI Gateway is not responding. Make sure the Gateway is running.',
        })

    try:
        resolved_cwd = resolve_git_cwd(cwd)
        return result_to_text(proxy.run_task(task=task, cwd=resolved_cwd, model=model, max_turns=max_turns))
    except httpx.HTTPStatusError as exc:
        log_fn(f'[err] run_task: {exc}')
        return result_to_text({'status': 'error', 'message': f'Gateway HTTP error: {exc.response.status_code}'})
    except httpx.RequestError as exc:
        log_fn(f'[err] run_task: {exc}')
        return result_to_text({'status': 'error', 'message': f'Gateway communication error: {exc}'})


def reply_task_request(*, task_id: str, message: str, proxy, result_to_text, log_fn) -> str:
    try:
        return result_to_text(proxy.reply_task(task_id=task_id, message=message))
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return result_to_text({'status': 'not_found', 'message': f'Task not found: {task_id}'})
        log_fn(f'[err] reply_task: {exc}')
        return result_to_text({'status': 'error', 'message': f'Gateway HTTP error: {exc.response.status_code}'})
    except httpx.RequestError as exc:
        log_fn(f'[err] reply_task: {exc}')
        return result_to_text({'status': 'error', 'message': f'Gateway communication error: {exc}'})


def check_task_request(*, task_id: str, full: bool, proxy, result_to_text, log_fn) -> str:
    try:
        return result_to_text(proxy.check_task(task_id=task_id, full=full))
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return result_to_text({'status': 'not_found', 'message': f'Task not found: {task_id}'})
        log_fn(f'[err] check_task: {exc}')
        return result_to_text({'status': 'error', 'message': f'Gateway HTTP error: {exc.response.status_code}'})
    except httpx.RequestError as exc:
        log_fn(f'[err] check_task: {exc}')
        return result_to_text({'status': 'error', 'message': f'Gateway communication error: {exc}'})


def cancel_task_request(*, task_id: str, proxy, result_to_text, log_fn) -> str:
    try:
        return result_to_text(proxy.cancel_task(task_id=task_id))
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return result_to_text({'status': 'not_found', 'message': f'Task not found: {task_id}'})
        log_fn(f'[err] cancel_task: {exc}')
        return result_to_text({'status': 'error', 'message': f'Gateway HTTP error: {exc.response.status_code}'})
    except httpx.RequestError as exc:
        log_fn(f'[err] cancel_task: {exc}')
        return result_to_text({'status': 'error', 'message': f'Gateway communication error: {exc}'})
