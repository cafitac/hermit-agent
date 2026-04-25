from __future__ import annotations


def test_dispatch_sse_waiting_event_maps_to_permission_prompt(monkeypatch):
    from hermit_agent import bridge as bridge_mod
    import hermit_agent.bridge.core as bridge_core

    sent = []
    monkeypatch.setattr(bridge_core, "_send", lambda msg: sent.append(msg))

    bridge_mod._dispatch_sse_to_tui(
        {"type": "waiting", "question": "Need input", "options": ["A", "B"]}
    )

    assert sent == [{
        "type": "permission_ask",
        "tool": "ask",
        "summary": "Need input",
        "options": ["A", "B"],
    }]


def test_dispatch_sse_permission_event_uses_tool_name(monkeypatch):
    from hermit_agent import bridge as bridge_mod
    import hermit_agent.bridge.core as bridge_core

    sent = []
    monkeypatch.setattr(bridge_core, "_send", lambda msg: sent.append(msg))

    bridge_mod._dispatch_sse_to_tui(
        {
            "type": "permission_ask",
            "tool_name": "bash",
            "question": "[Permission request] bash",
            "options": ["Yes", "No"],
        }
    )

    assert sent == [{
        "type": "permission_ask",
        "tool": "bash",
        "summary": "[Permission request] bash",
        "options": ["Yes", "No"],
    }]


def test_dispatch_sse_progress_event_maps_to_tool_result(monkeypatch):
    from hermit_agent import bridge as bridge_mod
    import hermit_agent.bridge.core as bridge_core

    sent = []
    monkeypatch.setattr(bridge_core, "_send", lambda msg: sent.append(msg))

    bridge_mod._dispatch_sse_to_tui({"type": "progress", "message": "step ok"})

    assert sent == [{
        "type": "tool_result",
        "content": "step ok",
        "is_error": False,
    }]
