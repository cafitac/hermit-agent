"""Health check components for /health endpoint.

Each function performs ONE independent HTTP probe and returns a structured
result. Composed by gateway/__init__.py::health() via asyncio.gather to
parallelize the LLM/ollama probes (worst case 13s sequential → ~5s parallel).
"""
from __future__ import annotations

import time
from typing import Any

import httpx


async def check_llm(*, llm_url: str, llm_api_key: str | None) -> dict[str, Any]:
    """Probe the configured LLM endpoint.

    Returns dict with keys: status, latency_ms, error (optional).
    For local ollama checks /api/tags; for external APIs checks /models.
    """
    is_ollama = "localhost" in llm_url or "127.0.0.1" in llm_url
    check_url = llm_url.replace("/v1", "/api/tags") if is_ollama else llm_url.rstrip("/") + "/models"
    headers: dict[str, str] = {}
    if llm_api_key:
        headers["Authorization"] = f"Bearer {llm_api_key}"

    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(check_url, headers=headers, timeout=5.0)
        latency_ms = int((time.monotonic() - t0) * 1000)
        if r.status_code < 500:
            # 2xx and 4xx both mean the server is reachable (401/403 = auth required)
            error = f"HTTP {r.status_code} (server reachable)" if r.status_code >= 400 else None
            return {"status": "operational", "latency_ms": latency_ms, "error": error}
        return {"status": "major", "latency_ms": latency_ms, "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"status": "major", "latency_ms": None, "error": str(e)[:100]}


async def check_ollama_active(*, ollama_base: str) -> dict[str, Any]:
    """Probe ollama /api/ps for currently-loaded models.

    Returns dict with keys: status, models (list of {id,size_gb,expires_at}),
    active_names (set of names — used to dedupe against the full list).
    """
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{ollama_base}/api/ps", timeout=3.0)
        if r.status_code != 200:
            return {"status": "operational", "models": [], "active_names": set()}
        models: list[dict[str, Any]] = []
        active_names: set[str] = set()
        for m in r.json().get("models", []):
            name = m.get("name", "")
            if not name:
                continue
            models.append({
                "id": name,
                "size_gb": round(m.get("size", 0) / 1e9, 1),
                "expires_at": m.get("expires_at"),
            })
            active_names.add(name)
            active_names.add(name.replace(":latest", ""))
        return {"status": "operational", "models": models, "active_names": active_names}
    except Exception:
        # /api/ps is best-effort; failure does not mark ollama unavailable here
        # (the /api/tags probe in check_ollama_installed is the authoritative source)
        return {"status": "operational", "models": [], "active_names": set()}


async def check_ollama_installed(*, ollama_base: str) -> dict[str, Any]:
    """Probe ollama /api/tags for the full installed-model list.

    Returns dict with keys: status, count, models (list of {id,provider,size_gb?}).
    A failure here marks the ollama component as unavailable.
    """
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{ollama_base}/api/tags", timeout=5.0)
        if r.status_code != 200:
            return {"status": "unavailable", "count": 0, "models": []}
        ollama_models = r.json().get("models", [])
        models: list[dict[str, Any]] = []
        for m in ollama_models:
            name = m.get("name", "")
            if not name:
                continue
            entry: dict[str, Any] = {"id": name, "provider": "ollama"}
            if m.get("size"):
                entry["size_gb"] = round(m["size"] / 1e9, 1)
            models.append(entry)
        return {"status": "operational", "count": len(ollama_models), "models": models}
    except Exception:
        return {"status": "unavailable", "count": 0, "models": []}
