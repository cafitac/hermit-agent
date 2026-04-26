from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from ..auth import AuthContext, get_current_user
from ..db import query_usage, query_recent_tasks, list_api_keys, create_api_key, delete_api_key, lookup_api_key
from ..errors import ErrorCode, gateway_error

logger = logging.getLogger("hermit_agent.gateway.routes.dashboard")
router = APIRouter()

_COOKIE_NAME = "gateway_session"


async def _check_dashboard_auth(request: Request) -> bool:
    """Dashboard authentication via cookie or API key."""
    session = request.cookies.get(_COOKIE_NAME)
    if session and await lookup_api_key(session):
        return True
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and await lookup_api_key(auth[7:]):
        return True
    return False


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not await _check_dashboard_auth(request):
        return RedirectResponse(url="/auth", status_code=302)

    from .. import templates
    usage = await query_usage(user=None, days=7)
    recent = await query_recent_tasks(limit=20)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"usage": usage, "recent": recent},
    )


@router.get("/auth", response_class=HTMLResponse)
async def auth_page(request: Request):
    return HTMLResponse("""
<!DOCTYPE html>
<html>
<head><title>HermitAgent Gateway — Login</title></head>
<body>
<h2>HermitAgent AI Gateway</h2>
<form method="post" action="/auth">
  <label>API Key: <input type="password" name="api_key" /></label>
  <button type="submit">Login</button>
</form>
</body>
</html>
""")


@router.post("/auth")
async def auth_login(
    request: Request,
    api_key: str = Form(...),
):
    if await lookup_api_key(api_key) is None:
        raise gateway_error(ErrorCode.UNAUTHORIZED)

    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(_COOKIE_NAME, api_key, httponly=True, samesite="strict")
    return response


@router.get("/api/usage")
async def api_usage(
    user: str | None = None,
    days: int = 7,
    auth: AuthContext = Depends(get_current_user),
):
    data = await query_usage(user=user, days=days)
    return {"data": data, "days": days, "user": user}


# ─── API Key management ───────────────────────────────────────────────────────


class ApiKeyRequest(BaseModel):
    api_key: str
    user: str


@router.get("/api/keys")
async def api_list_keys(auth: AuthContext = Depends(get_current_user)):
    keys = await list_api_keys()
    # Show only last 4 characters of api_key
    for k in keys:
        full = k["api_key"]
        k["api_key_masked"] = "****" + full[-4:] if len(full) > 4 else full
        del k["api_key"]
    return {"keys": keys}


@router.post("/api/keys")
async def api_create_key(req: ApiKeyRequest, auth: AuthContext = Depends(get_current_user)):
    await create_api_key(req.api_key, req.user, grant_all_platforms=True)
    return {"status": "ok", "user": req.user}


@router.delete("/api/keys/{api_key}")
async def api_delete_key(api_key: str, auth: AuthContext = Depends(get_current_user)):
    deleted = await delete_api_key(api_key)
    if not deleted:
        raise gateway_error(ErrorCode.TASK_NOT_FOUND)
    return {"status": "deleted"}
