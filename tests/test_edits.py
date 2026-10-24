"""Every edit of the contract against the made-up vault in a real git repo with a temporary "GitHub" remote."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from arestoteles.api import create_app

from conftest import APP, git, note, position, edit

PRESS = "Topics/Printing press/Printing press.md"
SPREAD = "Topics/Printing press/Spread of print.md"
APP_AUTHOR = "Patrik Breeck (Arestoteles app) <287037715+carlsenares@users.noreply.github.com>"


def file(world, path: str) -> str:
    return (world.vault / path).read_text(encoding="utf-8")


def last_commit(world) -> str:
    return git(world.vault, "log", "-1", "--format=%an <%ae>|%s").stdout.strip()


def commits(world) -> int:
    return int(git(world.vault, "rev-list", "--count", "HEAD").stdout)


def section(text: str, title: str) -> list[str]:
    lines = text.split("\n")
    start = lines.index(f"## {title}") + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    return [line for line in lines[start:end] if line.strip()]


def source(client, note_id: str) -> dict:
    return client.get(f"/api/arestoteles/notes/{note_id}/source", headers=APP).json()


# ── positions ──
def test_confirm_position(client, world):
    answer = edit(client, op="confirm_position", position="Printing press#2")
    assert answer.status_code == 200
    body = answer.json()
    assert (body["changed"], body["pushed"], body["warnings"]) == (["Printing press"], True, [])
    assert section(file(world, PRESS), "My position")[1] == (
        "2. **Printers were businessmen first; they printed what sold.** → [[Information wants to be cheap]]")
    assert "updated: 2026-10-24" in file(world, PRESS)
    assert position(body["vault"], "Printing press#2")["draft"] is False
    assert last_commit(world) == f"{APP_AUTHOR}|App: confirm position 2 (Printing press)"
    assert world.remote_log(1) == [f"{APP_AUTHOR}|App: confirm position 2 (Printing press)"]
    assert body["vault"]["commit"] == git(world.vault, "rev-parse", "--short", "HEAD").stdout.strip()


def test_confirm_twice_changes_nothing(client, world):
    edit(client, op="confirm_position", position="Printing press#2")
    count = commits(world)
    again = edit(client, op="confirm_position", position="Printing press#1")
    assert again.status_code == 200
    assert again.json()["changed"] == []
    assert commits(world) == count


def test_reword_position(client, world):
    answer = edit(client, op="reword_position", position="Printing press#1",
                  text="  Print did not start the Reformation, but it made it unstoppable.  ")
    assert answer.status_code == 200
    lines = section(file(world, PRESS), "My position")
    assert lines[0] == ("1. **Print did not start the Reformation, but it made it unstoppable.** → "
                        "[[Did print cause the Reformation]], [[Reformation]]")
    assert len(section(file(world, PRESS), "How my view changed")) == 1   # same view: no history
    p = position(answer.json()["vault"], "Printing press#1")
    assert p["text"] == "Print did not start the Reformation, but it made it unstoppable."
    assert p["evidence"] == ["Did print cause the Reformation", "Reformation"]
    assert last_commit(world).endswith("|App: reword position 1 (Printing press)")


def test_reword_of_a_draft_makes_it_patriks_words(client, world):
    answer = edit(client, op="reword_position", position="Printing press#2", text="Printers printed what sold.")
    assert position(answer.json()["vault"], "Printing press#2")["draft"] is False


def test_change_position_keeps_the_old_view(client, world):
    answer = edit(client, op="change_position", position="Printing press#2",
                  text="Printers printed what sold, whatever it was.", why="The sources say so.")
    assert answer.status_code == 200
    text = file(world, PRESS)
    assert section(text, "My position")[1] == (
        "2. **Printers printed what sold, whatever it was.** → [[Information wants to be cheap]]")
    assert section(text, "How my view changed") == [
        "- **2026-10-24, position 2:** I thought: Printers were businessmen first; they printed what sold. "
        "What changed it: The sources say so.",
        "- **2026-10-20, position 1:** I thought: Print caused the Reformation. What changed it: Earlier reformers "
        "failed without a press, but the press alone convinced nobody."]
    vault = answer.json()["vault"]
    assert position(vault, "Printing press#2")["history"] == [
        {"date": "2026-10-24", "text": "Printers were businessmen first; they printed what sold.",
         "why": "The sources say so."}]
    assert len(position(vault, "Printing press#1")["history"]) == 1
    assert last_commit(world).endswith("|App: change position 2 (Printing press)")


def test_change_creates_the_history_section_before_sources(client, world):
    answer = edit(client, op="change_position", position="Positions#1", text="Who controls copying wins.",
                  why="Too broad")
    assert answer.status_code == 200
    text = file(world, "Positions.md")
    assert text.endswith("![[Printing press#My position]]\n\n## How my view changed\n"
                         "- **2026-10-24, position 1:** I thought: Who controls the copies controls the argument. "
                         "What changed it: Too broad\n")
    p = position(answer.json()["vault"], "Positions#1")
    assert p["history"][0]["text"] == "Who controls the copies controls the argument."


def test_drop_position_renumbers(client, world):
    edit(client, op="change_position", position="Printing press#2", text="Printers printed what sold.", why="X.")
    answer = edit(client, op="drop_position", position="Printing press#1", why="No longer sure.")
    assert answer.status_code == 200
    text = file(world, PRESS)
    assert section(text, "My position") == ["1. **Printers printed what sold.** → [[Information wants to be cheap]]"]
    assert section(text, "How my view changed") == [
        "- **2026-10-24:** I thought: Print did not cause the Reformation, but it made it impossible to stop. "
        "What changed it: No longer sure.",
        "- **2026-10-24, position 1:** I thought: Printers were businessmen first; they printed what sold. "
        "What changed it: X.",
        "- **2026-10-20:** I thought: Print caused the Reformation. What changed it: Earlier reformers failed "
        "without a press, but the press alone convinced nobody."]
    vault = answer.json()["vault"]
    assert note(vault, "Printing press")["positions"] == ["Printing press#1"]
    assert position(vault, "Printing press#1")["history"][0]["why"] == "X."
    assert "![[Printing press#My position]]" in file(world, "Positions.md")   # the embed stays
    gone = edit(client, op="confirm_position", position="Printing press#2")
    assert gone.status_code == 409
    assert gone.json()["error"] == "This position no longer exists; it was changed elsewhere."
    assert gone.json()["current"]["id"] == "Printing press"


def test_add_position(client, world):
    answer = edit(client, op="add_position", note="Printing press", text="Paper mattered as much as the press.",
                  evidence=["Gutenberg Bible", "Spread of print"])
    assert answer.status_code == 200
    assert section(file(world, PRESS), "My position")[2] == (
        "3. **Paper mattered as much as the press.** → [[Gutenberg Bible]], [[Spread of print]]")
    p = position(answer.json()["vault"], "Printing press#3")
    assert (p["text"], p["draft"], p["evidence"]) == (
        "Paper mattered as much as the press.", False, ["Gutenberg Bible", "Spread of print"])
    across = edit(client, op="add_position", note="Positions", text="Copies beat arguments.", evidence=[])
    assert section(file(world, "Positions.md"), "Across topics")[1] == "2. **Copies beat arguments.**"
    assert across.json()["vault"]["positions"][0]["positions"][1]["id"] == "Positions#2"
    assert last_commit(world).endswith("|App: add position 2 (Positions)")


def test_add_position_creates_the_section_and_the_embed(client, world, service):
    (world.laptop / "Topics" / "Paper").mkdir()
    (world.laptop / "Topics" / "Paper" / "Paper.md").write_text(
        "---\ntype: topic\nconfidence: shaky\ncreated: 2026-10-01\nupdated: 2026-10-01\n---\n# Paper\n\n"
        "> [!summary]\n> Paper came from far away.\n\n## 1. Mills\nMills spread north.\n", encoding="utf-8")
    git(world.laptop, "add", "-A")
    git(world.laptop, "commit", "-qm", "A new topic")
    git(world.laptop, "push", "-q")
    service.sync()
    answer = edit(client, op="add_position", note="Paper", text="Paper was the bottleneck.", evidence=["Gutenberg Bible"])
    assert answer.status_code == 200
    assert answer.json()["changed"] == ["Paper", "Positions"]
    assert file(world, "Topics/Paper/Paper.md").split("---\n", 2)[2] == (
        "# Paper\n\n> [!summary]\n> Paper came from far away.\n\n## My position\n"
        "1. **Paper was the bottleneck.** → [[Gutenberg Bible]]\n\n## 1. Mills\nMills spread north.\n")
    assert file(world, "Positions.md").endswith("### Printing press\n![[Printing press#My position]]\n\n"
                                                "### Paper\n![[Paper#My position]]\n")
    groups = answer.json()["vault"]["positions"]
    assert [g["note"] for g in groups] == ["Positions", "Printing press", "Paper"]


@pytest.mark.parametrize("body,status,error", [
    ({"op": "add_position", "note": "Spread of print", "text": "X.", "evidence": []}, 422,
     "Positions can only be added to a topic overview or to Positions."),
    ({"op": "add_position", "note": "Printing press", "text": "X.", "evidence": ["Nowhere"]}, 422,
     "The evidence names a note that does not exist: Nowhere."),
    ({"op": "add_position", "note": "Nowhere", "text": "X.", "evidence": []}, 404, "Unknown note."),
    ({"op": "reword_position", "position": "Printing press#1", "text": "  "}, 422, "The text is empty."),
    ({"op": "reword_position", "position": "Printing press#1", "text": "Two\nlines"}, 422,
     "A position is one line, without line breaks, → or **."),
    ({"op": "reword_position", "position": "Printing press#1", "text": "A → B"}, 422,
     "A position is one line, without line breaks, → or **."),
    ({"op": "change_position", "position": "Printing press#1", "text": "New.", "why": " "}, 422,
     "Say what changed your view."),
    ({"op": "confirm_position", "position": "Printing press#9"}, 409,
     "This position no longer exists; it was changed elsewhere."),
    ({"op": "confirm_position", "position": "Nowhere#1"}, 404, "Unknown position."),
    ({"op": "confirm_position", "position": "Printing press"}, 404, "Unknown position."),
    ({"op": "confirm_position", "position": "Gutenberg Bible#1"}, 404, "Unknown position."),
    ({"op": "set_confidence", "note": "Martin Luther", "confidence": "solid"}, 422,
     "This kind of note has no confidence."),
    ({"op": "set_confidence", "note": "Printing press", "confidence": "certain"}, 400, "Bad request."),
    ({"op": "quick_note", "text": " \n "}, 422, "The text is empty."),
    ({"op": "explode"}, 400, "Bad request."),
    ({"op": "quick_note", "text": "x", "extra": 1}, 400, "Bad request."),
])
def test_edits_that_cannot_apply(client, world, body, status, error):
    count = commits(world)
    answer = client.post("/api/arestoteles/edits", json=body, headers=APP)
    assert answer.status_code == status
    assert answer.json()["error"] == error
    assert commits(world) == count
    assert git(world.vault, "status", "--porcelain").stdout == ""


# ── notes ──
def test_set_confidence(client, world):
    answer = edit(client, op="set_confidence", note="Printing press", confidence="solid")
    assert answer.status_code == 200
    assert "confidence: solid\n" in file(world, PRESS)
    assert note(answer.json()["vault"], "Printing press")["confidence"] == "solid"
    assert last_commit(world).endswith("|App: set confidence solid (Printing press)")


def test_adopt_callout(client, world):
    version = note(client.get("/api/arestoteles/vault", headers=APP).json(), "Printing press")["version"]
    answer = edit(client, op="adopt_callout", note="Printing press", callout=0, version=version)
    assert answer.status_code == 200
    text = file(world, PRESS)
    assert "[!claude]" not in text
    assert ("[[Did print cause the Reformation]].\n\nElizabeth Eisenstein (*The Printing Press as an Agent of Change*, "
            "1979) gives the press the leading role; Andrew Pettegree argues that pamphlets mattered more than books."
            "\n\n## How my view changed") in text
    n = note(answer.json()["vault"], "Printing press")
    assert n["callouts"] == [] and n["brief"]["counterpoints"] == []
    assert last_commit(world).endswith("|App: adopt callout 1 (Printing press)")


def test_dismiss_callout(client, world):
    version = source(client, "Spread of print")["version"]
    answer = edit(client, op="dismiss_callout", note="Spread of print", callout=0, version=version)
    assert answer.status_code == 200
    text = file(world, SPREAD)
    assert "[!shaky]" not in text and "\n\n\n" not in text
    assert "northern Italy.\n\n| City | First press |" in text
    assert note(answer.json()["vault"], "Printing press")["brief"]["shaky"] == []


def test_callout_edits_check_the_version(client, world):
    stale = edit(client, op="dismiss_callout", note="Printing press", callout=0, version="0" * 40)
    assert stale.status_code == 409
    assert stale.json()["error"] == "This note was changed elsewhere; here is the current version."
    assert stale.json()["current"]["id"] == "Printing press"
    version = stale.json()["current"]["version"]
    missing = edit(client, op="dismiss_callout", note="Printing press", callout=3, version=version)
    assert (missing.status_code, missing.json()["error"]) == (404, "Unknown callout.")


def test_edit_note(client, world):
    current = source(client, "Spread of print")
    markdown = current["markdown"].replace("Lyon | 1473 |", "Lyon | 1473 |\n| Basel | 1468 |")
    answer = edit(client, op="edit_note", note="Spread of print", version=current["version"], markdown=markdown)
    assert answer.status_code == 200
    assert file(world, SPREAD) == ("---\ntype: topic\nconfidence: solid\ncreated: 2026-10-01\nupdated: 2026-10-24\n"
                                   "tags: []\n---\n" + markdown)
    assert source(client, "Spread of print")["markdown"] == markdown
    table = [b for b in note(answer.json()["vault"], "Spread of print")["blocks"] if b["kind"] == "table"][0]
    assert table["rows"][-1] == ["Basel", "1468"]
    assert last_commit(world).endswith("|App: edit (Spread of print)")
    stale = edit(client, op="edit_note", note="Spread of print", version=current["version"], markdown="# x\n")
    assert stale.status_code == 409


@pytest.mark.parametrize("language,prefix", [
    ("en", "The vault check found errors, so the edit was undone: "),
    ("de", "Die Prüfung hat Fehler gefunden, deshalb wurde die Änderung rückgängig gemacht: ")])
def test_check_error_undoes_the_edit(client, world, language, prefix):
    before = file(world, SPREAD)
    count = commits(world)
    current = source(client, "Spread of print")
    answer = edit(client, language, op="edit_note", note="Spread of print", version=current["version"],
                  markdown="# Spread of print\n\nNo summary box any more.\n")
    assert answer.status_code == 422
    assert answer.json()["error"] == prefix + (
        "Topics/Printing press/Spread of print.md: topic page must open with a > [!summary] box")
    assert file(world, SPREAD) == before
    assert commits(world) == count
    assert git(world.vault, "status", "--porcelain").stdout == ""


def test_warnings_are_the_new_ones(client, world, service):
    world.laptop_commit("Library/Actors/Martin Luther.md", lambda t: t + "\nSee also [[Johann Tetzel]].\n")
    service.sync()
    current = source(client, "Spread of print")
    answer = edit(client, op="edit_note", note="Spread of print", version=current["version"],
                  markdown=current["markdown"] + "\nPaper came from [[Paper mills]].\n")
    assert answer.status_code == 200
    assert answer.json()["warnings"] == ["Topics/Printing press/Spread of print.md: links unwritten note 'Paper mills'"]


@pytest.mark.parametrize("language,warning", [
    ("en", "The vault check did not run: Ruby is not installed on the server."),
    ("de", "Die Prüfung lief nicht: Auf dem Server ist Ruby nicht installiert.")])
def test_without_ruby_the_check_is_skipped(world, language, warning):
    client = TestClient(create_app(world.service(ruby="/nonexistent/ruby")))
    answer = edit(client, language, op="confirm_position", position="Printing press#2")
    assert answer.status_code == 200
    assert answer.json()["warnings"] == [warning]


def test_without_a_check_script_the_check_is_skipped(world):
    (world.vault / ".tools" / "check.rb").unlink()
    client = TestClient(create_app(world.service()))
    answer = edit(client, op="confirm_position", position="Printing press#2")
    assert answer.json()["warnings"] == ["The vault check did not run: the vault has no .tools/check.rb."]


def test_quick_note(client, world):
    answer = edit(client, op="quick_note", text="paper mills: who owned them?? check\n\nsecond *line*")
    assert answer.status_code == 200
    name = "2026-10-24 1805 paper mills who owned"
    assert answer.json()["changed"] == [name]
    assert file(world, f"Inbox/{name}.md") == (
        "---\ntype: inbox\nstatus: new\ncreated: 2026-10-24\n---\npaper mills: who owned them?? check\n\nsecond *line*\n")
    n = note(answer.json()["vault"], name)
    assert (n["type"], n["path"], n["title"]) == ("inbox", f"Inbox/{name}.md", name)
    assert last_commit(world) == f"{APP_AUTHOR}|App: quick note ({name})"
    again = edit(client, op="quick_note", text="paper mills: who owned them?? check")
    assert again.json()["changed"] == [f"{name} 2"]
    odd = edit(client, op="quick_note", text="[[a]] / b#c ^d")
    assert odd.json()["changed"] == ["2026-10-24 1805 a bc d"]


# ── git: concurrent pushes, conflicts, GitHub unreachable ──
def test_rebase_over_a_concurrent_push(client, world):
    world.laptop_commit("Glossary.md", lambda t: t + "| copy | Abschrift | [[Spread of print]] |\n",
                        "Glossary: one more term")
    answer = edit(client, op="confirm_position", position="Printing press#2")
    assert answer.status_code == 200
    assert answer.json()["pushed"] is True
    assert world.remote_log(2) == [f"{APP_AUTHOR}|App: confirm position 2 (Printing press)",
                                   "Test Laptop <laptop@example.com>|Glossary: one more term"]
    assert "Abschrift" in world.remote_file("Glossary.md")
    assert [t["english"] for t in answer.json()["vault"]["glossary"]] == ["copy", "printing town", "trading city"]


@pytest.mark.parametrize("language,error", [
    ("en", "The note was changed elsewhere at the same time, so your edit was not saved."),
    ("de", "Die Notiz wurde gleichzeitig woanders geändert, deshalb wurde deine Änderung nicht gespeichert.")])
def test_a_real_conflict_undoes_the_edit(client, world, language, error):
    world.laptop_commit(PRESS, lambda t: t.replace("they printed what sold.** *(draft)*",
                                                   "they printed what sold, nothing more.** *(draft)*"))
    answer = edit(client, language, op="confirm_position", position="Printing press#2")
    assert answer.status_code == 409
    assert answer.json()["error"] == error
    current = answer.json()["current"]
    assert current["id"] == "Printing press"
    assert git(world.vault, "rev-parse", "HEAD").stdout == git(world.remote, "rev-parse", "main").stdout
    assert world.remote_log(1)[0].startswith("Test Laptop")
    vault = client.get("/api/arestoteles/vault", headers=APP).json()
    p = position(vault, "Printing press#2")
    assert (p["text"], p["draft"]) == ("Printers were businessmen first; they printed what sold, nothing more.", True)
    assert git(world.vault, "status", "--porcelain").stdout == ""


def test_push_failure_keeps_the_commit(client, world, service):
    away = world.remote.with_name("github-away.git")
    world.remote.rename(away)
    answer = edit(client, op="confirm_position", position="Printing press#2")
    assert answer.status_code == 200
    assert answer.json()["pushed"] is False
    assert last_commit(world).endswith("|App: confirm position 2 (Printing press)")
    health = client.get("/api/arestoteles/health").json()
    assert (health["ok"], health["pushed"]) == (True, False)
    world.clock.advance(minutes=11)
    service.sync()
    assert client.get("/api/arestoteles/health").json()["ok"] is False   # failing for more than 10 minutes
    away.rename(world.remote)
    service.sync()
    health = client.get("/api/arestoteles/health").json()
    assert (health["ok"], health["pushed"]) == (True, True)
    assert world.remote_log(1) == [f"{APP_AUTHOR}|App: confirm position 2 (Printing press)"]


def test_pushing_off_commits_locally(world):
    client = TestClient(create_app(world.service(push=False)))
    answer = edit(client, op="confirm_position", position="Printing press#2")
    assert answer.json()["pushed"] is False
    assert world.remote_log(1)[0].endswith("|A made-up vault")
