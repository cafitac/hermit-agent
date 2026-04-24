from __future__ import annotations
import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from .db import init_db
from ._singletons import sse_manager, MAX_WORKERS
from .task_store import expire_tasks, init_semaphore

logger = logging.getLogger("hermit_agent.gateway")

_gateway_start_time = time.monotonic()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    sse_manager.attach_loop(asyncio.get_running_loop())
    init_semaphore(MAX_WORKERS)

    async def _sweep():
        while True:
            await asyncio.sleep(600)
            expire_tasks(sse_manager=sse_manager)

    sweep_task = asyncio.create_task(_sweep())
    logger.info("HermitAgent AI Gateway starting (max_workers=%d)", MAX_WORKERS)
    yield
    sweep_task.cancel()
    logger.info("HermitAgent AI Gateway shutting down")


app = FastAPI(title="HermitAgent AI Gateway", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    """GitHub-style status page — JSON format.

    Returns overall status, component health, available models, worker pool usage.
    """
    from .task_store import active_worker_count, _tasks_lock, _tasks
    from ..config import load_settings

    components = {}
    overall = "operational"

    # ── Gateway itself (always operational — it responded) ──
    components["gateway"] = {
        "status": "operational",
        "uptime_seconds": int(time.monotonic() - _gateway_start_time),
        "version": "1.0.0",
    }

    # ── Worker Pool ──
    active = active_worker_count()
    worker_pct = (active / MAX_WORKERS * 100) if MAX_WORKERS > 0 else 0
    worker_status = "operational" if worker_pct < 80 else ("degraded" if worker_pct < 95 else "major")
    components["worker_pool"] = {
        "status": worker_status,
        "active": active,
        "max": MAX_WORKERS,
        "utilization_pct": round(worker_pct, 1),
    }
    if worker_status != "operational":
        overall = "degraded" if overall == "operational" else overall

    # ── Active Tasks ──
    _ACTIVE_STATUSES = {"running", "waiting"}
    with _tasks_lock:
        task_statuses = {}
        for state in _tasks.values():
            task_statuses[state.status] = task_statuses.get(state.status, 0) + 1
    active_total = sum(v for k, v in task_statuses.items() if k in _ACTIVE_STATUSES)
    components["tasks"] = {
        "status": "operational",
        "active_total": active_total,
        "breakdown": task_statuses,
    }

    # ── LLM connection status ──
    from ..config import select_llm_endpoint, get_primary_model
    cfg = load_settings()
    # Resolve upstream for the configured default model — ollama or
    # providers[<slug>] per the active routing rules.
    primary_model = get_primary_model(cfg, available_only=True) or get_primary_model(cfg)
    llm_url, llm_api_key = select_llm_endpoint(primary_model, cfg)
    if not llm_url:
        llm_url = cfg.get("ollama_url", "http://localhost:11434/v1")
    llm_status = "operational"
    llm_latency_ms = None
    llm_error = None

    try:
        import httpx
        # For local ollama use /api/tags, for external API use /models to check connection
        is_ollama = "localhost" in llm_url or "127.0.0.1" in llm_url
        check_url = llm_url.replace("/v1", "/api/tags") if is_ollama else llm_url.rstrip("/") + "/models"
        headers = {}
        if llm_api_key:
            headers["Authorization"] = f"Bearer {llm_api_key}"

        t0 = time.monotonic()
        async with httpx.AsyncClient() as client:
            r = await client.get(check_url, headers=headers, timeout=5.0)
        llm_latency_ms = int((time.monotonic() - t0) * 1000)

        if r.status_code < 500:
            # Both 2xx and 4xx mean the server is alive (401/403 = auth required but server healthy)
            llm_status = "operational"
            if r.status_code >= 400:
                llm_error = f"HTTP {r.status_code} (server reachable)"
        else:
            llm_status = "major"
            llm_error = f"HTTP {r.status_code}"
    except Exception as e:
        llm_status = "major"
        llm_error = str(e)[:100]

    components["llm"] = {
        "status": llm_status,
        "url": llm_url.replace("://", "://**redacted**@") if "@" in llm_url else llm_url,
        "latency_ms": llm_latency_ms,
    }
    if llm_error:
        components["llm"]["error"] = llm_error
    if llm_status != "operational" and overall == "operational":
        overall = "degraded" if llm_status == "degraded" else "major"

    # ── LLM provider detection ──
    _PROVIDER_MAP = {
        "z.ai": "z.ai",
        "openai.com": "openai",
        "api.openai.com": "openai",
        "anthropic.com": "anthropic",
        "minimax": "minimax",
        "localhost": "ollama",
        "127.0.0.1": "ollama",
    }
    llm_provider = "unknown"
    for host_pattern, provider_name in _PROVIDER_MAP.items():
        if host_pattern in llm_url:
            llm_provider = provider_name
            break

    # ── Model list ──
    models = []
    active_models = []
    default_model = primary_model

    # Configured default model (cloud API → always active)
    if default_model:
        models.append({"id": default_model, "provider": llm_provider, "default": True})
        active_models.append({"id": default_model, "provider": llm_provider, "default": True})

    # Always check local ollama models (regardless of configured LLM)
    ollama_status = "operational"
    ollama_model_count = 0
    ollama_active_detail = []
    try:
        import httpx

        # 1) Query active models loaded in memory first (/api/ps)
        active_names: set[str] = set()
        try:
            async with httpx.AsyncClient() as client:
                r_ps = await client.get("http://localhost:11434/api/ps", timeout=3.0)
            if r_ps.status_code == 200:
                for m in r_ps.json().get("models", []):
                    name = m.get("name", "")
                    if name:
                        ollama_active_detail.append({
                            "id": name,
                            "size_gb": round(m.get("size", 0) / 1e9, 1),
                            "expires_at": m.get("expires_at"),
                        })
                        active_names.add(name)
                        active_names.add(name.replace(":latest", ""))
                        if name != default_model:
                            active_models.append({"id": name, "provider": "ollama"})
        except Exception:
            pass

        # 2) Full list of installed models (/api/tags)
        async with httpx.AsyncClient() as client:
            r2 = await client.get("http://localhost:11434/api/tags", timeout=5.0)
        if r2.status_code == 200:
            ollama_models = r2.json().get("models", [])
            ollama_model_count = len(ollama_models)
            for m in ollama_models:
                name = m.get("name", "")
                if name and name != default_model:
                    size_gb = round(m.get("size", 0) / 1e9, 1) if m.get("size") else None
                    models.append({
                        "id": name,
                        "provider": "ollama",
                        **({"size_gb": size_gb} if size_gb else {}),
                    })
    except Exception:
        ollama_status = "unavailable"

    components["ollama"] = {
        "status": ollama_status,
        "model_count": ollama_model_count,
        "active_count": len(ollama_active_detail),
        "active": ollama_active_detail,
    }

    # ── Response ──
    return {
        "status": overall,
        "service": "hermit_agent-gateway",
        "version": "1.0.0",
        "components": components,
        "models": models,
        "active_models": active_models,
    }

templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)

from .routes.tasks import router as tasks_router              # noqa: E402
from .routes.interactive_sessions import router as interactive_sessions_router  # noqa: E402
from .routes.dashboard import router as dashboard_router      # noqa: E402
from .routes.v1 import router as v1_router                    # noqa: E402
from .routes.anthropic import router as anthropic_router      # noqa: E402

app.include_router(tasks_router)
app.include_router(interactive_sessions_router)
app.include_router(dashboard_router)
app.include_router(v1_router, prefix="/v1")
app.include_router(anthropic_router, prefix="/anthropic")

try:
    from mcp.server.fastmcp import FastMCP
    from .mcp_tools import register_mcp_tools
    _mcp = FastMCP("hermit_agent-gateway")
    register_mcp_tools(_mcp)
    app.mount("/mcp", _mcp.streamable_http_app())
    logger.info("MCP endpoint mounted at /mcp")
except (AttributeError, ImportError) as e:
    logger.warning("MCP mount skipped (%s). CC MCP connection unavailable.", e)
