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
        if done.returncode != 0:
            raise GitError("detached HEAD; refusing to guess a branch to push")
        return done.stdout.strip()

    def git_path(self, name: str) -> Path:
        path = Path(self.git("rev-parse", "--git-path", name).stdout.strip())
        return path if path.is_absolute() else self.root / path

    def require_idle(self) -> None:
        """Never abort someone else's operation or delete a lock that might still be held."""
        branch = self.branch()
        if self.git_path(f"refs/heads/{branch}.lock").exists():
            raise GitError("clone needs attention: branch lock")
        directory = self.git_path(".")
        for name in ("index.lock", "HEAD.lock", "rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD",
                     "REVERT_HEAD", "sequencer"):
            if (directory / name).exists():
                raise GitError(f"clone needs attention: {name}")

    def require_clean(self) -> None:
        self.require_idle()
        if self.git("status", "--porcelain", "--untracked-files=all").stdout:
            raise GitError("clone has uncommitted files; refusing to overwrite them")

    @property
    def upstream(self) -> str:
        return f"{self.remote}/{self.branch()}"

    def has_upstream(self) -> bool:
        return self.git("rev-parse", "--verify", "--quiet", self.upstream, check=False).returncode == 0

    def ahead_behind(self) -> tuple[int, int]:
        """(commits only here, commits only on the remote) against the last fetched state."""
        if not self.has_upstream():
            return int(self.git("rev-list", "--count", "HEAD").stdout), 0
        out = self.git("rev-list", "--left-right", "--count", f"HEAD...{self.upstream}").stdout.split()
        return int(out[0]), int(out[1])

    def changed_files(self, old: str, new: str) -> list[str]:
        return [p for p in self.git("diff", "--no-renames", "--name-only", "-z", old, new).stdout.split("\0") if p]

    # ── syncing ──
    def fetch(self) -> bool:
        return self._network("fetch", "--quiet", "--prune", self.remote)

    def _network(self, *args: str) -> bool:
        try:
            done = self.git(*args, check=False)
        except GitError as e:
            log.warning("%s", e)
            return False
        if done.returncode != 0:
            log.warning("git %s failed: %s", args[0], done.stderr.strip()[:300])
        return done.returncode == 0

    def fast_forward(self) -> None:
        self.git("merge", "--ff-only", "--quiet", self.upstream)

    def rebase(self) -> bool:
        """Replay the local commits on the remote ones. False (and nothing changed) on a real conflict."""
        self.require_clean()
        before = self.head()
        # A durable ref survives a killed process or an abort that cannot restore the checkout.
        self.git("update-ref", "refs/arestoteles/rebase-original", before)
        try:
            done = self.git("rebase", "--reapply-cherry-picks", self.upstream, check=False, identity=True)
        except GitError:
            self._abort_rebase(before)
            raise
        if done.returncode == 0:
            # The service checks the resulting vault before removing the recovery ref or pushing.
            return True
        conflict = bool(self.git("ls-files", "--unmerged").stdout)
        self._abort_rebase(before)
        if conflict:
            return False
        raise GitError("rebase failed without a content conflict; local commits kept")

    def _abort_rebase(self, before: str) -> None:
        if self.git_path("rebase-merge").exists() or self.git_path("rebase-apply").exists():
            self.git("rebase", "--abort")
        if self.head() != before:
            raise GitError("rebase did not restore HEAD; original kept at refs/arestoteles/rebase-original")
        self.require_clean()
        self.git("update-ref", "-d", "refs/arestoteles/rebase-original")

    def recover_rebase(self) -> None:
        ref = "refs/arestoteles/rebase-original"
        if self.git("rev-parse", "--verify", "--quiet", ref, check=False).returncode == 0:
            self.require_clean()
            self.reset_hard(ref)
            self.git("update-ref", "-d", ref)

    def push(self) -> bool:
        self.require_idle()
        return self._network("push", "--quiet", self.remote, f"HEAD:refs/heads/{self.branch()}")

    # ── writing ──
    def commit(self, paths: list[str], message: str) -> None:
        self.git("add", "--", *paths)
        self.git("commit", "--quiet", "-m", message, "--", *paths, identity=True)

    def reset_hard(self, ref: str) -> None:
        self.git("reset", "--hard", "--quiet", ref)

    def save_branch(self, name: str) -> None:
        """Keep local commits before resetting. Publishing is retried independently by the sync loop."""
        self.git("branch", name, "HEAD")

    def conflict_branches(self) -> list[str]:
        return self.git("for-each-ref", "--format=%(refname:short)",
                        "refs/heads/arestoteles-app/conflict-*").stdout.splitlines()

    def push_conflicts(self) -> bool:
        names = self.conflict_branches()
        return not names or self._network("push", "--quiet", self.remote,
                                           *(f"refs/heads/{n}:refs/heads/{n}" for n in names))
