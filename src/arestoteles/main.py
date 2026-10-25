"""Start the vault service: `python -m arestoteles` (settings from the environment, see config.py)."""

from __future__ import annotations

import logging

import uvicorn

from .api import create_app
from .auth import EmpireAuth
from .config import Settings
from .service import VaultService

log = logging.getLogger("arestoteles")


class _NoQueryInAccessLog(logging.Filter):
    """uvicorn's access lines without the query string: `?q=` carries what people search for, which the logs do not
    need (they keep address, time, method, path and status for 14 days; ares-empire/docs/PRIVACY.md)."""

    def filter(self, record: logging.LogRecord) -> bool:
        # uvicorn logs '%s - "%s %s HTTP/%s" %d' with (client, method, path with query, HTTP version, status).
        if isinstance(record.args, tuple) and len(record.args) == 5:
            client, method, path, version, status = record.args
            record.args = (client, method, str(path).split("?", 1)[0], version, status)
        return True


def quiet_access_log() -> None:
    """Called after uvicorn set up its loggers (its `Config` does that)."""
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _NoQueryInAccessLog) for f in access.filters):
        access.addFilter(_NoQueryInAccessLog())


def build_service(settings: Settings) -> VaultService:
    if not settings.allowed_users:
        log.warning("EMPIRE_ALLOWED_USERS is empty: no account can use the app")
    service = VaultService(settings, EmpireAuth(settings.auth_url, settings.allowed_users))
    service.rebuild()   # answer from the clone right away; the loop pulls in the background
    return service


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = Settings.from_env()
    if not settings.push:
        log.warning("pushing is off (ARESTOTELES_PUSH=0): edits are committed in %s only", settings.vault)
    service = build_service(settings)
    config = uvicorn.Config(create_app(service, run_loops=True), host=settings.host, port=settings.port, log_level="info")
    quiet_access_log()
    uvicorn.Server(config).run()


if __name__ == "__main__":
    main()
