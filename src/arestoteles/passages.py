"""The vault's passages for search (docs/API.md → Search): every paragraph, list item, quote, callout, table and
position of the notes people read, with where it stands, its plain text and its sentences.

Built from the same index `/vault` serves (`Built.vault`), so a result's `note`/`block`/`item` point into exactly the
blocks the app shows. The index pages (Home, Positions, Glossary) only repeat titles and links and are left out, as
the app's `VaultSearch` does; the positions written on Positions.md ("Across topics") are passages all the same.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

INDEX_PAGES = ("home", "positions", "glossary")
PART_OF = re.compile(r"Part of .+, section \d+\.?")   # a section page's line naming its overview: no content


@dataclass(frozen=True)
class Passage:
    note: str
    block: int                     # index in the note's `blocks`
    item: int | None               # a list item's index in its list
    position: str | None           # a position's id (`block` is then the positions block it stands in)
    heading: str | None            # the heading it stands under, plain text
    text: str                      # inline Markdown as in /vault
    plain: str                     # `text` without the Markdown
    sentences: tuple[str, ...]     # plain text; a table gives one per row
    title: str                     # the note's title (context for ranking)


def passages(vault: dict) -> list[Passage]:
    positions = {p["id"]: p for group in vault["positions"] for p in group["positions"]}
    found: list[Passage] = []
    for note in vault["notes"]:
        on_index_page = note["type"] in INDEX_PAGES
        heading: str | None = None

        def add(index: int, text: str, sentences: list[str], *, item: int | None = None,
                position: str | None = None, extra: str = "") -> None:
            body = plain(text)
            if not body.strip():
                return
            found.append(Passage(note=note["id"], block=index, item=item, position=position, heading=heading,
                                 text=text, plain=body, sentences=tuple(sentences) or (body.strip(),),
                                 title=note["title"]))

        for index, block in enumerate(note["blocks"]):
            kind = block["kind"]
            if kind == "heading":
                heading = plain(block["text"]).strip() or None
            elif kind == "positions":
                for position_id in block["ids"]:
                    if position_id in positions:
                        text = positions[position_id]["text"]
                        add(index, text, split(plain(text)), position=position_id)
            elif on_index_page:
                continue
            elif kind in ("paragraph", "quote"):
                if note["part_of"] and PART_OF.fullmatch(plain(block["text"]).strip()):
                    continue
                add(index, block["text"], split(plain(block["text"])))
            elif kind == "list":
                for number, item in enumerate(block["items"]):
                    add(index, item["text"], split(plain(item["text"])), item=number)
            elif kind == "callout":
                # shown as the app's Lookup shows it: the title in bold before the text; the title is no sentence
                title = block["title"]
                text = f"**{title}** {block['text']}" if title else block["text"]
                add(index, text, split(plain(block["text"])))
            elif kind == "table":
                rows = [" · ".join(cells) for cells in [block["header"], *block["rows"]]]
                add(index, "\n".join(rows), [plain(row).strip() for row in rows[1:] if plain(row).strip()])
    return found


# ── plain text ──
def plain(markdown: str) -> str:
    """Inline Markdown → its words, as the app's InlineMarkdown.plain: escapes stand for themselves, `*` and `` ` ``
    go, `_` goes at a word's edge, a link leaves its text."""
    out: list[str] = []
    i, n = 0, len(markdown)
    while i < n:
        c = markdown[i]
        if c == "\\":
            if i + 1 < n:
                out.append(markdown[i + 1])
            i += 2
        elif c in "*`":
            i += 1
        elif c == "_" and _edge(markdown, i):
            i += 1
        elif c == "[":
            link = _link(markdown, i)
            if link is None:
                out.append(c)
                i += 1
            else:
                out.append(plain(link[0]))
                i = link[1]
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _edge(text: str, i: int) -> bool:
    before = text[i - 1] if i > 0 else " "
    after = text[i + 1] if i + 1 < len(text) else " "
    return not before.isalnum() or not after.isalnum()


def _link(text: str, start: int) -> tuple[str, int] | None:
    """`[text](destination)` at `start`: its text and the index after the closing parenthesis."""
    close = text.find("]", start)
    if close == -1 or close + 1 >= len(text) or text[close + 1] != "(":
        return None
    depth = 0
    for j in range(close + 1, len(text)):
        if text[j] == "(":
            depth += 1
        elif text[j] == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1:close], j + 1
    return None


# ── sentences ──
# Words before a full stop that do not end a sentence (English and German, folded to lower case, without the dot).
ABBREVIATIONS = frozenset("""
    e.g i.e etc vs cf ca c approx dr mr mrs ms st no nos vol vols pp p ed eds jr sr fig al u.s u.k b.c a.d bce ce
    z.b d.h u.a bzw vgl usw nr jh jhd bspw ggf inkl evtl s.o s.u o.a v.chr n.chr
""".split())
_END = re.compile(r"[.!?…]+[\"'”’)\]]*(?=\s+)")
_LIST_MARK = re.compile(r"^(?:•|\d{1,3}\.)\s+")


def split(text: str) -> list[str]:
    """Plain text → its sentences: each line on its own (a callout's list items, a line break in a paragraph), and
    within a line at ".", "!", "?" before a space, except after an abbreviation or an initial ("e.g.", "A. Smith")."""
    found: list[str] = []
    for line in text.split("\n"):
        line = _LIST_MARK.sub("", line.strip())
        start = 0
        for m in _END.finditer(line):
            before = line[start:m.start()].rsplit(None, 1)
            word = before[-1].lower().lstrip("(\"'„“") if before else ""
            nxt = line[m.end():].lstrip()
            if m.group().startswith(".") and (word in ABBREVIATIONS or (len(word) == 1 and word.isalpha())):
                continue
            if nxt and nxt[0].islower():
                continue
            found.append(line[start:m.end()].strip())
            start = m.end()
        rest = line[start:].strip()
        if rest:
            found.append(rest)
    return [s for s in found if s]
