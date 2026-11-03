"""Obsidian's inline parts: wikilinks and embeds, how they resolve to notes, and the contract's Text.

Text (docs/API.md → Types) is inline Markdown: the author's source with every [[link]] turned into
[shown text](arestoteles://note/<id>#<anchor>), or into plain text when the note does not exist. Everything else
(bold, italic, code, web links) stays exactly as written.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable
from urllib.parse import quote

from .notefile import name_key

# [[target#anchor|alias]] and ![[…]]; `\|` is the escaped pipe Obsidian needs inside tables.
WIKILINK = re.compile(r"(!?)\[\[([^\[\]\n]+?)\]\]")
CODE_SPAN = re.compile(r"(`+)(?:.|\n)*?(?<!`)\1(?!`)")
_ESCAPE = re.compile(r"([\\\[\]*_`])")

Resolve = Callable[[str], "str | None"]


@dataclass(frozen=True)
class WikiLink:
    target: str          # the note name as written ("" for a link to a heading of the same note)
    anchor: str | None   # heading (or ^block) after '#'
    alias: str | None    # text after '|'
    embed: bool

    @property
    def shown(self) -> str:
        """What Obsidian shows for the link: the alias, else "Note > Heading", else the note name."""
        if self.alias:
            return self.alias
        if self.anchor:
            return f"{self.target} > {self.anchor}" if self.target else self.anchor
        return self.target


def parse_link(inner: str, embed: bool = False) -> WikiLink:
    inner = inner.replace("\\|", "|")
    target_part, bar, alias = inner.partition("|")
    target, hash_, anchor = target_part.partition("#")
    return WikiLink(target=target.strip(), anchor=anchor.strip() or None if hash_ else None,
                    alias=alias.strip() or None if bar else None, embed=embed)


def find_links(source: str) -> list[WikiLink]:
    return [parse_link(m[2], bool(m[1])) for m in WIKILINK.finditer(source)]


class Resolver:
    """Note name → note id, the way Obsidian finds a note: exact name, then ignoring case, then a path form."""

    def __init__(self, ids: Iterable[str]):
        self.ids = set(ids)
        self._folded: dict[str, str] = {}
        for note_id in sorted(self.ids):
            self._folded.setdefault(name_key(note_id).casefold(), note_id)

    def __call__(self, target: str) -> str | None:
        name = target.strip()
        if name.lower().endswith(".md"):
            name = name[:-3]
        if "/" in name:
            name = name.rsplit("/", 1)[1]
        if not name:
            return None
        if name in self.ids:
            return name
        return self._folded.get(name_key(name).casefold())


def escape(value: str) -> str:
    """Plain text made safe inside inline Markdown (and inside a link's [text])."""
    return _ESCAPE.sub(r"\\\1", value)


def note_url(note_id: str, anchor: str | None = None) -> str:
    url = "arestoteles://note/" + quote(note_id, safe="")
    return url + "#" + quote(anchor, safe="") if anchor else url


def _outside_code(source: str, convert: Callable[[str], str]) -> str:
    """Apply `convert` to everything except inline code spans."""
    out, last = [], 0
    for m in CODE_SPAN.finditer(source):
        out.append(convert(source[last:m.start()]))
        out.append(m[0])
        last = m.end()
    out.append(convert(source[last:]))
    return "".join(out)


def to_text(source: str, resolve: Resolve, self_id: str | None = None) -> str:
    """Inline Obsidian Markdown → the contract's Text."""
    def link(m: re.Match) -> str:
        wl = parse_link(m[2], bool(m[1]))
        note = (self_id if not wl.target else resolve(wl.target))
        if note is None:
            return escape(wl.shown)
        return f"[{escape(wl.shown)}]({note_url(note, wl.anchor)})"

    return _outside_code(source.strip(), lambda part: WIKILINK.sub(link, part))


def plain(source: str) -> str:
    """Inline source with links reduced to what Obsidian shows (for titles, anchors and glossary words)."""
    return WIKILINK.sub(lambda m: parse_link(m[2]).shown, source).strip()


def resolved_ids(links: Iterable[WikiLink], resolve: Resolve, exclude: str | None = None) -> list[str]:
    """Note ids of the links in order of first appearance, without duplicates."""
    seen: list[str] = []
    for wl in links:
        note = resolve(wl.target) if wl.target else None
        if note is not None and note != exclude and note not in seen:
            seen.append(note)
    return seen
