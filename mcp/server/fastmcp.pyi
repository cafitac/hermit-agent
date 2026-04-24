from __future__ import annotations

from typing import Any, Callable


class _ElicitData:
    answer: Any


class _ElicitResult:
    action: str
    data: _ElicitData | None
    content: dict[str, Any] | None


class _SessionContext:
    session: Any


class Context:
    async def elicit(self, message: str, schema: Any) -> _ElicitResult: ...


class FastMCP:
    _mcp_server: Any

    def __init__(self, name: str, host: str = ..., port: int = ...) -> None: ...
    def tool(self, *, name: str = ..., description: str = ...) -> Callable[[Callable[..., Any]], Callable[..., Any]]: ...
    def get_context(self) -> _SessionContext: ...
    def run(self, transport: str = ...) -> None: ...
    def streamable_http_app(self) -> Any: ...
