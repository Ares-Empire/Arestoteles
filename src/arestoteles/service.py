"""The vault service: the current index, the sync loop (pull every 60 s, retry pushes) and the edit flow.

One lock covers everything that touches the clone (a pull, an edit), so the working tree is only ever changed by
one of them at a time. Index readers never wait; source readers take the lock to avoid uncommitted bytes.
"""

from __future__ import annotations

import logging
import tempfile
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
from .search import Search
from .texts import Text, text
from .transaction import Transaction, note_path, pending_reads, remember_reads

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
                 repo: Repo | None = None, search: Search | None = None):
        self.settings = settings
        self.root: Path = settings.vault
        self.repo = repo or Repo(self.root)
        self.auth = auth
        self.clock = clock
        self.search = search or Search.from_settings(settings)   # follows every rebuild (docs/API.md → Search)
        self.built: Built | None = None
        self.pulled: datetime | None = None
        self.pull_failing_since: datetime | None = None
        self.push_failing_since: datetime | None = None
        self.ahead = 0
        self.conflicts: list[str] = []
        self.blocked = False
        self._lock = threading.RLock()
        self._checks: dict[str, CheckResult] = {}
        self._unversioned_ops: set[str] = set()

    # ── reading ──
    def current(self) -> Built:
        if self.built is None:
            raise NotReady
        return self.built

    def source(self, note_id: str) -> dict | None:
        with self._lock:
            if self.blocked:
                raise NotReady
            paths = self.current().paths
            matches = [i for i in paths if notefile.name_key(i) == notefile.name_key(note_id)]
            if len(matches) != 1:
                return None
            note_id = matches[0]
            try:
                raw = (self.root / paths[note_id]).read_bytes()
            except FileNotFoundError:
                return None
            return {"id": note_id, "version": notefile.blob_hash(raw),
                    "markdown": notefile.split(notefile.decode(raw))[1]}

    def health(self) -> dict:
        now = self.clock()

        def failing(since: datetime | None) -> bool:
            return since is not None and (now - since).total_seconds() > STALE_SECONDS

        built = self.built
        return {"ok": built is not None and not self.blocked and not self.conflicts
                      and not failing(self.pull_failing_since) and not failing(self.push_failing_since),
                "commit": built.commit if built else "", "pulled": iso(self.pulled) if self.pulled else None,
                "pushed": self.ahead == 0 and not self.conflicts and not self.blocked,
                "notes": len(built.notes) if built else 0}

    # ── building ──
    def rebuild(self, force: bool = False) -> None:
        with self._lock:
            if not self.root.is_dir():
                log.warning("no vault at %s", self.root)
                return
            try:
                if self.repo.is_repo():
                    Transaction(self.repo).recover()
                    self.repo.require_idle()
                    self.repo.recover_rebase()
                    self._status()
                    commit = self.repo.head(short=True)
                else:
                    commit = ""
            except (GitError, OSError):
                self.blocked = True
                log.exception("clone cannot be indexed safely")
                return
            if not force and self.built is not None and self.built.commit == commit and commit:
                return
            started = self.clock()
            built = build(self.root, commit, iso(started))
            try:
                self.search.update(built)   # the words at once; the meaning in the background
            except Exception:   # the search must never keep the vault from updating
                log.exception("the search index could not be built; the search keeps the previous one")
            self.built = built
            log.info("vault built at %s: %d notes, %d unresolved link targets", commit or "(no commit)",
                     len(self.built.notes), len(self.built.unresolved))

    # ── the sync loop ──
    def sync(self) -> None:
        with self._lock:
            if not self.repo.is_repo():
                self.rebuild()
                return
            try:
                self._prepare()
                if self.settings.pull:
                    self._pull()
                if self.settings.push:
                    self._push_pending()
                    self.repo.push_conflicts()
                self._status()
                self.rebuild()
            except (GitError, OSError):
                self.blocked = True
                log.exception("clone needs attention; sync left it intact")

    def _status(self) -> None:
        self.ahead = self.repo.ahead_behind()[0]
        self.conflicts = self.repo.conflict_branches()

    def _prepare(self) -> None:
        Transaction(self.repo).recover()
        self.repo.require_clean()
        self.blocked = False
        self.rebuild()

    def _pull(self) -> bool:
        try:
            if not self.repo.fetch():
                self.pull_failing_since = self.pull_failing_since or self.clock()
                return False
            ahead, behind = self.repo.ahead_behind()
            if behind and not ahead:
                self.repo.fast_forward()
            elif behind and ahead and not self._rebase():
                self._keep_conflict()
        except GitError as e:
            log.warning("pull failed: %s", e)
            self.pull_failing_since = self.pull_failing_since or self.clock()
            return False
        self.pulled, self.pull_failing_since = self.clock(), None
        return True

    def _rebase(self) -> bool:
        """Git can merge valid changes into an invalid vault. Check against the remote's own baseline."""
        original = self.repo.head()
        dependencies = pending_reads(self.repo)
        if dependencies is None:
            return False
        base = self.repo.git("merge-base", "HEAD", self.repo.upstream).stdout.strip()
        changed = [notefile.name_key(p) for p in self.repo.changed_files(base, self.repo.upstream)]
        names = {notefile.name_key(p) for p in dependencies}
        if any(path in names or any(d.endswith("/") and path.startswith(d) for d in names)
               for path in changed):
            return False
        with tempfile.TemporaryDirectory(prefix="arestoteles-check-") as directory:
            checkout = Path(directory) / "vault"
            self.repo.git("worktree", "add", "--quiet", "--detach", str(checkout), self.repo.upstream)
            try:
                baseline = check.run(checkout, self.settings.ruby)
            finally:
                self.repo.git("worktree", "remove", "--force", str(checkout))
        if not self.repo.rebase():
            return False
        try:
            after = check.run(self.root, self.settings.ruby)
            valid = not after.new_since(baseline).errors and not (not baseline.skipped and after.skipped)
            if not valid:
                self.repo.reset_hard(original)
            else:
                for commit in self.repo.git("rev-list", f"{self.repo.upstream}..HEAD").stdout.splitlines():
                    remember_reads(self.repo, commit, dependencies)
        except Exception:
            self.repo.reset_hard(original)
            raise
        # Retain the recovery ref if checking or restoring failed.
        self.repo.git("update-ref", "-d", "refs/arestoteles/rebase-original")
        return valid

    def _keep_conflict(self) -> None:
        """Local commits that cannot be replayed on the remote ones: keep them on a branch, follow the remote."""
        name = f"arestoteles-app/conflict-{self.clock():%Y%m%d-%H%M%S}"
        stem, suffix = name, 1
        while name in self.repo.conflict_branches():
            suffix += 1
            name = f"{stem}-{suffix}"
        self.repo.save_branch(name)
        self.conflicts = self.repo.conflict_branches()
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
            try:
                return self._edit(edit)
            except (GitError, OSError):
                try:
                    self.repo.require_clean()
                    self.blocked = Transaction(self.repo).journal.exists()
                except (GitError, OSError):
                    self.blocked = True
                log.exception("edit could not be completed")
                raise EditError(503, "edit_unavailable") from None

    def _edit(self, edit: dict) -> EditOutcome:
        if not self.repo.is_repo():
            raise NotReady
        self._prepare()
        built = self.current()
        before = self._check_for_head()
        now = self.clock().astimezone(self.settings.tz)
        editor = Editor(built, read=lambda path: note_path(self.root, path).read_bytes(), today=now.date().isoformat(),
                        now=now)
        plan = edits.apply(edit, editor, require_versions=self.settings.require_versions)
        if edit.get("version") is None and (edit.get("note") or edit.get("position") or edit.get("about")):
            op = edit["op"]
            if op not in self._unversioned_ops:
                log.warning("unversioned %s edit allowed (ARESTOTELES_REQUIRE_VERSIONS=0)", op)
                self._unversioned_ops.add(op)
        if not plan.files:
            return EditOutcome(built, [], self.health()["pushed"], self._conflict_warnings())
        transaction = Transaction(self.repo)
        transaction.begin(plan)
        try:
            transaction.write(plan)
            after = check.run(self.root, self.settings.ruby)
            new = after.new_since(before)
            if after.skipped and not before.skipped:
                raise EditError(503, "check_failed")
            if new.errors:
                raise EditError(422, "check_errors", errors="; ".join(new.errors))
            self.repo.commit(list(plan.files), plan.message)
        except Exception:
            transaction.recover()
            raise
        transaction.finish()
        committed = self.repo.head()
        self.rebuild()
        pushed = self._push_edit(plan)
        if self.repo.head() == committed:
            self._checks[committed] = after
        if not self.blocked:
            self._status()
        self.rebuild()
        warnings: list[str | Text] = [text(after.skipped)] if after.skipped else list(new.warnings)
        return EditOutcome(self.current(), plan.changed, pushed, warnings + self._conflict_warnings())

    def _conflict_warnings(self) -> list[Text]:
        return [text("pending_conflicts", branches=", ".join(self.conflicts))] if self.conflicts else []

    def _check_for_head(self) -> CheckResult:
        head = self.repo.head()
        if head not in self._checks:
            if len(self._checks) > 50:
                self._checks.clear()
            self._checks[head] = check.run(self.root, self.settings.ruby)
        return self._checks[head]

    def _push_edit(self, plan: edits.Plan) -> bool:
        try:
            return self._try_push_edit(plan)
        except GitError as e:
            # The edit is already committed. A network/operational error must not look like an unsaved edit.
            self.push_failing_since = self.push_failing_since or self.clock()
            log.warning("committed edit is waiting: %s", e)
            try:
                self.repo.require_clean()
            except GitError:
                self.blocked = True
            return False

    def _try_push_edit(self, plan: edits.Plan) -> bool:
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
        if self._rebase():
            pushed = self.repo.push()
            self.push_failing_since = None if pushed else (self.push_failing_since or self.clock())
            return pushed
        self.repo.reset_hard("HEAD~1")
        self._pull()
        self._status()
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
