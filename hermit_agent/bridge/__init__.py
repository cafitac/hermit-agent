# bridge/ package — bridge.py 내용을 core.py로 이동, 기존 심볼 re-export
from .core import main, _run_gateway_mode, _send, _dispatch_sse_to_tui

__all__ = ["main", "_run_gateway_mode", "_send", "_dispatch_sse_to_tui"]
