"""Settings from the environment (on the server: the systemd unit, optionally /root/Arestoteles/vault.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


def _flag(value: str | None, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8099
    vault: Path = Path("/var/lib/arestoteles/vault")   # the server's clone of carlsenares/opinions
    auth_url: str = "http://127.0.0.1:8090"            # PocketBase (the Empire accounts)
    sync_interval: float = 60.0
    pull: bool = True    # off: never fetch (a local copy without its remote)
    push: bool = True    # off: commit edits but never push (a local copy)
    ruby: str = "ruby"
    timezone: str = "Europe/Berlin"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        d = cls()
        return cls(
            host=env.get("HOST", d.host),
            port=int(env.get("PORT", d.port)),
            vault=Path(env.get("ARESTOTELES_VAULT", d.vault)),
            auth_url=env.get("EMPIRE_AUTH_URL", d.auth_url).rstrip("/"),
            sync_interval=float(env.get("ARESTOTELES_SYNC_INTERVAL", d.sync_interval)),
            pull=_flag(env.get("ARESTOTELES_PULL"), d.pull),
            push=_flag(env.get("ARESTOTELES_PUSH"), d.push),
            ruby=env.get("ARESTOTELES_RUBY", d.ruby),
            timezone=env.get("ARESTOTELES_TZ", d.timezone),
        )
