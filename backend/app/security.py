import hmac
import hashlib
import time
from collections import defaultdict
from fastapi import Header, HTTPException, Request

from app.config import settings

_buckets: dict[str, list[float]] = defaultdict(list)


def rate_limit(key: str) -> None:
    now = time.time()
    window = _buckets[key]
    window[:] = [t for t in window if now - t < 60]
    if len(window) >= settings.RATE_LIMIT_PER_MIN:
        raise HTTPException(status_code=429, detail={"error": {"code": "rate_limited", "message": "Too many requests"}})
    window.append(now)


def require_invite(code: str | None) -> None:
    allowed = settings.invite_codes
    if not allowed:  # dev mode
        return
    if not code or code not in allowed:
        raise HTTPException(status_code=403, detail={"error": {"code": "invalid_invite", "message": "Invite code required"}})


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    if not x_admin_token or x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail={"error": {"code": "admin_forbidden", "message": "Invalid admin token"}})


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def hmac_sign(secret: str, payload: bytes) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()