"""Frontmatter edits keep every other line; files keep their line endings; check output parsing."""

from __future__ import annotations

import subprocess

from arestoteles import check, notefile

from conftest import APP, edit


def test_blob_hash_is_gits():
    raw = "---\ntype: inbox\n---\nhello\n".encode()
    done = subprocess.run(["git", "hash-object", "--stdin"], input=raw, capture_output=True)
    assert notefile.blob_hash(raw) == done.stdout.decode().strip()


def test_set_field_replaces_or_inserts():
    text = "---\ntype: topic\ncreated: 2026-10-01\ntags: [a]\n---\n# T\n"
    assert notefile.set_field(text, "updated", "2026-10-24", after=("created",)) == (
        "---\ntype: topic\ncreated: 2026-10-01\nupdated: 2026-10-24\ntags: [a]\n---\n# T\n")
    assert notefile.set_field(text, "confidence", "shaky", after=("type",)) == (
        "---\ntype: topic\nconfidence: shaky\ncreated: 2026-10-01\ntags: [a]\n---\n# T\n")
    assert notefile.set_field(text, "tags", "[]") == "---\ntype: topic\ncreated: 2026-10-01\ntags: []\n---\n# T\n"
    listed = "---\ntype: event\nwhere:\n  - Europe\nfrom: 1\n---\n"
    assert notefile.set_field(listed, "where", "[Asia]") == "---\ntype: event\nwhere: [Asia]\nfrom: 1\n---\n"
    assert notefile.set_field("# no frontmatter\n", "updated", "x") == "# no frontmatter\n"
    assert notefile.set_field("---\ntype: home\n---\n", "updated", "x") == "---\ntype: home\nupdated: x\n---\n"


def test_windows_line_endings_survive_an_edit(world):
    from fastapi.testclient import TestClient

    from arestoteles.api import create_app
    from conftest import git

    path = world.laptop / "Topics" / "Printing press" / "Printing press.md"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    git(world.laptop, "commit", "-qam", "Windows line endings")
    git(world.laptop, "push", "-q")
    service = world.service()
    service.sync()
    client = TestClient(create_app(service))
    answer = edit(client, op="confirm_position", position="Printing press#2")
    assert answer.status_code == 200
    raw = (world.vault / "Topics" / "Printing press" / "Printing press.md").read_bytes()
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    assert b"*(draft)*" not in raw and b"updated: 2026-10-24\r\n" in raw
    assert client.get("/api/arestoteles/vault", headers=APP).status_code == 200


def test_check_output_parsing():
    out = ("3 notes checked (1 home)\nUnwritten (backlog): 1\n  - X  <- Home\nWarnings:\n  ! one warning\n"
           "  ! two warning\nERRORS:\n  x an error\n")
    assert check.parse(out) == (["an error"], ["one warning", "two warning"])
    assert check.parse("Warnings: none\nErrors: none\n") == ([], [])
    before = check.CheckResult(["e1"], ["w1", "w2"])
    after = check.CheckResult(["e1", "e2"], ["w2", "w3"])
    assert after.new_since(before) == check.CheckResult(["e2"], ["w3"])
    assert after.new_since(check.CheckResult(skipped="check_no_ruby")) == after


def test_a_crashing_check_is_reported_as_skipped(tmp_path):
    (tmp_path / ".tools").mkdir()
    (tmp_path / ".tools" / "check.rb").write_text("raise 'boom'\n")
    assert check.run(tmp_path).skipped == "check_broken"
    assert check.run(tmp_path, ruby="/nonexistent/ruby").skipped == "check_no_ruby"
    assert check.run(tmp_path / "nothing").skipped == "check_missing"
