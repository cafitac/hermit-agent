import inspect


def test_bridge_imports_should_auto_recap():
    import hermit_agent.bridge as bridge_mod
    src = inspect.getsource(bridge_mod._run_gateway_mode)
    assert 'should_auto_recap' in src, 'bridge.py::_run_gateway_mode must call should_auto_recap'
    assert 'generate_recap' in src, 'bridge.py must call generate_recap to produce the auto-recap text'
