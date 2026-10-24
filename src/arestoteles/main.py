"""Start the vault service: `python -m arestoteles` (settings from the environment, see config.py)."""

from __future__ import annotations

import logging

import uvicorn

from .api import create_app
from .auth import EmpireAuth
from .config import Settings
from .service import VaultService

log = logging.getLogger("arestoteles")


def build_service(settings: Settings) -> VaultService:
    service = VaultService(settings, EmpireAuth(settings.auth_url))
    service.rebuild()   # answer from the clone right away; the loop pulls in the background
    return service


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = Settings.from_env()
    if not settings.push:
        log.warning("pushing is off (ARESTOTELES_PUSH=0): edits are committed in %s only", settings.vault)
    service = build_service(settings)
    uvicorn.run(create_app(service, run_loops=True), host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
