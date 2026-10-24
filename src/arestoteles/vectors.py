"""The passages' embeddings on disk, by text hash (SQLite, one file per model), so a pull or an edit re-embeds only
the passages that changed and a restart embeds nothing that was embedded before.

Only vectors and hashes are stored, never text. A cache made by another model or other model settings (the spec's
fingerprint) is emptied when opened. Used from one thread at a time (the search's background worker).
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Iterable

import numpy as np

_CHUNK = 500   # SQLite's limit on query parameters is 999 on old builds


def key(text: str) -> bytes:
    return hashlib.sha256(text.encode("utf-8")).digest()


class VectorCache:
    def __init__(self, path: Path, fingerprint: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute("CREATE TABLE IF NOT EXISTS meta (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self._db.execute("CREATE TABLE IF NOT EXISTS vectors (hash BLOB PRIMARY KEY, vector BLOB NOT NULL)")
        row = self._db.execute("SELECT value FROM meta WHERE name = 'fingerprint'").fetchone()
        if row is None or row[0] != fingerprint:
            with self._db:
                self._db.execute("DELETE FROM vectors")
                self._db.execute("INSERT OR REPLACE INTO meta VALUES ('fingerprint', ?)", (fingerprint,))

    def get(self, keys: Iterable[bytes]) -> dict[bytes, np.ndarray]:
        keys = list(keys)
        found: dict[bytes, np.ndarray] = {}
        for start in range(0, len(keys), _CHUNK):
            chunk = keys[start:start + _CHUNK]
            marks = ",".join("?" * len(chunk))
            for k, blob in self._db.execute(f"SELECT hash, vector FROM vectors WHERE hash IN ({marks})", chunk):
                found[k] = np.frombuffer(blob, dtype=np.float32)
        return found

    def put(self, vectors: dict[bytes, np.ndarray]) -> None:
        with self._db:
            self._db.executemany("INSERT OR REPLACE INTO vectors VALUES (?, ?)",
                                 [(k, np.asarray(v, dtype=np.float32).tobytes()) for k, v in vectors.items()])

    def keep(self, keys: set[bytes]) -> int:
        """Forget every vector not in `keys` (texts no longer in the vault); returns how many went."""
        stale = [k for (k,) in self._db.execute("SELECT hash FROM vectors") if k not in keys]
        with self._db:
            for start in range(0, len(stale), _CHUNK):
                chunk = stale[start:start + _CHUNK]
                self._db.execute(f"DELETE FROM vectors WHERE hash IN ({','.join('?' * len(chunk))})", chunk)
        return len(stale)

    def __len__(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM vectors").fetchone()[0]

    def close(self) -> None:
        self._db.close()
