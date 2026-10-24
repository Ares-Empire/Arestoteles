"""`Block.lines`: where each block and list item sits in the note's source body, so the app can edit one paragraph or
one list item and send the whole body back with `edit_note` (made-up notes only)."""

from __future__ import annotations

from collections import Counter

from arestoteles.inline import Resolver
from arestoteles.reader import read

from conftest import APP, edit, note
from linecheck import check_note, problems, replace_lines

SPREAD = "Topics/Printing press/Spread of print.md"


def source(client, note_id: str) -> dict:
    return client.get(f"/api/arestoteles/notes/{note_id}/source", headers=APP).json()


def test_every_fixture_block_round_trips(service, client):
    built = service.current()
    resolve = Resolver(built.paths)
    counts: Counter = Counter()
    for n in built.vault["notes"]:
        counts += check_note(n, source(client, n["id"])["markdown"], resolve)
    assert problems(counts) == {}
    assert (counts["blocks"], counts["items"]) == (47, 12)


def test_tricky_bodies_round_trip():
    """Loose lists, nested items with a paragraph after them, setext headings, embeds inside a paragraph, a
    Windows file and blank lines everywhere."""
    body = ("\n\n# T\n\n- a\n  - b\n\n  more of a\n- c\n\n\n1. one\n\n2. two\n\n\nSetext\n===\n\nText before\n"
            "![[Other]]\n→ [[Other]], [[T]]\ntext after\n\n> [!claude] t\n> x\nlazy\n\n    code\n\n"
            "| a |\n|---|\n| 1 |\n")
    ids = ["T", "Other"]
    file = f"---\ntype: mechanism\n---\n{body}"
    for raw in (file.encode(), file.replace("\n", "\r\n").encode()):
        n = read("Library/Mechanisms/T.md", raw, Resolver(ids)).note
        counts = check_note(n, body, Resolver(ids))
        assert problems(counts) == {}
        assert (counts["blocks"], counts["items"]) == (11, 5)
    n = read("Library/Mechanisms/T.md", f"---\ntype: mechanism\n---\n{body}".encode(), Resolver(ids)).note
    lists = [b for b in n["blocks"] if b["kind"] == "list"]
    assert [b["lines"] for b in lists] == [[4, 9], [11, 14]]                  # without the blank lines after them
    assert [i["lines"] for i in lists[0]["items"]] == [[4, 5], [5, 8], [8, 9]]   # "more of a" reads as b's text
    assert lists[0]["items"][1]["text"] == "b\nmore of a"
    assert [i["lines"] for i in lists[1]["items"]] == [[11, 12], [13, 14]]
    assert [(b["kind"], b["lines"]) for b in n["blocks"][3:8]] == [
        ("paragraph", [19, 20]), ("embed", [20, 21]), ("section_link", [21, 22]), ("section_link", [21, 22]),
        ("paragraph", [22, 23])]


def test_a_lone_carriage_return_gives_no_lines():
    """markdown-it breaks lines at a lone "\\r" and str.split("\\n") does not: then the server gives no ranges."""
    n = read("Library/Mechanisms/T.md", b"---\ntype: mechanism\n---\n# T\n\nOne\rtwo\n\n- a\n", Resolver(["T"])).note
    assert [b["lines"] for b in n["blocks"]] == [None, None]
    assert n["blocks"][1]["items"][0]["lines"] is None


def test_edit_one_paragraph_with_its_lines(client, world):
    """The app's flow: the block's lines in the source, replaced, the whole body sent with the source's version."""
    vault = client.get("/api/arestoteles/vault", headers=APP).json()
    blocks = note(vault, "Spread of print")["blocks"]
    paragraph = next(b for b in blocks if b["kind"] == "paragraph" and b["text"].startswith("Printers went"))
    current = source(client, "Spread of print")
    assert current["version"] == note(vault, "Spread of print")["version"]   # the lines belong to this version
    markdown = replace_lines(current["markdown"], paragraph["lines"], "Printers went where the money was.")
    answer = edit(client, op="edit_note", note="Spread of print", version=current["version"], markdown=markdown)
    assert answer.status_code == 200
    after = note(answer.json()["vault"], "Spread of print")["blocks"]
    assert [b["kind"] for b in after] == [b["kind"] for b in blocks]
    changed = [i for i, (old, new) in enumerate(zip(blocks, after)) if old != new]
    assert changed == [blocks.index(paragraph)]
    assert after[changed[0]] == {"kind": "paragraph", "text": "Printers went where the money was.",
                                 "lines": paragraph["lines"]}
    text = (world.vault / SPREAD).read_text(encoding="utf-8")
    assert "## Trade routes, not borders\nPrinters went where the money was.\n\n> [!shaky]" in text


def test_edit_one_list_item_with_its_lines(client, world):
    vault = client.get("/api/arestoteles/vault", headers=APP).json()
    sources = note(vault, "Printing press")["blocks"][-1]
    assert sources["kind"] == "list" and len(sources["items"]) == 2
    current = source(client, "Printing press")
    item = sources["items"][1]
    markdown = replace_lines(current["markdown"], item["lines"], "- Andrew Pettegree, *Brand Luther*, 2015, ch. 3\n"
                                                                 "- Elizabeth Eisenstein, 1979")
    answer = edit(client, op="edit_note", note="Printing press", version=current["version"], markdown=markdown)
    assert answer.status_code == 200
    after = note(answer.json()["vault"], "Printing press")["blocks"][-1]
    assert [i["text"] for i in after["items"]] == [
        sources["items"][0]["text"], "Andrew Pettegree, *Brand Luther*, 2015, ch. 3", "Elizabeth Eisenstein, 1979"]
    assert after["items"][0] == sources["items"][0]
    stale = edit(client, op="edit_note", note="Printing press", version=current["version"], markdown=markdown)
    assert stale.status_code == 409   # lines of an old version are never applied to a newer file
