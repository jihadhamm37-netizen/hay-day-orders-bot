"""Session cookies (JWT), CSRF double-submit and permission checks for the web panel."""
from __future__ import annotations

import secrets
import time
from collections import defaultdict, deque

import jwt
from fastapi import Depends, HTTPException, Request, Response

from ..core import Core
from ..services import admins

SESSION_COOKIE = "hd_session"
CSRF_COOKIE = "hd_csrf"
ALGO = "HS256"


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"


def make_token(core: Core, payload: dict, ttl_seconds: int) -> str:
    now = int(time.time())
    return jwt.encode({**payload, "iat": now, "exp": now + ttl_seconds}, core.config.jwt_secret, algorithm=ALGO)


def read_token(core: Core, token: str, purpose: str) -> dict | None:
    try:
        data = jwt.decode(token, core.config.jwt_secret, algorithms=[ALGO])
    except jwt.PyJWTError:
        return None
    return data if data.get("p") == purpose else None


def set_session(core: Core, response: Response, admin: dict) -> None:
    ttl = core.config.session_hours * 3600
    token = make_token(core, {"p": "session", "sub": str(admin["id"]), "ver": admin["token_version"]}, ttl)
    secure = core.config.cookie_secure
    response.set_cookie(SESSION_COOKIE, token, max_age=ttl, httponly=True, secure=secure, samesite="strict", path="/")
    response.set_cookie(CSRF_COOKIE, secrets.token_urlsafe(24), max_age=ttl, httponly=False, secure=secure,
                        samesite="strict", path="/")


def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def get_core(request: Request) -> Core:
    return request.app.state.core


async def current_admin(request: Request, core: Core = Depends(get_core)) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    data = read_token(core, token, "session") if token else None
    if not data:
        raise HTTPException(401, "يجب تسجيل الدخول.")
    a = await admins.get_admin(core, int(data["sub"]))
    if not a or not a["is_active"] or a["token_version"] != data.get("ver"):
        raise HTTPException(401, "انتهت الجلسة، سجّل الدخول من جديد.")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        sent = request.headers.get("x-csrf-token", "")
        cookie = request.cookies.get(CSRF_COOKIE, "")
        if not cookie or not secrets.compare_digest(sent, cookie):
            raise HTTPException(403, "رمز الحماية (CSRF) غير صالح. حدّث الصفحة.")
    return a


def require(perm: str):
    async def dep(admin: dict = Depends(current_admin)) -> dict:
        if not admins.has_perm(admin["role"], perm):
            raise HTTPException(403, "ليست لديك صلاحية لهذا الإجراء.")
        return admin
    return dep


def actor_of(admin: dict) -> str:
    return f"web:{admin['username']}"


class RateLimiter:
    """Simple in-memory sliding window per key (IP)."""

    def __init__(self, limit: int, window: float):
        self.limit, self.window = limit, window
        self.hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str) -> bool:
        now = time.monotonic()
        q = self.hits[key]
        while q and q[0] < now - self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        if len(self.hits) > 10_000:
            self.hits.clear()
        return True
