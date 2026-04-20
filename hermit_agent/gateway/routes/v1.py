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


def _derive_anthropic_base_url(openai_base_url: str) -> str:
    """Fallback Anthropic endpoint derivation for z.ai-shaped URLs.

    Used when the provider block does not specify `anthropic_base_url`.
    z.ai exposes `/api/coding/paas/v4` (OpenAI-compat) and `/api/anthropic`
    under the same host.
    """
    base = openai_base_url.rstrip("/")
    if "/api/paas" in base or "/api/coding/paas" in base:
        host = base.split("/api/", 1)[0]
        return host + "/api/anthropic"
    if base.endswith("/v1"):
        base = base[:-3]
    return base.rstrip("/") + "/api/anthropic"


def _get_adapter(platform: str) -> ProviderAdapter:
    """Return a cached provider adapter for *platform*.

    Adapters are lazily constructed from `cfg["providers"][platform]` and
    cached for the process lifetime, matching `_get_admission`'s semantics.
    """
    if platform in _adapters:
        return _adapters[platform]

    from ...config import get_provider_cred, load_settings
    cfg = load_settings()

    adapter: ProviderAdapter
    if platform == "local":
        adapter = OllamaAdapter(
            base_url=cfg.get("ollama_url", "http://localhost:11434/v1"),
        )
    elif platform == "z.ai":
        cred = get_provider_cred(cfg, "z.ai")
        openai_base_url = cred.get("base_url") or "https://api.z.ai/api/coding/paas/v4"
        adapter = ZaiAdapter(
            openai_base_url=openai_base_url,
            anthropic_base_url=cred.get("anthropic_base_url") or _derive_anthropic_base_url(openai_base_url),
            api_key=cred.get("api_key", ""),
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
    from ...config import load_settings, get_primary_model
    cfg = load_settings()
    model_id = get_primary_model(cfg, available_only=True) or get_primary_model(cfg) or "hermit_agent"
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
        from ...config import load_settings, get_primary_model
        cfg = load_settings()
        model = get_primary_model(cfg, available_only=True) or get_primary_model(cfg) or ""

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
