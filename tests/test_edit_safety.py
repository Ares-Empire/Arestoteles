"""Edit-loss regressions, using only the made-up vault and temporary git remotes."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
import subprocess
import sys
import threading
import unicodedata

import pytest
from fastapi.testclient import TestClient

from arestoteles.api import create_app
from arestoteles.gitrepo import GitError
from conftest import APP, edit, git

PRESS = "Topics/Printing press/Printing press.md"
DISCUSS = "Inbox/2026-10-23 2110 discuss Printing press.md"


def hook(world, name, body):
    path = world.vault / ".git" / "hooks" / name
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(0o755)
    return path


def raw_edit(client, **body):
    return client.post("/api/arestoteles/edits", headers=APP, json=body)


def test_an_unversioned_position_edit_cannot_overwrite_a_newer_view(world):
    service = world.service(require_versions=True)
    client = TestClient(create_app(service))
    world.laptop_commit(PRESS, lambda t: t.replace("Printers were businessmen first", "Printers took risks"))
    service.sync()
    before = (world.vault / PRESS).read_bytes()
    answer = raw_edit(client, op="reword_position", position="Printing press#2", text="Old phone wording.")
    assert answer.status_code == 428
    assert (world.vault / PRESS).read_bytes() == before


def test_operational_rebase_failure_keeps_the_edit_pending(client, world, service):
    hook(world, "pre-rebase", "exit 1")
    world.laptop_commit("Glossary.md", lambda t: t + "\nA laptop addition.\n")
    answer = edit(client, op="confirm_position", position="Printing press#2")
    assert answer.status_code == 200
    assert answer.json()["pushed"] is False
    assert "*(draft)*" not in (world.vault / PRESS).read_text()
    assert service.repo.ahead_behind() == (1, 1)


@pytest.mark.parametrize("command", ["push", "fetch"])
def test_network_timeout_reports_a_committed_pending_edit(client, world, service, monkeypatch, command):
    original = service.repo.git

    def timeout(*args, **kwargs):
        if args[0] == command:
            raise GitError("injected network timeout")
        if command == "fetch" and args[0] == "push":
            return subprocess.CompletedProcess(args, 1, "", "offline")
        return original(*args, **kwargs)

    monkeypatch.setattr(service.repo, "git", timeout)
    answer = edit(client, op="confirm_position", position="Printing press#2")
    assert answer.status_code == 200
    assert answer.json()["pushed"] is False
    assert answer.json()["vault"]["commit"] == service.repo.head(short=True)
    assert service.health()["pushed"] is False
    monkeypatch.setattr(service.repo, "git", original)
    service.sync()
    assert service.health()["pushed"] is True


def test_failed_commit_restores_the_index_too(client, world):
    hook(world, "pre-commit", "exit 1")
    before = (world.vault / PRESS).read_bytes()
    quiet = TestClient(client.app, raise_server_exceptions=False)
    answer = edit(quiet, op="confirm_position", position="Printing press#2")
    assert (world.vault / PRESS).read_bytes() == before
    assert git(world.vault, "status", "--porcelain").stdout == ""
    assert answer.status_code == 503


def test_failure_halfway_through_a_multifile_edit_restores_every_file(client, world, monkeypatch):
    from arestoteles import transaction

    originals = {p: (world.vault / p).read_bytes() for p in (PRESS, DISCUSS)}
    write = transaction.replace

    def fail_once(path, raw):
        if path == world.vault / DISCUSS:
            monkeypatch.setattr(transaction, "replace", write)
            path.write_bytes(raw[:12])
            raise OSError("injected short write")
        return write(path, raw)

    monkeypatch.setattr(transaction, "replace", fail_once)
    answer = edit(TestClient(client.app, raise_server_exceptions=False),
                  op="drop_position", position="Printing press#1", why="A test.")
    assert {p: (world.vault / p).read_bytes() for p in originals} == originals
    assert git(world.vault, "status", "--porcelain").stdout == ""
    assert answer.status_code == 503


def test_source_never_reads_an_uncommitted_edit(client, world, service, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    old = service.source("Printing press")

    def paused_commit(*args):
        entered.set()
        assert release.wait(10)
        raise GitError("injected rejected commit")

    monkeypatch.setattr(service.repo, "commit", paused_commit)
    with ThreadPoolExecutor(2) as pool:
        quiet = TestClient(client.app, raise_server_exceptions=False)
        editing = pool.submit(edit, quiet, op="confirm_position", position="Printing press#2")
        assert entered.wait(10)
        reading = pool.submit(service.source, "Printing press")
        try:
            try:
                observed = reading.result(timeout=0.1)
            except TimeoutError:  # A reader may wait for the edit's lock.
                pass
            else:
                assert observed == old
        finally:
            release.set()
        assert editing.result().status_code == 503
        assert reading.result() == old


@pytest.mark.parametrize("stage", ["write", "commit", "after_commit"])
def test_process_death_during_edit_recovers_on_restart(world, stage):
    before = {p: (world.vault / p).read_bytes() for p in (PRESS, DISCUSS)}
    code = '''
import os, signal, sys
from pathlib import Path
from arestoteles.service import VaultService
from arestoteles.config import Settings
from arestoteles.models import DropPosition
from arestoteles import transaction
service = VaultService(Settings(vault=Path(sys.argv[1]), pull=False, push=False, search_model="off"), None)
service.rebuild()
commit = service.repo.commit
def die(*args):
    if sys.argv[2] == "after_commit":
        commit(*args)
    os.kill(os.getpid(), signal.SIGKILL)
service.repo.commit = die
if sys.argv[2] == "write":
    replace = transaction.os.replace
    def die_during_replace(source, target):
        if Path(target).suffix == ".md":
            os.kill(os.getpid(), signal.SIGKILL)
        replace(source, target)
    transaction.os.replace = die_during_replace
payload = {"op": "drop_position", "position": "Printing press#1", "why": "A test."}
if "version" in DropPosition.model_fields:
    payload["version"] = service.current().notes["Printing press"]["version"]
service.edit(payload)
'''
    done = subprocess.run([sys.executable, "-c", code, str(world.vault), stage], capture_output=True)
    assert done.returncode == -9, done.stderr.decode()
    restarted = world.service(push=False)
    assert git(world.vault, "status", "--porcelain").stdout == ""
    if stage == "after_commit":
        assert (world.vault / PRESS).read_bytes() != before[PRESS]
        assert restarted.health()["pushed"] is False
    else:
        assert {p: (world.vault / p).read_bytes() for p in before} == before


def test_restart_reports_pending_commits(world):
    service = world.service(push=False)
    assert edit(TestClient(create_app(service)), op="confirm_position", position="Printing press#2").status_code == 200
    restarted = world.service()
    assert restarted.health()["pushed"] is False


def test_missing_remote_branch_is_not_reported_as_pushed(world):
    git(world.vault, "update-ref", "-d", "refs/remotes/origin/main")
    service = world.service(pull=False, push=False)
    answer = edit(TestClient(create_app(service)), op="confirm_position", position="Printing press#2")
    assert answer.status_code == 200
    assert service.health()["pushed"] is False


@pytest.mark.parametrize("name", ["index.lock", "HEAD.lock", "refs/heads/main.lock"])
def test_a_stuck_clone_reports_unhealthy_and_refuses_edits(client, world, service, name):
    lock = world.vault / ".git" / name
    lock.touch()
    answer = edit(TestClient(client.app, raise_server_exceptions=False),
                  op="confirm_position", position="Printing press#2")
    assert answer.status_code == 503
    service.sync()
    assert service.health()["ok"] is False
    assert lock.exists()  # Never guess whether another git process still owns a lock.
    lock.unlink()  # The operator has established that this test lock is stale.
    service.sync()
    assert service.health()["ok"] is True


def test_conflict_branches_are_unique_and_visible(client, world, service):
    hook_path = hook(world, "pre-push", "exit 1")
    assert edit(client, op="confirm_position", position="Printing press#2").json()["pushed"] is False
    world.laptop_commit(PRESS, lambda t: t.replace("what sold.** *(draft)*", "what sold, nothing more.**"))
    service.sync()
    first = git(world.vault, "for-each-ref", "--format=%(objectname)", "refs/heads/arestoteles-app/").stdout.strip()
    assert first
    assert edit(client, op="reword_position", position="Printing press#2", text="Another app view.").status_code == 200
    world.laptop_commit(PRESS, lambda t: t.replace("what sold, nothing more.", "what people wanted."))
    service.sync()  # Same clock second: must not replace the first recovery branch.
    refs = git(world.vault, "for-each-ref", "--format=%(objectname)", "refs/heads/arestoteles-app/").stdout.splitlines()
    assert len(refs) == 2 and first in refs
    assert service.health()["ok"] is False
    hook_path.unlink()
    service.sync()
    remote_refs = git(world.remote, "for-each-ref", "--format=%(objectname)", "refs/heads/arestoteles-app/").stdout.splitlines()
    assert set(remote_refs) == set(refs)


def test_ignored_quick_note_collision_cannot_overwrite_a_file(client, world):
    path = world.vault / "Inbox/2026-10-24 1805 hidden thought.md"
    path.write_text("---\ntype: inbox\nstatus: new\n---\nAn existing thought.\n")
    # The index was built before this file existed. Ignored files are not in git status either.
    with (world.vault / ".git/info/exclude").open("a") as f:
        f.write("\nInbox/2026-10-24 1805 hidden thought.md\n")
    answer = edit(TestClient(client.app, raise_server_exceptions=False), op="quick_note", text="hidden thought")
    assert "An existing thought." in path.read_text()
    assert answer.status_code != 200 or answer.json()["changed"] != [path.stem]


def test_invalid_utf8_is_not_silently_replaced_by_an_edit(world):
    path = world.vault / PRESS
    path.write_bytes(path.read_bytes() + b"\nOld bytes: \xff\n")
    git(world.vault, "commit", "-qam", "A legacy encoding")
    service = world.service(push=False)
    before = path.read_bytes()
    answer = edit(TestClient(create_app(service)), op="confirm_position", position="Printing press#2")
    assert answer.status_code == 422
    assert path.read_bytes() == before


def test_nfc_request_edits_an_nfd_filename(world):
    name = unicodedata.normalize("NFD", "Bücher")
    path = world.vault / f"Inbox/{name}.md"
    path.write_text("---\ntype: inbox\nstatus: new\n---\nA made-up note.\n")
    git(world.vault, "add", "--", str(path))
    git(world.vault, "commit", "-qm", "A decomposed name")
    service = world.service(push=False)
    client = TestClient(create_app(service))
    answer = edit(client, op="set_inbox_status", note="Bücher", status="processed")
    assert answer.status_code == 200
    assert "status: processed" in path.read_text()


def test_git_pathspec_metacharacters_do_not_stage_another_note(world):
    special = world.vault / "Inbox/[ab].md"
    other = world.vault / "Inbox/a.md"
    for path in (special, other):
        path.write_text("---\ntype: inbox\nstatus: new\n---\nOriginal.\n")
    git(world.vault, "add", "-A")
    git(world.vault, "commit", "-qm", "Names with brackets")
    service = world.service(push=False)
    client = TestClient(create_app(service))
    answer = edit(client, op="set_inbox_status", note="[ab]", status="processed")
    assert answer.status_code == 200
    assert git(world.vault, "show", "HEAD:Inbox/[ab].md").stdout == special.read_text()
    assert "status: new" in other.read_text()


@pytest.mark.parametrize("pending", [False, True])
def test_a_clean_rebase_must_not_publish_a_broken_vault(client, world, service, pending):
    name = "2026-10-24 1805 same title"
    if pending:
        reject = hook(world, "pre-push", "exit 1")
        assert edit(client, op="quick_note", text="same title").json()["pushed"] is False
        reject.unlink()
    other = world.laptop / f"Library/Actors/{name}.md"
    other.write_text("---\ntype: actor\n---\nA laptop note with the same name.\n")
    git(world.laptop, "add", "-A")
    git(world.laptop, "commit", "-qm", "Laptop creates the same name in another folder")
    git(world.laptop, "push", "-q")
    remote_before = git(world.remote, "rev-parse", "main").stdout
    if pending:
        service.sync()
        assert service.health()["ok"] is False
        assert service.repo.conflict_branches()
    else:
        answer = edit(client, op="quick_note", text="same title")
        assert answer.status_code == 409
    assert git(world.remote, "rev-parse", "main").stdout == remote_before
    assert git(world.vault, "status", "--porcelain").stdout == ""


@pytest.mark.parametrize("abort_fails", [False, True])
def test_abort_failure_never_resets_the_remote_commit(client, world, service, monkeypatch, abort_fails):
    collision = "Inbox/2026-10-24 1805 same title App words.md"
    (world.laptop / collision).write_text("---\ntype: inbox\nstatus: new\n---\nLaptop words.\n")
    git(world.laptop, "add", "-A")
    git(world.laptop, "commit", "-qm", "A competing quick note")
    git(world.laptop, "push", "-q")
    remote_head = git(world.remote, "rev-parse", "main").stdout.strip()
    original = service.repo.git

    def no_abort(*args, **kwargs):
        if abort_fails and args[:2] == ("rebase", "--abort"):
            if kwargs.get("check", True):
                raise GitError("injected failed abort")
            return subprocess.CompletedProcess(args, 1, "", "injected failed abort")
        return original(*args, **kwargs)

    monkeypatch.setattr(service.repo, "git", no_abort)
    answer = edit(TestClient(client.app, raise_server_exceptions=False),
                  op="quick_note", text="same title\n\nApp words.")
    assert service.repo.head() == remote_head
    if not abort_fails:
        assert answer.status_code == 409
        assert git(world.vault, "status", "--porcelain").stdout == ""
        assert "Laptop words." in (world.vault / collision).read_text()
        return
    assert answer.status_code == 200 and answer.json()["pushed"] is False
    assert service.health()["ok"] is False
    kept = git(world.vault, "show", "refs/arestoteles/rebase-original:" + collision).stdout
    assert "App words." in kept


def test_detached_head_is_never_pushed_to_main(world):
    git(world.vault, "checkout", "--detach", "-q")
    before = git(world.remote, "rev-parse", "main").stdout
    service = world.service()
    answer = raw_edit(TestClient(create_app(service), raise_server_exceptions=False), op="quick_note", text="A thought")
    assert answer.status_code == 503
    assert service.health()["ok"] is False
    assert git(world.remote, "rev-parse", "main").stdout == before


def test_two_clients_editing_one_version_have_one_winner(client, world, service):
    source = service.source("Printing press")
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda words: raw_edit(client, op="reword_position", position="Printing press#2",
                                                      text=words, version=source["version"]),
                                ["First client words.", "Second client words."]))
    assert sorted(r.status_code for r in results) == [200, 409]
    winner = next(r for r in results if r.status_code == 200)
    assert winner.json()["vault"]["commit"] == service.repo.head(short=True)


def test_old_position_number_cannot_edit_its_successor(client, service):
    old = service.source("Printing press")["version"]
    assert edit(client, op="drop_position", position="Printing press#1", why="A test.").status_code == 200
    answer = raw_edit(client, op="reword_position", position="Printing press#1", text="Stale wording.", version=old)
    assert answer.status_code == 409
    assert "Stale wording." not in service.source("Printing press")["markdown"]


def test_rebase_does_not_drop_a_patch_that_the_laptop_later_reverted(client, world, service):
    reject = hook(world, "pre-push", "exit 1")
    assert edit(client, op="confirm_position", position="Printing press#2").json()["pushed"] is False
    app_bytes = (world.vault / PRESS).read_bytes()
    (world.laptop / PRESS).write_bytes(app_bytes)
    git(world.laptop, "commit", "-qam", "The same confirmation on the laptop")
    git(world.laptop, "revert", "--no-edit", "HEAD")
    git(world.laptop, "push", "-q")
    reject.unlink()
    service.sync()
    assert "*(draft)*" not in world.remote_file(PRESS)
    assert service.health()["pushed"] is True


def test_symlink_note_is_not_replaced_or_written_through(world):
    outside = world.tmp / "outside.md"
    original = "---\ntype: inbox\nstatus: new\n---\nAn outside file.\n"
    outside.write_text(original)
    link = world.vault / "Inbox/Linked.md"
    link.symlink_to(outside)
    git(world.vault, "add", "-A")
    git(world.vault, "commit", "-qm", "A note symlink")
    client = TestClient(create_app(world.service(push=False)))
    answer = edit(client, op="set_inbox_status", note="Linked", status="processed")
    assert answer.status_code == 422
    assert link.is_symlink()
    assert outside.read_text() == original


def test_two_different_paths_with_the_same_name_cannot_be_edited(world):
    a = world.vault / "Inbox/Duplicate.md"
    b = world.vault / "Library/Actors/Duplicate.md"
    raw = "---\ntype: inbox\nstatus: new\n---\nOriginal.\n"
    for file in (a, b):
        file.write_text(raw)
    git(world.vault, "add", "-A")
    git(world.vault, "commit", "-qm", "An existing duplicate")
    client = TestClient(create_app(world.service(push=False)))
    answer = edit(client, op="set_inbox_status", note="Duplicate", status="processed")
    assert answer.status_code == 409
    assert a.read_text() == b.read_text() == raw


@pytest.mark.parametrize("pending", [False, True])
def test_a_discuss_mark_cannot_silently_follow_a_different_position(client, world, service, pending):
    # The app still displays position 1, while Obsidian replaces that view. There is no overlapping file edit:
    # the phone writes an Inbox file, the laptop changes the topic, so a plain rebase silently accepts it.
    if pending:
        reject = hook(world, "pre-push", "exit 1")
        answer = edit(client, op="quick_note", text="Discuss this view.", about="Printing press#1")
        assert answer.status_code == 200 and answer.json()["pushed"] is False
        reject.unlink()
    world.laptop_commit(PRESS, lambda t: t.replace("Print did not cause", "A different view: print caused"))
    remote_before = git(world.remote, "rev-parse", "main").stdout
    if pending:
        service = world.service()  # dependency information must survive a restart
        service.sync()
        assert service.health()["ok"] is False
    else:
        answer = edit(client, op="quick_note", text="Discuss this view.", about="Printing press#1")
        assert answer.status_code == 409
    assert git(world.remote, "rev-parse", "main").stdout == remote_before


@pytest.mark.parametrize("op", ["reword_position", "change_position", "drop_position"])
def test_structured_edits_do_not_discard_position_continuations(world, op):
    file = world.vault / PRESS
    file.write_text(file.read_text().replace("\n2. **Printers", "\n   An extra qualification from Obsidian.\n2. **Printers"))
    git(world.vault, "commit", "-qam", "A multiline position")
    client = TestClient(create_app(world.service(push=False)))
    before = file.read_bytes()
    body = {"op": op, "position": "Printing press#1"}
    if op != "drop_position":
        body["text"] = "New words."
    if op != "reword_position":
        body["why"] = "A test."
    answer = edit(client, **body)
    assert file.read_bytes() == before
    assert answer.status_code == 422


def test_a_check_that_breaks_only_after_the_edit_does_not_approve_it(client, world):
    script = world.vault / ".tools/check.rb"
    script.write_text(script.read_text() + '\nraise "unexpected content" if Dir.glob("Inbox/*.md").any? { |p| File.read(p).include?("trigger checker failure") }\n')
    # The fixture exits explicitly; put the injected failure before that exit.
    script.write_text(script.read_text().replace("exit(errors.empty? ? 0 : 1)\n", "") + "\nexit(errors.empty? ? 0 : 1)\n")
    git(world.vault, "commit", "-qam", "A checker that crashes on particular input")
    before = git(world.vault, "rev-parse", "HEAD").stdout
    answer = edit(client, op="quick_note", text="trigger checker failure")
    assert answer.status_code == 503
    assert git(world.vault, "rev-parse", "HEAD").stdout == before
    assert git(world.vault, "status", "--porcelain").stdout == ""


@pytest.mark.parametrize("rename", [False, True])
def test_a_move_or_rename_does_not_resurrect_the_old_path(client, world, service, rename):
    new = "Inbox/Renamed press.md" if rename else "Topics/Printing press/Moved/Printing press.md"
    (world.laptop / new).parent.mkdir(parents=True, exist_ok=True)
    git(world.laptop, "mv", PRESS, new)
    git(world.laptop, "commit", "-qm", "Move a note on the laptop")
    git(world.laptop, "push", "-q")
    answer = edit(client, op="confirm_position", position="Printing press#2")
    assert answer.status_code == 409
    assert not (world.vault / PRESS).exists()
    assert (world.vault / new).exists()
    new_id = "Renamed press" if rename else "Printing press"
    source = service.source(new_id)
    answer = raw_edit(client, op="edit_note", note=new_id, version=source["version"],
                      markdown=source["markdown"] + "\nAn addition at the new path.\n")
    assert answer.status_code == 200
    assert "An addition at the new path." in world.remote_file(new)
    assert not (world.vault / PRESS).exists()


def test_a_second_push_race_keeps_all_edits_for_the_next_sync(client, world, service, monkeypatch):
    reject = hook(world, "pre-push", "exit 1")
    assert edit(client, op="quick_note", text="First app note.").json()["pushed"] is False
    reject.unlink()
    world.laptop_commit("Glossary.md", lambda t: t + "\nFirst laptop addition.\n")
    push, calls = service.repo.push, 0

    def racing_push():
        nonlocal calls
        calls += 1
        if calls == 2:
            world.laptop_commit("Glossary.md", lambda t: t + "\nSecond laptop addition.\n")
        return push()

    monkeypatch.setattr(service.repo, "push", racing_push)
    result = edit(client, op="quick_note", text="Second app note.")
    assert result.status_code == 200 and result.json()["pushed"] is False
    restarted = world.service()
    restarted.sync()
    assert restarted.health()["pushed"] is True
    assert "First app note." in world.remote_file("Inbox/2026-10-24 1805 First app note.md")
    assert "Second app note." in world.remote_file("Inbox/2026-10-24 1805 Second app note.md")
    assert "Second laptop addition." in world.remote_file("Glossary.md")


def test_large_note_is_saved_whole_or_rejected_whole(client, world, service):
    source = service.source("Printing press")
    body = source["markdown"] + "\n" + ("A made-up long paragraph. " * 3600) + "\n"
    answer = raw_edit(client, op="edit_note", note="Printing press", version=source["version"], markdown=body)
    assert answer.status_code == 200
    assert service.source("Printing press")["markdown"] == body
    before = (world.vault / PRESS).read_bytes()
    answer = raw_edit(client, op="edit_note", note="Printing press", version=service.source("Printing press")["version"],
                      markdown=body * 2)
    assert answer.status_code == 413
    assert (world.vault / PRESS).read_bytes() == before


@pytest.mark.parametrize("require_versions", [False, True])
@pytest.mark.parametrize("body", [
    {"op": "confirm_position", "position": "Printing press#2"},
    {"op": "reword_position", "position": "Printing press#2", "text": "A view."},
    {"op": "change_position", "position": "Printing press#2", "text": "A view.", "why": "A test."},
    {"op": "drop_position", "position": "Printing press#2", "why": "A test."},
    {"op": "add_position", "note": "Printing press", "text": "A view."},
    {"op": "set_confidence", "note": "Printing press", "confidence": "solid"},
    {"op": "set_inbox_status", "note": "2026-10-23 2110 discuss Printing press", "status": "processed"},
    {"op": "quick_note", "text": "A question.", "about": "Printing press#1"},
    {"op": "quick_note", "text": "A question.", "about": "Printing press"},
])
def test_structured_versions_in_both_modes(world, require_versions, body, caplog):
    service = world.service(require_versions=require_versions)
    client = TestClient(create_app(service))
    before = service.repo.head()
    assert raw_edit(client, **body, version="0" * 40).status_code == 409
    assert service.repo.head() == before
    assert not caplog.records
    answer = raw_edit(client, **body)
    if require_versions:
        assert answer.status_code == 428
        assert service.repo.head() == before
        assert not caplog.records
        assert edit(client, **body).status_code == 200   # the displayed current version is accepted
    else:
        assert answer.status_code == 200
        assert service.repo.head() != before
        assert [r.getMessage() for r in caplog.records] == [
            f"unversioned {body['op']} edit allowed (ARESTOTELES_REQUIRE_VERSIONS=0)"]


def test_rebase_dependencies_match_git_nfc_and_filesystem_nfd_names(world):
    name = unicodedata.normalize("NFD", "Bücher")
    path = f"Inbox/{name}.md"
    git(world.vault, "config", "core.precomposeunicode", "true")
    (world.vault / path).write_text("---\ntype: inbox\nstatus: new\n---\nThe original thought.\n")
    git(world.vault, "add", "-A")
    git(world.vault, "commit", "-qm", "A decomposed name")
    git(world.vault, "push", "-q")
    service = world.service()
    client = TestClient(create_app(service))
    world.laptop_commit(path, lambda t: t.replace("original", "changed"))
    answer = edit(client, op="quick_note", text="A question about the old thought.", about="Bücher")
    assert answer.status_code == 409


def test_a_long_existing_filename_can_still_be_replaced_atomically(world):
    name = "x" * 240
    path = world.vault / f"Inbox/{name}.md"
    path.write_text("---\ntype: inbox\nstatus: new\n---\nA thought.\n")
    git(world.vault, "add", "-A")
    git(world.vault, "commit", "-qm", "A long existing filename")
    client = TestClient(create_app(world.service(push=False)))
    answer = edit(client, op="set_inbox_status", note=name, status="processed")
    assert answer.status_code == 200
    assert "status: processed" in path.read_text()


def test_a_process_killed_before_rebase_validation_cannot_publish_unchecked_work(client, world, service):
    reject = hook(world, "pre-push", "exit 1")
    assert edit(client, op="quick_note", text="Keep this pending note.").json()["pushed"] is False
    reject.unlink()
    original = service.repo.head()
    world.laptop_commit("Glossary.md", lambda t: t + "\nA concurrent laptop addition.\n")
    remote = git(world.remote, "rev-parse", "main").stdout
    code = '''
import os, signal, sys
from pathlib import Path
from arestoteles.service import VaultService
from arestoteles.config import Settings
from arestoteles import check
root = Path(sys.argv[1])
service = VaultService(Settings(vault=root, search_model="off"), None)
service.rebuild()
run = check.run
def die_before_validation(path, *args):
    if path == root:
        os.kill(os.getpid(), signal.SIGKILL)
    return run(path, *args)
check.run = die_before_validation
service.sync()
'''
    done = subprocess.run([sys.executable, "-c", code, str(world.vault)], capture_output=True)
    assert done.returncode == -9, done.stderr.decode()
    assert git(world.remote, "rev-parse", "main").stdout == remote
    restarted = world.service()
    assert restarted.repo.head() == original
    restarted.sync()
    assert restarted.health()["pushed"] is True
    assert "Keep this pending note." in world.remote_file("Inbox/2026-10-24 1805 Keep this pending note.md")


def test_nfc_inbox_links_follow_a_position_drop_in_an_nfd_note(world):
    name = unicodedata.normalize("NFD", "Bücher")
    path = world.vault / f"Topics/{name}/{name}.md"
    path.parent.mkdir()
    path.write_bytes((world.vault / PRESS).read_bytes())
    mark = world.vault / "Inbox/A mark with a composed link.md"
    mark.write_text('---\ntype: inbox\nstatus: new\nabout: "[[Bücher#My position]]"\nposition: 2\n---\nA question.\n')
    git(world.vault, "add", "-A")
    git(world.vault, "commit", "-qm", "Decomposed filename and composed link")
    client = TestClient(create_app(world.service(push=False)))
    answer = edit(client, op="drop_position", position=f"{name}#1", why="A test.")
    assert answer.status_code == 200
    assert "\nposition: 1\n" in mark.read_text()


def test_quick_note_names_do_not_collide_across_unicode_normalizations(world):
    stem = "2026-10-24 1805 Bücher"
    path = world.vault / f"Inbox/{unicodedata.normalize('NFD', stem)}.md"
    original = "---\ntype: inbox\nstatus: new\n---\nKeep the earlier note.\n"
    path.write_text(original)
    git(world.vault, "add", "-A")
    git(world.vault, "commit", "-qm", "An existing decomposed name")
    client = TestClient(create_app(world.service(push=False)))
    answer = edit(client, op="quick_note", text="Bücher")
    assert path.read_text() == original
    assert answer.status_code == 200
    assert answer.json()["changed"] == [stem + " 2"]
