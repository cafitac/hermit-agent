from __future__ import annotations

import queue

from hermit_agent.bridge_runtime import BridgeRuntime


def test_bridge_runtime_tracks_current_task_and_replaces_shutdown_event():
    runtime = BridgeRuntime(queue.Queue())
    first_event = runtime.sse_shutdown

    runtime.current_task_id = "task-1"
    runtime.clear_current_task()
    second_event = runtime.reset_sse_shutdown()

    assert runtime.current_task_id is None
    assert first_event is not second_event
