"""One note file → the contract's `Note` (docs/API.md → Types), plus what the index needs from it.

markdown-it-py gives the CommonMark block structure (headings, paragraphs, lists, quotes, tables); the Obsidian parts
are added here: callouts and their titles, the summary box, embeds, `→ [[…]]` section links, the positions list,
"How my view changed", the part-of line, the glossary table and Home's "To learn about next". Text fields are the
author's inline source with links turned into note URLs (inline.to_text).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from markdown_it import MarkdownIt
from markdown_it.token import Token

from . import notefile
from . import positions as pos
from .inline import Resolver, find_links, parse_link, plain, resolved_ids, to_text

NOTE_TYPES = ("topic", "mechanism", "event", "actor", "question", "session", "inbox", "home", "positions", "glossary")
CONFIDENCE = ("solid", "my-read", "shaky")
CALLOUT = re.compile(r"^\[!([A-Za-z][\w-]*)\][-+]?[ \t]*(.*)$")
EMBED_LINE = re.compile(r"!\[\[([^\[\]\n]+?)\]\]")
ARROW_LINE = re.compile(r"→[ \t]*\[\[[^\[\]\n]+?\]\](?:[ \t]*,[ \t]*\[\[[^\[\]\n]+?\]\])*")
PART_OF = re.compile(r"Part of \[\[([^\[\]\n]+?)\]\],?\s*section\s+(\d+)")
NUMBERED = re.compile(r"^(\d+)\.\s+(.*)$")
LEARN_NEXT = "To learn about next"
FOLDER_TYPES = {"Topics": "topic", "Library/Mechanisms": "mechanism", "Library/Events": "event",
                "Library/Actors": "actor", "Library/Questions": "question", "Sessions": "session", "Inbox": "inbox"}
SPECIAL_NOTES = {"Home": "home", "Positions": "positions", "Glossary": "glossary"}

_md = MarkdownIt("commonmark").enable("table")


@dataclass
class Parsed:
    note: dict                                   # the contract's Note; topic, backlinks, brief come from the index
    positions: list[dict] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    embeds: list[tuple[str, str | None]] = field(default_factory=list)
    sections: list[dict] = field(default_factory=list)    # numbered sections: {title, summary, note}
    terms: list[dict] = field(default_factory=list)       # the glossary table's rows
    learn_next: list[str] = field(default_factory=list)   # Home's "To learn about next"


def note_type(declared: object, path: str) -> str:
    if isinstance(declared, str) and declared in NOTE_TYPES:
        return declared
    stem = PurePosixPath(path).stem
    if "/" not in path and stem in SPECIAL_NOTES:
        return SPECIAL_NOTES[stem]
    for folder, kind in FOLDER_TYPES.items():
        if path.startswith(folder + "/"):
            return kind
    return "inbox"   # unsorted raw material; the vault check reports the missing type


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return []


def _year(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _led_to(value: object, resolve: Resolver) -> list[str]:
    out: list[str] = []
    for item in value if isinstance(value, list) else [value]:
        if isinstance(item, str):
            targets = [wl.target for wl in find_links(item)]
        else:   # YAML reads an unquoted [[X]] as a nested list
            targets = _strings(item)
        for target in targets:
            note = resolve(target)
            if note and note not in out:
                out.append(note)
    return out


def _close(tokens: list[Token], i: int) -> int:
    """Index of the token closing tokens[i]."""
    kind, level = tokens[i].type.replace("_open", "_close"), tokens[i].level
    j = i + 1
    while not (tokens[j].type == kind and tokens[j].level == level):
        j += 1
    return j


class _Body:
    """Walks one note's tokens and fills `Parsed`."""

    def __init__(self, parsed: Parsed, note_id: str, resolve: Resolver, positions_title: str):
        self.p, self.id, self.resolve = parsed, note_id, resolve
        self.positions_title = positions_title
        self.blocks: list[dict] = parsed.note["blocks"]
        self.section: str | None = None          # the current `##` title
        self.numbered: dict | None = None        # the current numbered section (for the brief)
        self.title: str | None = None
        self.summary: str | None = None
        self.positions_done = False

    def text(self, source: str) -> str:
        return to_text(source, self.resolve, self.id)

    # ── blocks ──
    def walk(self, tokens: list[Token]) -> None:
        i = 0
        while i < len(tokens):
            t = tokens[i]
            if t.type == "heading_open":
                self.heading(int(t.tag[1]), tokens[i + 1].content)
                i += 3
            elif t.type == "paragraph_open":
                self.paragraph(tokens[i + 1].content)
                i += 3
            elif t.type in ("bullet_list_open", "ordered_list_open"):
                j = _close(tokens, i)
                self.list(tokens[i:j + 1])
                i = j + 1
            elif t.type == "blockquote_open":
                j = _close(tokens, i)
                self.quote(tokens[i + 1:j])
                i = j + 1
            elif t.type == "table_open":
                j = _close(tokens, i)
                self.table(tokens[i:j + 1])
                i = j + 1
            elif t.type == "hr":
                self.blocks.append({"kind": "rule"})
                i += 1
            elif t.type in ("fence", "code_block"):
                self.blocks.append({"kind": "paragraph", "text": _code(t.content)})
                i += 1
            elif t.type == "html_block":
                if not t.content.lstrip().startswith("<!--"):
                    self.blocks.append({"kind": "paragraph", "text": self.text(t.content)})
                i += 1
            else:
                i += 1

    def heading(self, level: int, source: str) -> None:
        if level == 1 and self.title is None:
            self.title = plain(source) or None
            return
        if level <= 2:
            self.section = source.strip()
            m = NUMBERED.match(self.section)
            self.numbered = None
            if m and self.p.note["type"] == "topic":
                self.numbered = {"title": plain(m[2]), "summary": None, "note": None}
                self.p.sections.append(self.numbered)
        self.blocks.append({"kind": "heading", "level": min(max(level, 2), 4), "text": self.text(source),
                            "anchor": plain(source)})

    def paragraph(self, source: str) -> None:
        lines: list[str] = []

        def flush() -> None:
            if lines:
                value = self.text("\n".join(lines))
                self.blocks.append({"kind": "paragraph", "text": value})
                if self.numbered is not None and self.numbered["summary"] is None:
                    self.numbered["summary"] = value
                lines.clear()

        for line in source.split("\n"):
            stripped = line.strip()
            embed = EMBED_LINE.fullmatch(stripped)
            if embed:
                wl = parse_link(embed[1], embed=True)
                note = self.resolve(wl.target) if wl.target else None
                if note:
                    flush()
                    self.blocks.append({"kind": "embed", "note": note, "anchor": wl.anchor})
                    self.p.embeds.append((note, wl.anchor))
                    continue
            if ARROW_LINE.fullmatch(stripped):
                notes = [self.resolve(wl.target) for wl in find_links(stripped)]
                if notes and all(notes):
                    flush()
                    for note in notes:
                        self.blocks.append({"kind": "section_link", "note": note})
                        if self.numbered is not None and self.numbered["note"] is None:
                            self.numbered["note"] = note
                    continue
            lines.append(line)
        flush()

    def list(self, tokens: list[Token]) -> None:
        if (tokens[0].type == "ordered_list_open" and not self.positions_done
                and self.section == self.positions_title):
            self.positions_done = True
            self.blocks.append({"kind": "positions", "ids": [p["id"] for p in self.p.positions]})
            return
        items = [{"text": self.text(source), "depth": depth} for source, depth in _items(tokens)]
        self.blocks.append({"kind": "list", "ordered": tokens[0].type == "ordered_list_open", "items": items})
        if self.section == LEARN_NEXT and self.p.note["type"] == "home":
            self.p.learn_next.extend(item["text"] for item in items if item["depth"] == 0)

    def quote(self, inner: list[Token]) -> None:
        first = inner[1].content if len(inner) > 1 and inner[0].type == "paragraph_open" else None
        m = CALLOUT.match(first.split("\n", 1)[0]) if first is not None else None
        if m is None:
            self.blocks.append({"kind": "quote", "text": self._inner_text(inner, None)})
            return
        kind, title = m[1].lower(), m[2].strip()
        rest = first.split("\n", 1)[1] if "\n" in first else ""
        body = self._inner_text(inner[3:], rest)
        if kind == "summary" and self.summary is None:
            self.summary = body
            return
        style = kind if kind in ("claude", "shaky") else "note"
        index = -1
        if style != "note":
            callouts = self.p.note["callouts"]
            index = len(callouts)
            callouts.append({"index": index, "style": style, "title": plain(title) or None, "text": body})
        self.blocks.append({"kind": "callout", "style": style, "title": self.text(title) if title else None,
                            "text": body, "index": index})

    def _inner_text(self, inner: list[Token], first_rest: str | None) -> str:
        """A quote's or callout's content as one Text: paragraphs apart by a blank line, list items as lines."""
        parts: list[str] = []
        if first_rest is not None and first_rest.strip():
            parts.append(self.text(first_rest))
        i = 0
        while i < len(inner):
            t = inner[i]
            if t.type in ("paragraph_open", "heading_open"):
                parts.append(self.text(inner[i + 1].content))
                i += 3
            elif t.type in ("bullet_list_open", "ordered_list_open"):
                j = _close(inner, i)
                ordered = t.type == "ordered_list_open"
                lines = [("  " * depth) + (f"{n}. " if ordered and depth == 0 else "• ") + self.text(source)
                         for n, (source, depth) in enumerate(_items(inner[i:j + 1]), start=1)]
                parts.append("\n".join(lines))
                i = j + 1
            elif t.type in ("blockquote_open", "table_open"):
                j = _close(inner, i)
                parts.extend(self.text(x.content) for x in inner[i:j] if x.type == "inline" and x.content.strip())
                i = j + 1
            elif t.type in ("fence", "code_block"):
                parts.append(_code(t.content))
                i += 1
            else:
                i += 1
        return "\n\n".join(p for p in parts if p)

    def table(self, tokens: list[Token]) -> None:
        rows: list[list[str]] = []
        sources: list[list[str]] = []
        for t in tokens:
            if t.type == "tr_open":
                rows.append([])
                sources.append([])
            elif t.type == "inline":
                rows[-1].append(self.text(t.content))
                sources[-1].append(t.content)
        if not rows:
            return
        self.blocks.append({"kind": "table", "header": rows[0], "rows": rows[1:]})
        if self.p.note["type"] == "glossary" and not self.p.terms:
            self.p.terms = _terms(sources, self.resolve)


def _items(tokens: list[Token]) -> list[tuple[str, int]]:
    """A list's items in order as (inline source, depth), nested lists flattened."""
    out: list[tuple[str, int]] = []
    base = tokens[0].level
    current: list[str] | None = None
    for t in tokens:
        if t.type == "list_item_open":
            current = []
            out.append(("", (t.level - base - 1) // 2))
        elif t.type == "inline" and current is not None and out:
            # only the item's own paragraphs (a nested list's items open their own entry first)
            source, depth = out[-1]
            out[-1] = (source + "\n" + t.content if source else t.content, depth)
    return out


def _terms(rows: list[list[str]], resolve: Resolver) -> list[dict]:
    header = [plain(cell).casefold() for cell in rows[0]]
    if "english" not in header or "german" not in header:
        return []
    e, g = header.index("english"), header.index("german")
    w = header.index("where") if "where" in header else 2
    terms = []
    for row in rows[1:]:
        cells = row + [""] * (max(e, g, w) + 1 - len(row))
        english = plain(cells[e])
        if not english:
            continue
        links = [resolve(wl.target) for wl in find_links(cells[w]) if wl.target]
        terms.append({"english": english, "german": plain(cells[g]),
                      "note": next((note for note in links if note), None)})
    return terms


def _code(content: str) -> str:
    return "\n".join(f"`` {line} ``" if "`" in line else f"`{line}`" for line in content.rstrip("\n").split("\n")
                     if line.strip())


def callout_spans(body: str) -> list[tuple[int, int]]:
    """Body line ranges [start, end) of the note's claude/shaky callouts, in the order of `Note.callouts`."""
    tokens = _md.parse(body)
    spans = []
    for i, t in enumerate(tokens):
        if t.type == "blockquote_open" and t.level == 0 and t.map and tokens[i + 1].type == "paragraph_open":
            m = CALLOUT.match(tokens[i + 2].content.split("\n", 1)[0])
            if m and m[1].lower() in ("claude", "shaky"):
                spans.append((t.map[0], t.map[1]))
    return spans


def read(path: str, raw: bytes, resolve: Resolver) -> Parsed:
    text = notefile.decode(raw)
    frontmatter, body = notefile.split(text)
    fm = notefile.parse(frontmatter)
    note_id = PurePosixPath(path).stem
    kind = note_type(fm.get("type"), path)
    confidence = fm.get("confidence")
    links = find_links(text)
    note = {
        "id": note_id, "path": path, "type": kind, "title": note_id, "summary": None,
        "confidence": confidence if confidence in CONFIDENCE else None,
        "created": notefile.iso(fm.get("created")) or notefile.iso(fm.get("date")),
        "updated": notefile.iso(fm.get("updated")),
        "tags": [t.strip().lstrip("#") for t in _strings(fm.get("tags")) if t.strip()],
        "topic": None, "part_of": None,
        "event": ({"from": _year(fm.get("from")), "to": _year(fm.get("to")), "where": _strings(fm.get("where"))}
                  if kind == "event" else None),
        "led_to": _led_to(fm.get("led_to"), resolve),
        "links": resolved_ids(links, resolve, exclude=note_id),
        "backlinks": [], "positions": [], "callouts": [], "blocks": [], "brief": None,
        "version": notefile.blob_hash(raw),
    }
    parsed = Parsed(note=note, unresolved=sorted({wl.target for wl in links if wl.target and resolve(wl.target) is None}))

    lines = body.split("\n")
    parsed.positions = _positions(lines, note_id, resolve, across=(kind == "positions"))
    note["positions"] = [p["id"] for p in parsed.positions]

    part_of = PART_OF.search(body)
    if part_of:
        target = resolve(parse_link(part_of[1]).target)
        if target:
            note["part_of"] = {"note": target, "section": int(part_of[2])}

    walker = _Body(parsed, note_id, resolve, pos.ACROSS_TOPICS if kind == "positions" else pos.MY_POSITION)
    walker.walk(_md.parse(body))
    note["title"] = walker.title or note_id
    note["summary"] = walker.summary
    for section in parsed.sections:
        section["summary"] = section["summary"] or ""
    return parsed


def _positions(lines: list[str], note_id: str, resolve: Resolver, across: bool) -> list[dict]:
    span = pos.position_section(lines, across)
    if span is None:
        return []
    history = pos.entries(lines)
    out = []
    for number, item in enumerate(pos.items(lines, span), start=1):
        mine = sorted((e for e in history if e.position == number), key=lambda e: e.date, reverse=True)
        out.append({
            "id": f"{note_id}#{number}", "note": note_id, "number": number,
            "text": to_text(item.text, resolve, note_id), "draft": item.draft,
            "evidence": resolved_ids(find_links(item.evidence or ""), resolve),
            "history": [{"date": e.date, "text": to_text(e.text, resolve, note_id),
                         "why": to_text(e.why, resolve, note_id) if e.why else None} for e in mine],
        })
    return out
