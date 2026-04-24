import inspect


def test_bridge_does_not_auto_resume_on_tui_startup():
    """TUI startup must NOT auto-resume previous sessions. Use /resume explicitly."""
    import hermit_agent.bridge as bridge_mod
    src = inspect.getsource(bridge_mod._run_gateway_mode)
    assert 'find_resumable_interactive_session' not in src, (
        '_run_gateway_mode must not auto-resume sessions on startup; '
        'user should use /resume explicitly'
    )


def test_bridge_does_not_show_auto_recap_on_tui_startup():
    """TUI startup must NOT show previous session recap — no TUI tool does this."""
    import hermit_agent.bridge as bridge_mod
    src = inspect.getsource(bridge_mod._run_gateway_mode)
    assert 'should_auto_recap' not in src, (
        '_run_gateway_mode must not show auto-recap on startup'
    )
    assert 'load_auto_recap_text' not in src, (
        '_run_gateway_mode must not call load_auto_recap_text on startup'
    )
