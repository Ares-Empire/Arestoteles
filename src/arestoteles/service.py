"""The vault service: the current index, the sync loop (pull every 60 s, retry pushes) and the edit flow.

One lock covers everything that touches the clone (a pull, an edit), so the working tree is only ever changed by
one of them at a time. Readers never wait for it: `built` is replaced in one step after each rebuild.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from . import check, edits, notefile
from .auth import EmpireAuth
from .check import CheckResult
from .config import Settings
from .edits import EditError, Editor
from .gitrepo import GitError, Repo
from .index import Built, build
from .texts import Text, text

log = logging.getLogger("arestoteles")

STALE_SECONDS = 600   # health turns false when pulls or pushes have failed for longer than this


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class NotReady(Exception):
    pass


@dataclass
class EditOutcome:
    built: Built
    changed: list[str]
    pushed: bool
    warnings: list[str | Text]


class VaultService:
    def __init__(self, settings: Settings, auth: EmpireAuth, clock: Callable[[], datetime] = utc_now,
                 repo: Repo | None = None):
        self.settings = settings
        self.root: Path = settings.vault
        self.repo = repo or Repo(self.root)
        self.auth = auth
        self.clock = clock
        self.built: Built | None = None
        self.pulled: datetime | None = None
        self.pull_failing_since: datetime | None = None
        self.push_failing_since: datetime | None = None
        self.ahead = 0
        self._lock = threading.RLock()
        self._checks: dict[str, CheckResult] = {}

    # ── reading ──
    def current(self) -> Built:
        if self.built is None:
            raise NotReady
        return self.built

    def source(self, note_id: str) -> dict | None:
        path = self.current().paths.get(note_id)
        if path is None:
            return None
        try:
            raw = (self.root / path).read_bytes()
        except FileNotFoundError:
            return None
        return {"id": note_id, "version": notefile.blob_hash(raw), "markdown": notefile.split(notefile.decode(raw))[1]}

    def health(self) -> dict:
        now = self.clock()

        def failing(since: datetime | None) -> bool:
            return since is not None and (now - since).total_seconds() > STALE_SECONDS

        built = self.built
        return {"ok": built is not None and not failing(self.pull_failing_since) and not failing(self.push_failing_since),
                "commit": built.commit if built else "", "pulled": iso(self.pulled) if self.pulled else None,
                "pushed": self.ahead == 0, "notes": len(built.notes) if built else 0}

    # ── building ──
    def rebuild(self, force: bool = False) -> None:
        with self._lock:
            if not self.root.is_dir():
                log.warning("no vault at %s", self.root)
                return
            commit = self.repo.head(short=True) if self.repo.is_repo() else ""
            if not force and self.built is not None and self.built.commit == commit and commit:
                return
            started = self.clock()
            self.built = build(self.root, commit, iso(started))
            log.info("vault built at %s: %d notes, %d unresolved links", commit or "(no commit)",
                     len(self.built.notes), len(self.built.unresolved))

    # ── the sync loop ──
    def sync(self) -> None:
        with self._lock:
            if not self.repo.is_repo():
                self.rebuild()
                return
            if self.settings.pull:
                self._pull()
            if self.settings.push:
                self._push_pending()
            self.ahead = self.repo.ahead_behind()[0]
            self.rebuild()

    def _pull(self) -> bool:
        if not self.repo.fetch():
            self.pull_failing_since = self.pull_failing_since or self.clock()
            return False
        try:
            ahead, behind = self.repo.ahead_behind()
            if behind and not ahead:
                self.repo.fast_forward()
            elif behind and ahead and not self.repo.rebase():
                self._keep_conflict()
        except GitError as e:
            log.warning("pull failed: %s", e)
            self.pull_failing_since = self.pull_failing_since or self.clock()
            return False
        self.pulled, self.pull_failing_since = self.clock(), None
        return True

    def _keep_conflict(self) -> None:
        """Local commits that cannot be replayed on the remote ones: keep them on a branch, follow the remote."""
        name = f"arestoteles-app/conflict-{self.clock():%Y%m%d-%H%M%S}"
        self.repo.save_branch(name)
        self.repo.reset_hard(self.repo.upstream)
        log.warning("app commits conflict with the vault on GitHub; kept on branch %s", name)

    def _push_pending(self) -> bool:
        if self.repo.ahead_behind()[0] == 0:
            self.push_failing_since = None
            return True
        if self.repo.push():
            self.push_failing_since = None
            return True
        self.push_failing_since = self.push_failing_since or self.clock()
        return False

    def start_loop(self) -> Loop:
        return Loop(self, self.settings.sync_interval).start()

    # ── edits ──
    def edit(self, edit: dict) -> EditOutcome:
        with self._lock:
            built = self.current()
            if not self.repo.is_repo():
                raise NotReady
            before = self._check_for_head()
            now = self.clock().astimezone(self.settings.tz)
            editor = Editor(built, read=lambda path: (self.root / path).read_bytes(), today=now.date().isoformat(),
                            now=now)
            plan = edits.apply(edit, editor)
            if not plan.files:
                return EditOutcome(built, [], self.ahead == 0, [])
            originals = self._write(plan)
            after = check.run(self.root, self.settings.ruby)
            new = after.new_since(before)
            if new.errors:
                self._restore(originals, plan.created)
                raise EditError(422, "check_errors", errors="; ".join(new.errors))
            try:
                self.repo.commit(list(plan.files), plan.message)
            except GitError:
                self._restore(originals, plan.created)
                raise
            committed = self.repo.head()
            pushed = self._push_edit(plan)
            if self.repo.head() == committed:
                self._checks[committed] = after
            self.ahead = self.repo.ahead_behind()[0]
            self.rebuild()
            warnings: list[str | Text] = [text(after.skipped)] if after.skipped else list(new.warnings)
            return EditOutcome(self.current(), plan.changed, pushed, warnings)

    def _check_for_head(self) -> CheckResult:
        head = self.repo.head()
        if head not in self._checks:
            if len(self._checks) > 50:
                self._checks.clear()
            self._checks[head] = check.run(self.root, self.settings.ruby)
        return self._checks[head]

    def _write(self, plan: edits.Plan) -> dict[str, bytes]:
        originals: dict[str, bytes] = {}
        for path, content in plan.files.items():
            file = self.root / path
            if file.exists():
                originals[path] = file.read_bytes()
            crlf = b"\r\n" in originals.get(path, b"")
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(notefile.encode(content, crlf))
        return originals

    def _restore(self, originals: dict[str, bytes], created: list[str]) -> None:
        for path, raw in originals.items():
            (self.root / path).write_bytes(raw)
        for path in created:
            (self.root / path).unlink(missing_ok=True)

    def _push_edit(self, plan: edits.Plan) -> bool:
        """Push the edit's commit. Rejected: rebase on the remote and push again; a real conflict undoes the edit."""
        if not self.settings.push:
            return False
        if self.repo.push():
            self.push_failing_since = None
            return True
        if not self.repo.fetch():    # GitHub unreachable: the commit waits, the loop retries
            self.push_failing_since = self.push_failing_since or self.clock()
            return False
        if self.repo.ahead_behind()[1] == 0:   # not behind, still refused: keep the commit, retry later
            self.push_failing_since = self.push_failing_since or self.clock()
            return False
        if self.repo.rebase():
            pushed = self.repo.push()
            self.push_failing_since = None if pushed else (self.push_failing_since or self.clock())
            return pushed
        self.repo.reset_hard("HEAD~1")
        self._pull()
        self.rebuild(force=True)
        raise EditError(409, "conflict", current=plan.changed[0] if plan.changed else None)


class Loop:
    """The sync loop in a background thread: one sync right away, then one every `interval` seconds."""

    def __init__(self, service: VaultService, interval: float):
        self.service, self.interval = service, interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="arestoteles-sync", daemon=True)

    def start(self) -> Loop:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.service.sync()
            except Exception:  # the loop must survive anything; the next round tries again
                log.exception("sync round failed")
            self._stop.wait(self.interval)
