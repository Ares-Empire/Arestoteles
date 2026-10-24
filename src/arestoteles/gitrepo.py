"""The server's clone of the vault: the few git commands the sync loop and the edits need.

Commits (and rebased commits) are written as the Arestoteles app (docs/API.md), set per command with `-c`, so the
clone's own git config is never changed. Network commands have a timeout and never prompt.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger("arestoteles")

AUTHOR_NAME = "Patrik Breeck (Arestoteles app)"
AUTHOR_EMAIL = "287037715+carlsenares@users.noreply.github.com"


class GitError(Exception):
    pass


class Repo:
    def __init__(self, root: Path, remote: str = "origin", timeout: float = 60.0):
        self.root = root
        self.remote = remote
        self.timeout = timeout
        self._env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}

    def git(self, *args: str, check: bool = True, identity: bool = False) -> subprocess.CompletedProcess:
        command = ["git"]
        if identity:
            command += ["-c", f"user.name={AUTHOR_NAME}", "-c", f"user.email={AUTHOR_EMAIL}"]
        command += ["-C", str(self.root), *args]
        try:
            done = subprocess.run(command, capture_output=True, text=True, timeout=self.timeout, env=self._env)
        except subprocess.TimeoutExpired as e:
            raise GitError(f"git {args[0]} timed out") from e
        if check and done.returncode != 0:
            raise GitError(f"git {args[0]} failed: {done.stderr.strip()[:300]}")
        return done

    # ── reading ──
    def is_repo(self) -> bool:
        return self.root.is_dir() and self.git("rev-parse", "--git-dir", check=False).returncode == 0

    def head(self, short: bool = False) -> str:
        args = ("rev-parse", "--short", "HEAD") if short else ("rev-parse", "HEAD")
        return self.git(*args).stdout.strip()

    def branch(self) -> str:
        done = self.git("symbolic-ref", "--short", "HEAD", check=False)
        return done.stdout.strip() if done.returncode == 0 else "main"

    @property
    def upstream(self) -> str:
        return f"{self.remote}/{self.branch()}"

    def has_upstream(self) -> bool:
        return self.git("rev-parse", "--verify", "--quiet", self.upstream, check=False).returncode == 0

    def ahead_behind(self) -> tuple[int, int]:
        """(commits only here, commits only on the remote) against the last fetched state."""
        if not self.has_upstream():
            return 0, 0
        out = self.git("rev-list", "--left-right", "--count", f"HEAD...{self.upstream}").stdout.split()
        return int(out[0]), int(out[1])

    def changed_files(self, old: str, new: str) -> list[str]:
        return [p for p in self.git("diff", "--name-only", old, new).stdout.splitlines() if p]

    # ── syncing ──
    def fetch(self) -> bool:
        done = self.git("fetch", "--quiet", self.remote, check=False)
        if done.returncode != 0:
            log.warning("git fetch failed: %s", done.stderr.strip()[:300])
        return done.returncode == 0

    def fast_forward(self) -> None:
        self.git("merge", "--ff-only", "--quiet", self.upstream)

    def rebase(self) -> bool:
        """Replay the local commits on the remote ones. False (and nothing changed) on a real conflict."""
        done = self.git("rebase", self.upstream, check=False, identity=True)
        if done.returncode == 0:
            return True
        self.git("rebase", "--abort", check=False)
        return False

    def push(self) -> bool:
        done = self.git("push", "--quiet", self.remote, f"HEAD:refs/heads/{self.branch()}", check=False)
        if done.returncode != 0:
            log.warning("git push failed: %s", done.stderr.strip()[:300])
        return done.returncode == 0

    # ── writing ──
    def commit(self, paths: list[str], message: str) -> None:
        self.git("add", "--", *paths)
        self.git("commit", "--quiet", "-m", message, "--", *paths, identity=True)

    def reset_hard(self, ref: str) -> None:
        self.git("reset", "--hard", "--quiet", ref)

    def save_branch(self, name: str) -> None:
        """Keep the current local commits under a branch (locally, and on the remote when it can be reached)."""
        self.git("branch", "--force", name, "HEAD")
        self.git("push", "--quiet", self.remote, f"{name}:refs/heads/{name}", check=False)
