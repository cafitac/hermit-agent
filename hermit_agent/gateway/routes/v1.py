from __future__ import annotations
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from ..admission import AdmissionController, AdmissionDenied
from ..auth import AuthContext, get_current_user
from ..db import allowed_platforms
from ..errors import ErrorCode
from ..providers import OllamaAdapter, ProviderAdapter, ZaiAdapter
from ..routing import UnknownPlatform, resolve_platform

logger = logging.getLogger("hermit_agent.gateway.routes.v1")
router = APIRouter()


_admission: AdmissionController | None = None
_adapters: dict[str, ProviderAdapter] = {}


def _get_admission() -> AdmissionController:
    global _admission
    if _admission is None:
        from ...config import load_settings
        cfg = load_settings()
        _admission = AdmissionController(
            ollama_max_loaded=int(cfg.get("ollama_max_loaded", 1)),
            external_max_concurrent=int(cfg.get("external_max_concurrent", 10)),
            ollama_url=cfg.get("ollama_url", "http://localhost:11434/v1"),
        )
    return _admission


def _derive_anthropic_base_url(llm_url: str) -> str:
    """Derive the z.ai Anthropic endpoint from the configured OpenAI-compat llm_url.

    z.ai exposes ``/api/paas/v4`` (OpenAI-compat) and ``/api/anthropic`` (Anthropic)
    under the same host. When users configure ``llm_url`` for the OpenAI-compat
    endpoint, swap the path suffix to point at the Anthropic endpoint.
    """
    base = llm_url.rstrip("/")
    if "/api/paas" in base:
        return base.split("/api/paas", 1)[0] + "/api/anthropic"
    # Fallback: assume same host, append /api/anthropic
    if base.endswith("/v1"):
        base = base[:-3]
    return base.rstrip("/") + "/api/anthropic"


def _get_adapter(platform: str) -> ProviderAdapter:
    """Return a cached provider adapter for *platform*.

    Adapters are lazily constructed from settings and cached for the process
    lifetime, matching the semantics of ``_get_admission``.
    """
    if platform in _adapters:
        return _adapters[platform]

    from ...config import load_settings
    cfg = load_settings()

    adapter: ProviderAdapter
    if platform == "local":
        adapter = OllamaAdapter(
            base_url=cfg.get("ollama_url", "http://localhost:11434/v1"),
        )
    elif platform == "z.ai":
        llm_url = cfg.get("llm_url", "https://api.z.ai/api/coding/paas/v4")
        adapter = ZaiAdapter(
            openai_base_url=llm_url,
            anthropic_base_url=_derive_anthropic_base_url(llm_url),
            api_key=cfg.get("llm_api_key", ""),
        )
    else:
        raise HTTPException(
            status_code=400,
            detail={
                "code": ErrorCode.INVALID_REQUEST.value,
                "message": f"no adapter configured for platform '{platform}'",
                "type": "gateway_error",
            },
        )

    _adapters[platform] = adapter
    return adapter


@router.get("/models")
async def list_models(auth: AuthContext = Depends(get_current_user)):
    from ...config import load_settings
    cfg = load_settings()
    model_id = cfg.get("model", "hermit_agent")
    return {
        "object": "list",
        "data": [
            {
                "id": model_id,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "hermit_agent",
            }
        ],
    }


@router.post("/chat/completions")
async def chat_completions(
    request: Request,
    auth: AuthContext = Depends(get_current_user),
):
    # No Pydantic validation — unknown OpenAI fields pass through verbatim.
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=400,
            detail={
                "code": ErrorCode.INVALID_REQUEST.value,
                "message": "request body must be a JSON object",
                "type": "gateway_error",
            },
        )

    model = body.get("model") or ""
    if not model:
        from ...config import load_settings
        model = load_settings().get("model", "")

    try:
        platform = resolve_platform(model)
    except UnknownPlatform:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unknown_platform",
                "message": f"no route for model '{model}'",
                "type": "gateway_error",
            },
        )

    allowed = await allowed_platforms(auth.api_key)
    if platform not in allowed:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "forbidden_platform",
                "message": f"key not authorized for platform '{platform}'",
                "type": "gateway_error",
            },
        )

    try:
        token = await _get_admission().acquire(model)
    except AdmissionDenied as denied:
        raise HTTPException(
            status_code=503,
            detail={
                "code": ErrorCode.SERVER_BUSY.value,
                "message": str(denied),
                "type": "gateway_error",
            },
            headers={"Retry-After": str(denied.retry_after)},
        )

    adapter = _get_adapter(platform)
    stream = bool(body.get("stream", False))

    if stream:
        async def _gen():
            try:
                async for chunk in adapter.forward_openai(body, stream=True):
                    yield chunk
            finally:
                token.release()

        return StreamingResponse(
            _gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    try:
        body_bytes = b""
        async for chunk in adapter.forward_openai(body, stream=False):
            body_bytes += chunk
        return Response(content=body_bytes, media_type="application/json")
    finally:
        token.release()
