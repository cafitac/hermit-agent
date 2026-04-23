import pytest
import queue
from hermit_agent.gateway.permission import GatewayPermissionChecker
from hermit_agent.permissions import PermissionMode


def _checker_with_reply(reply: str):
    q_in = queue.Queue()
    q_out = queue.Queue()
    q_out.put(reply)
    return GatewayPermissionChecker(
        mode=PermissionMode.ALLOW_READ,
        question_queue=q_in,
        reply_queue=q_out,
    )


@pytest.mark.parametrize('reply', ['yolo', 'always', '2', 'Always allow (yolo)', 'ALWAYS ALLOW (YOLO)'])
def test_yolo_variants_accepted(reply):
    c = _checker_with_reply(reply)
    assert c.check('bash', {'command': 'ls'}, is_read_only=False) is True
    assert c.mode == PermissionMode.YOLO


@pytest.mark.parametrize('reply', ['y', 'yes', '1', '', 'Yes (once)', 'YES'])
def test_yes_variants_accepted(reply):
    c = _checker_with_reply(reply)
    assert c.check('bash', {'command': 'ls'}, is_read_only=False) is True
    # Single-shot yes should NOT flip to YOLO.
    if reply.strip().lower() not in ('yolo', 'always', '2', 'always allow (yolo)'):
        assert c.mode != PermissionMode.YOLO


@pytest.mark.parametrize('reply', ['n', 'no', 'No', 'NO'])
def test_no_variants_rejected(reply):
    c = _checker_with_reply(reply)
    assert c.check('bash', {'command': 'ls'}, is_read_only=False) is False


def test_attached_codex_app_server_permission_roundtrip_accepts(monkeypatch):
    c = _checker_with_reply("unused")
    monkeypatch.setattr(
        "hermit_agent.gateway.permission.await_attached_codex_app_server_response",
        lambda prompt, env=None: "Yes (once)",
    )
    assert c.check("bash", {"command": "ls"}, is_read_only=False) is True


def test_attached_codex_app_server_permission_roundtrip_can_flip_yolo(monkeypatch):
    c = _checker_with_reply("unused")
    monkeypatch.setattr(
        "hermit_agent.gateway.permission.await_attached_codex_app_server_response",
        lambda prompt, env=None: "Always allow (yolo)",
    )
    assert c.check("bash", {"command": "ls"}, is_read_only=False) is True
    assert c.mode == PermissionMode.YOLO
