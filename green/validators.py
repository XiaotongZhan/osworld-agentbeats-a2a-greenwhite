# green/validators.py
import os
from fastapi import Request, HTTPException

def ensure_python_backend_only():
    mode = "python-api (no http)" if not os.getenv("OSWORLD_VM_BASE_URL") else "http backend (DISALLOWED)"
    return (os.getenv("OSWORLD_VM_BASE_URL") in (None, "", "null", "None")), mode

def _auth_disabled() -> bool:
    return str(os.getenv("GREEN_REQUIRE_AUTH", "true")).lower() == "false"

def _expected_token() -> str | None:
    return os.getenv("GREEN_AUTH_TOKEN")

def _extract_token(request: Request, path_token: str | None = None) -> str | None:
    # 1) Authorization: Bearer xxx
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    # 2) X-Auth-Token
    hdr = request.headers.get("x-auth-token")
    if hdr:
        return hdr.strip()
    # 3) ?token=xxx
    q = request.query_params.get("token")
    if q:
        return q.strip()
    # 4) /t/<token>/...
    if path_token:
        return path_token.strip()
    return None

def require_auth(request: Request, path_token: str | None = None) -> None:
    if _auth_disabled():
        return
    expected = _expected_token()
    if not expected:
        raise HTTPException(status_code=401, detail="Auth required but GREEN_AUTH_TOKEN is not set")
    got = _extract_token(request, path_token)
    if got != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")