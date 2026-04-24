from __future__ import annotations

import queue

from hermit_agent.bridge_runtime import BridgeRuntime


def test_bridge_runtime_tracks_current_task_and_replaces_shutdown_event():
    runtime = BridgeRuntime(queue.Queue())
    first_event = runtime.sse_shutdown

    runtime.current_interactive_session_id = "interactive-1"
    runtime.mark_interactive_waiting()
    second_event = runtime.reset_sse_shutdown()
    runtime.clear_interactive_waiting()

    assert runtime.current_interactive_session_id == "interactive-1"
    assert runtime.interactive_waiting is False
    assert first_event is not second_event
