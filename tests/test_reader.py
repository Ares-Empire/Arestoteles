"""Reading notes: Obsidian links into Text, and the Obsidian parts of a note body (made-up notes only)."""

from __future__ import annotations

import pytest

from arestoteles.inline import Resolver, find_links, plain, to_text
from arestoteles.reader import callout_spans, read

IDS = ["Printing press", "Luther's ninety-five theses", "Spread of print", "A_b (c)", "Did print cause it"]
resolve = Resolver(IDS)


def note(body: str, path: str = "Library/Mechanisms/Made up.md", ids=IDS, frontmatter: str = "type: mechanism"):
    raw = f"---\n{frontmatter}\n---\n{body}".encode()
    return read(path, raw, Resolver([*ids, path.rsplit("/", 1)[-1][:-3]]))


@pytest.mark.parametrize("source,expected", [
    ("[[Printing press]]", "[Printing press](arestoteles://note/Printing%20press)"),
    ("see [[Printing press|the press]].", "see [the press](arestoteles://note/Printing%20press)."),
    ("[[Printing press#My position]]",
     "[Printing press > My position](arestoteles://note/Printing%20press#My%20position)"),
    ("[[Luther's ninety-five theses]]",
     "[Luther's ninety-five theses](arestoteles://note/Luther%27s%20ninety-five%20theses)"),
    ("[[A_b (c)]]", "[A\\_b (c)](arestoteles://note/A_b%20%28c%29)"),
    ("[[printing press]]", "[printing press](arestoteles://note/Printing%20press)"),       # Obsidian ignores case
    ("[[Topics/Printing press/Printing press]]",
     "[Topics/Printing press/Printing press](arestoteles://note/Printing%20press)"),
    ("[[Not written yet]] stays", "Not written yet stays"),
    ("[[Not written|shown]]", "shown"),
    ("[[Note_with*stars]]", "Note\\_with\\*stars"),
    ("**bold** and *it* and [web](https://example.org/a_b)", "**bold** and *it* and [web](https://example.org/a_b)"),
    ("`code [[Printing press]]` and [[Printing press]]",
     "`code [[Printing press]]` and [Printing press](arestoteles://note/Printing%20press)"),
    ("[[Printing press\\|in a table]]", "[in a table](arestoteles://note/Printing%20press)"),
])
def test_text(source, expected):
    assert to_text(source, resolve) == expected


def test_heading_link_to_the_same_note():
    assert to_text("[[#Sources]]", resolve, self_id="Spread of print") == \
        "[Sources](arestoteles://note/Spread%20of%20print#Sources)"


def test_plain_and_links():
    assert plain("About [[Printing press|print]] and [[X#Y]]") == "About print and X > Y"
    links = find_links("![[Printing press#My position]] and [[A|B]]")
    assert [(wl.target, wl.anchor, wl.alias, wl.embed) for wl in links] == [
        ("Printing press", "My position", None, True), ("A", None, "B", False)]


def test_blocks_of_a_note():
    p = note("""# Made up

> [!summary]
> Line one
> line two.

Intro with a soft
break.

### Small heading
##### Tiny heading

1. first
   - nested
2. second

> [!claude] Suggested link
> Text of the callout.
>
> - a point
> - [[Printing press]]

> [!shaky]
> Probably wrong.

> [!info] Other
> Not Claude's.

> Just a quote.

---

![[Spread of print#Trade routes]]
![[Missing note]]
→ [[Spread of print]], [[Printing press]]
→ [[Not written]]

```
code line
```
""")
    n = p.note
    assert n["title"] == "Made up"
    assert n["summary"] == "Line one\nline two."
    kinds = [b["kind"] for b in n["blocks"]]
    assert kinds == ["paragraph", "heading", "heading", "list", "callout", "callout", "callout", "quote", "rule",
                     "embed", "paragraph", "section_link", "section_link", "paragraph", "paragraph"]
    assert n["blocks"][0]["text"] == "Intro with a soft\nbreak."
    assert [b["level"] for b in n["blocks"][1:3]] == [3, 4]
    assert n["blocks"][3] == {"kind": "list", "ordered": True, "items": [
        {"text": "first", "depth": 0}, {"text": "nested", "depth": 1}, {"text": "second", "depth": 0}]}
    assert n["blocks"][4] == {"kind": "callout", "style": "claude", "title": "Suggested link",
                              "text": "Text of the callout.\n\n• a point\n• [Printing press](arestoteles://note/"
                                      "Printing%20press)", "index": 0}
    assert n["blocks"][5]["title"] is None and n["blocks"][5]["index"] == 1
    assert n["blocks"][6] == {"kind": "callout", "style": "note", "title": "Other", "text": "Not Claude's.",
                              "index": -1}
    assert [c["style"] for c in n["callouts"]] == ["claude", "shaky"]
    assert n["blocks"][9] == {"kind": "embed", "note": "Spread of print", "anchor": "Trade routes"}
    assert n["blocks"][10] == {"kind": "paragraph", "text": "Missing note"}
    assert n["blocks"][13] == {"kind": "paragraph", "text": "→ Not written"}
    assert n["blocks"][14] == {"kind": "paragraph", "text": "`code line`"}
    assert p.unresolved == ["Missing note", "Not written"]


def test_positions_and_history():
    p = note("""# Topic

> [!summary]
> Short.

## My position
Intro line.
1. **First view.** → [[Printing press]], [[Not written]]
2. **Second view,** with more words. *(draft)* → [[Spread of print]]
3. **No links.** → section 2

## How my view changed
- **2026-10-20, position 1:** I thought: Old one. What changed it: A reason.
- **2026-10-22, position 1:** I thought: Older words
- **2026-10-21:** I thought: A dropped view. What changed it: Gone.
""", path="Topics/Topic/Topic.md", frontmatter="type: topic\nconfidence: solid")
    first, second, third = p.positions
    assert first == {"id": "Topic#1", "note": "Topic", "number": 1, "text": "First view.", "draft": False,
                     "evidence": ["Printing press"], "history": [
                         {"date": "2026-10-22", "text": "Older words", "why": None},
                         {"date": "2026-10-20", "text": "Old one.", "why": "A reason."}]}
    assert (second["text"], second["draft"], second["evidence"]) == (
        "Second view, with more words.", True, ["Spread of print"])
    assert (third["text"], third["evidence"], third["history"]) == ("No links.", [], [])
    assert p.note["positions"] == ["Topic#1", "Topic#2", "Topic#3"]
    assert {"kind": "positions", "ids": ["Topic#1", "Topic#2", "Topic#3"]} in p.note["blocks"]


def test_frontmatter_fields():
    p = note("# E\n", path="Library/Events/E.md", frontmatter=(
        "type: event\nconfidence: solid\nfrom: -44\nwhere: Europe\ncreated: 2026-10-01\n"
        "tags: [one, '#two']\nled_to: [[[Printing press]], \"[[Spread of print]]\", \"[[Not written]]\"]"))
    n = p.note
    assert n["event"] == {"from": -44, "to": None, "where": ["Europe"]}
    assert n["led_to"] == ["Printing press", "Spread of print"]
    assert (n["created"], n["updated"], n["tags"], n["confidence"]) == ("2026-10-01", None, ["one", "two"], "solid")
    assert n["links"] == ["Printing press", "Spread of print"]   # links in the frontmatter count too


def test_note_without_frontmatter_or_type():
    p = read("Library/Actors/Someone.md", b"Just text with [[Printing press]].", Resolver(IDS + ["Someone"]))
    assert p.note["type"] == "actor"
    assert p.note["title"] == "Someone"
    assert read("Loose.md", b"---\ntype: nonsense\n---\nx", Resolver(["Loose"])).note["type"] == "inbox"
    assert read("Home.md", b"x", Resolver(["Home"])).note["type"] == "home"
    session = read("Sessions/S.md", b"---\ntype: session\ndate: 2026-10-02\n---\n# S\n", Resolver(["S"]))
    assert session.note["created"] == "2026-10-02"


def test_windows_line_endings_read_the_same():
    body = "# Made up\r\n\r\n> [!claude] Title\r\n> Text.\r\n"
    raw = ("---\r\ntype: mechanism\r\n---\r\n" + body).encode()
    p = read("Library/Mechanisms/Made up.md", raw, Resolver(["Made up"]))
    assert p.note["title"] == "Made up"
    assert p.note["callouts"][0]["text"] == "Text."


def test_part_of_and_callout_spans():
    p = note("*Part of [[Printing press]], section 2.*\n\n> [!shaky]\n> One.\n\n> [!note]\n> skip\n\n"
             "> [!claude] T\n> Two\n> lines\n", path="Topics/Printing press/Made up.md",
             frontmatter="type: topic")
    assert p.note["part_of"] == {"note": "Printing press", "section": 2}
    body = "*Part of [[Printing press]], section 2.*\n\n> [!shaky]\n> One.\n\n> [!note]\n> skip\n\n> [!claude] T\n> Two\n"
    assert callout_spans(body) == [(2, 4), (8, 10)]
