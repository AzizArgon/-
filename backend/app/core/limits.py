"""Limits of the public server: login attempts and registrations per IP (in memory), daily usage (in the DB)."""

import time
from collections import defaultdict, deque
from datetime import date

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models import UsageCounter


def client_ip(request: Request) -> str:
    """nginx puts the visitor's IP (taken from Cloudflare's CF-Connecting-IP) into X-Real-IP.

    The header is trusted only from nginx on the same machine, otherwise anyone could send a fake one.
    """
    host = request.client.host if request.client else ""
    if host in ("127.0.0.1", "::1"):
        return request.headers.get("x-real-ip", host)
    return host


class SlidingWindow:
    """Counts events per key over the last `seconds`; one backend process, so memory is enough."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def count(self, key: str, seconds: int) -> int:
        hits = self._hits[key]
        while hits and hits[0] < time.monotonic() - seconds:
            hits.popleft()
        return len(hits)

    def hit(self, key: str) -> None:
        self._hits[key].append(time.monotonic())

    def clear(self) -> None:
        self._hits.clear()


login_failures = SlidingWindow()
registrations = SlidingWindow()


def too_many(code: str, **params) -> HTTPException:
    return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, {"code": code, **params})


def check_login_allowed(ip: str) -> None:
    window = settings.login_window_minutes * 60
    if settings.login_max_failures and login_failures.count(ip, window) >= settings.login_max_failures:
        raise too_many("too_many_logins", minutes=settings.login_window_minutes)


def check_register_allowed(ip: str) -> None:
    if settings.register_per_hour and registrations.count(ip, 3600) >= settings.register_per_hour:
        raise too_many("too_many_registrations")


def used_today(db: Session, key: str) -> int:
    row = db.get(UsageCounter, (date.today(), key))
    return row.count if row else 0


def spend(db: Session, key: str) -> None:
    row = db.get(UsageCounter, (date.today(), key)) or UsageCounter(day=date.today(), key=key, count=0)
    row.count += 1
    db.add(row)


def spend_import(db: Session, store_id: int) -> None:
    """A file, a text or a retry: checked against the store's and the server's daily limits (no commit here)."""
    store_key = f"imports:store:{store_id}"
    if settings.seller_daily_imports and used_today(db, store_key) >= settings.seller_daily_imports:
        raise too_many("import_limit_store", limit=settings.seller_daily_imports)
    if settings.server_daily_imports and used_today(db, "imports") >= settings.server_daily_imports:
        raise too_many("import_limit_server")
    spend(db, store_key)
    spend(db, "imports")


def spend_ai_request() -> bool:
    """False when the server's daily AI limit is used up; otherwise counts one request."""
    if not settings.server_daily_ai_requests:
        return True
    with SessionLocal() as db:
        if used_today(db, "ai") >= settings.server_daily_ai_requests:
            return False
        spend(db, "ai")
        db.commit()
    return True
