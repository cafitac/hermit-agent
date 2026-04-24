import queue


def test_gateway_permission_checker_fires_on_mode_change_callback():
    from hermit_agent.gateway.permission import GatewayPermissionChecker
    from hermit_agent.permissions import PermissionMode

    received = []
    q_in = queue.Queue()
    q_out = queue.Queue()
    q_out.put('yolo')
    checker = GatewayPermissionChecker(
        mode=PermissionMode.ALLOW_READ,
        question_queue=q_in,
        reply_queue=q_out,
        on_mode_change=lambda m: received.append(m),
    )
    # A bash tool call under ALLOW_READ will ask; user reply 'yolo' must fire the callback.
    result = checker.check('bash', {'command': 'echo hi'}, is_read_only=False)
    assert result is True
    assert received == [PermissionMode.YOLO]
    assert checker.mode == PermissionMode.YOLO


def test_gateway_permission_checker_without_callback_still_works():
    from hermit_agent.gateway.permission import GatewayPermissionChecker
    from hermit_agent.permissions import PermissionMode

    q_in = queue.Queue()
    q_out = queue.Queue()
    q_out.put('yolo')
    checker = GatewayPermissionChecker(
        mode=PermissionMode.ALLOW_READ,
        question_queue=q_in,
        reply_queue=q_out,
    )
    assert checker.check('bash', {'command': 'ls'}, is_read_only=False) is True
    assert checker.mode == PermissionMode.YOLO
