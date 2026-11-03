"""Recover an interrupted edit before serving or syncing the checkout.

The journal is durable before the first note changes. A commit is the boundary: before it, restore all original
bytes and the index; after it, keep the commit for pushing. Replacements are atomic, including during rollback.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from pathlib import Path

from . import notefile
from .edits import EditError, Plan
from .gitrepo import GitError, Repo


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def note_path(root: Path, path: str) -> Path:
    file = root / path
    if file.resolve() != root.resolve() / path:
        raise EditError(422, "symlink_note")
    return file


def temporary_prefix(file: Path) -> str:
    # A legal note name can already fill the filesystem's filename limit.
    return ".arestoteles-" + hashlib.sha256(file.name.encode("utf-8")).hexdigest() + "."


def replace(file: Path, raw: bytes) -> None:
    file.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=temporary_prefix(file), suffix=".tmp", dir=file.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(file.stat().st_mode & 0o777 if file.exists() else 0o644)
        os.replace(temporary, file)
        sync_directory(file.parent)
    finally:
        temporary.unlink(missing_ok=True)


def remember_reads(repo: Repo, commit: str, paths: set[str]) -> None:
    """Keep edit dependencies locally with the commit, including across service restarts and rebases."""
    replace(repo.git_path(f"arestoteles-edits/{commit}.json"), json.dumps(sorted(paths)).encode("utf-8"))


def pending_reads(repo: Repo) -> set[str] | None:
    paths: set[str] = set()
    commits = repo.git("rev-list", f"{repo.upstream}..HEAD").stdout.splitlines()
    for commit in commits:
        file = repo.git_path(f"arestoteles-edits/{commit}.json")
        if not file.exists():
            return None   # older/unrecognised commits: cannot prove a rebase preserves their dependencies
        paths.update(json.loads(file.read_text(encoding="utf-8")))
    return paths


class Transaction:
    def __init__(self, repo: Repo):
        self.repo = repo
        self.journal = repo.git_path("arestoteles-edit.json")

    def begin(self, plan: Plan) -> None:
        if self.journal.exists():
            raise GitError("an earlier edit still needs recovery")
        originals = {}
        for path in plan.files:
            file = note_path(self.repo.root, path)
            if path in plan.created and file.exists():
                raise GitError("new note would overwrite an existing file")
            originals[path] = base64.b64encode(file.read_bytes()).decode("ascii") if file.exists() else None
        payload = {"head": self.repo.head(), "originals": originals, "reads": sorted(plan.reads)}
        replace(self.journal, json.dumps(payload).encode("utf-8"))

    def write(self, plan: Plan) -> None:
        for path, content in plan.files.items():
            file = note_path(self.repo.root, path)
            raw = file.read_bytes() if file.exists() else b""
            replace(file, notefile.encode(content, b"\r\n" in raw))

    def recover(self) -> None:
        if not self.journal.exists():
            return
        data = json.loads(self.journal.read_text(encoding="utf-8"))
        self.repo.require_idle()
        if self.repo.head() == data["head"]:
            for path, original in data["originals"].items():
                file = self.repo.root / path
                if original is None:
                    file.unlink(missing_ok=True)
                    if file.parent.exists():
                        sync_directory(file.parent)
                else:
                    replace(file, base64.b64decode(original))
            self.repo.git("reset", "--quiet", "HEAD", "--",
                          *(f":(literal){p}" for p in data["originals"]))
        elif self.repo.git("rev-parse", "HEAD^").stdout.strip() != data["head"]:
            raise GitError("HEAD changed unexpectedly during edit recovery; journal kept")
        # A killed process cannot run replace()'s finally block. These names are reserved for this writer.
        for path in data["originals"]:
            file = self.repo.root / path
            if file.parent.exists():
                for temporary in file.parent.iterdir():
                    if temporary.name.startswith(temporary_prefix(file)) and temporary.name.endswith(".tmp"):
                        temporary.unlink()
                sync_directory(file.parent)
        self.finish()

    def finish(self) -> None:
        data = json.loads(self.journal.read_text(encoding="utf-8"))
        head = self.repo.head()
        if head != data["head"]:
            remember_reads(self.repo, head, set(data["reads"]))
        self.journal.unlink(missing_ok=True)
        sync_directory(self.journal.parent)
