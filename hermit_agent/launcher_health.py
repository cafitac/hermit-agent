from __future__ import annotations

import json
import sys
from urllib.error import URLError
from urllib.request import urlopen


def gateway_identity_ok(url: str, *, timeout: float = 1.0) -> bool:
    try:
        with urlopen(f"{url.rstrip('/')}/health", timeout=timeout) as response:
            if not (200 <= getattr(response, "status", 200) < 300):
                return False
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, OSError, ValueError, json.JSONDecodeError):
        return False
    return payload.get("service") == "hermit_agent-gateway"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("Usage: python -m hermit_agent.launcher_health <gateway-url>", file=sys.stderr)
        return 2
    return 0 if gateway_identity_ok(args[0]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
