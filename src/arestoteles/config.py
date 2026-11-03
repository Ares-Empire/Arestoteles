"""Settings from the environment (on the server: the systemd unit, optionally /root/Arestoteles/vault.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


def _ids(value: str | None) -> frozenset[str]:
    """A comma-separated list of account ids; blanks and empty entries are dropped."""
    return frozenset(part.strip() for part in (value or "").split(",") if part.strip())


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
    # The Empire accounts that may use the app (EMPIRE_ALLOWED_USERS, PocketBase ids, comma-separated): its owner.
    # Empty = nobody, as in Aresium.
    allowed_users: frozenset[str] = frozenset()
    sync_interval: float = 60.0
    pull: bool = True    # off: never fetch (a local copy without its remote)
    push: bool = True    # off: commit edits but never push (a local copy)
    require_versions: bool = False   # enable after the owner installs the version-sending client
    ruby: str = "ruby"
    timezone: str = "Europe/Berlin"
    # search (docs/API.md → Search): the meaning model's files, fetched by `python -m arestoteles.meaning fetch`,
    # and the passages' embeddings kept by text hash, so a pull re-embeds only what changed
    models: Path = Path("/var/lib/arestoteles/models")
    search_model: str = "embeddinggemma-300m-q4"   # an id in meaning.MODELS; "off": words only
    search_cache: Path = Path("/var/lib/arestoteles/search")
    search_threads: int = 2   # CPU threads of the model (the server has 4 cores)

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
            allowed_users=_ids(env.get("EMPIRE_ALLOWED_USERS")),
            sync_interval=float(env.get("ARESTOTELES_SYNC_INTERVAL", d.sync_interval)),
            pull=_flag(env.get("ARESTOTELES_PULL"), d.pull),
            push=_flag(env.get("ARESTOTELES_PUSH"), d.push),
            require_versions=_flag(env.get("ARESTOTELES_REQUIRE_VERSIONS"), d.require_versions),
            ruby=env.get("ARESTOTELES_RUBY", d.ruby),
            timezone=env.get("ARESTOTELES_TZ", d.timezone),
            models=Path(env.get("ARESTOTELES_MODELS", d.models)),
            search_model=env.get("ARESTOTELES_SEARCH_MODEL", d.search_model).strip(),
            search_cache=Path(env.get("ARESTOTELES_SEARCH_CACHE", d.search_cache)),
            search_threads=int(env.get("ARESTOTELES_SEARCH_THREADS", d.search_threads)),
        )
