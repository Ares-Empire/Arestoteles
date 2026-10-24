"""The Empire login check (ares-empire/docs/ACCOUNTS.md → How a service checks a login), as Aresus does it.

PocketBase's auth-refresh must answer 200 and the account must be approved with `arestoteles` in its services.
Answers are cached 60 s per token, keyed by the token's SHA-256 (the token itself is never kept or logged).
Outages are never cached.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from threading import Lock
from typing import Callable

import httpx

SERVICE = "arestoteles"
CACHE_SECONDS = 60.0


@dataclass(frozen=True)
class Access:
    status: int          # 200 allowed, else 401 / 403 / 503
    error: str = ""      # a key of texts.TEXTS
    user_id: str = ""

    @property
    def allowed(self) -> bool:
        return self.status == 200


UNAUTHENTICATED = Access(401, "unauthenticated")
FORBIDDEN = Access(403, "forbidden")
UNAVAILABLE = Access(503, "login_unavailable")


def has_access(record: object) -> bool:
    return (isinstance(record, dict) and record.get("approved") is True
            and isinstance(record.get("services"), list) and SERVICE in record["services"])


class EmpireAuth:
    def __init__(self, base_url: str, client: httpx.Client | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.url = base_url.rstrip("/") + "/api/collections/users/auth-refresh"
        self.client = client or httpx.Client(timeout=5.0)
        self.clock = clock
        self._cache: dict[str, tuple[Access, float]] = {}
        self._lock = Lock()

    def check(self, token: str) -> Access:
        if not token:
            return UNAUTHENTICATED
        key = hashlib.sha256(token.encode()).hexdigest()
        now = self.clock()
        with self._lock:
            hit = self._cache.get(key)
        if hit and hit[1] > now:
            return hit[0]
        access = self._ask(token)
        if access is UNAVAILABLE:
            return access
        with self._lock:
            if len(self._cache) >= 1000:
                self._cache.clear()
            self._cache[key] = (access, now + CACHE_SECONDS)
        return access

    def _ask(self, token: str) -> Access:
        try:
            response = self.client.post(self.url, headers={"Authorization": token}, timeout=5.0)
        except httpx.HTTPError:
            return UNAVAILABLE
        if response.status_code in (400, 401):
            return UNAUTHENTICATED
        if response.status_code == 403:
            return FORBIDDEN
        if response.status_code != 200:
            return UNAVAILABLE
        try:
            record = response.json().get("record")
        except (ValueError, AttributeError):
            return UNAVAILABLE
        if not isinstance(record, dict) or not isinstance(record.get("id"), str) or not record["id"]:
            return UNAVAILABLE
        return Access(200, user_id=record["id"]) if has_access(record) else FORBIDDEN
