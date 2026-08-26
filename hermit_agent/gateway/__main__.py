from __future__ import annotations
import logging
import os
import sys


def main() -> None:
    # Create log directory (before basicConfig)
    log_dir = os.path.expanduser("~/.hermit")
    os.makedirs(log_dir, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(os.path.join(log_dir, "gateway.log")),
        ],
    )

    import uvicorn

    host = os.environ.get("HERMIT_GATEWAY_HOST", "127.0.0.1")
    port = int(os.environ.get("HERMIT_GATEWAY_PORT", "8765"))

    uvicorn.run(
        "hermit_agent.gateway:app",
        host=host,
        port=port,
        workers=1,  # SSE asyncio.Queue requires a single process
        log_level="info",
    )


if __name__ == "__main__":
    main()
