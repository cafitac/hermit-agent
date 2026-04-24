from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ElicitRequestFormParams:
    message: str
    requestedSchema: dict[str, Any]


@dataclass
class ElicitRequest:
    params: ElicitRequestFormParams


@dataclass
class ElicitResult:
    action: str
    content: dict[str, Any] | None = None


@dataclass
class JSONRPCNotification:
    jsonrpc: str
    method: str
    params: dict[str, Any]


@dataclass
class JSONRPCMessage:
    message: Any
