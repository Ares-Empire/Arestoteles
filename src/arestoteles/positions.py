"""The line grammar of positions and of "How my view changed", shared by the reader and the edits.

A position is one numbered line in a note's `## My position` (topic overviews) or Positions.md's `## Across topics`:

    2. **Printers were businessmen first; they printed what sold.** *(draft)* → [[Information wants to be cheap]]

A history entry is one bullet in that note's `## How my view changed`, newest first:

    - **2026-10-20, position 1:** I thought: Print caused the Reformation. What changed it: Earlier reformers …

The ", position N" names the position the entry belongs to (CONTRACT ADDITION in docs/API.md); an entry without it
(a dropped position, or one written by hand) belongs to no current position.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

HEADING = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
ITEM = re.compile(r"^(\d{1,9})([.)])[ \t]+(.*)$")
BULLET = re.compile(r"^[-*+][ \t]+")
DRAFT = re.compile(r"[ \t]*[*_]?\(draft\)[*_]?", re.I)
BOLD = re.compile(r"\*\*(.+?)\*\*")
ENTRY = re.compile(r"^[-*+][ \t]+\*\*(\d{4}-\d{2}-\d{2})(?:,[ \t]*position[ \t]+(\d+))?:?\*\*:?[ \t]*(.*)$")
ENTRY_POSITION = re.compile(r"^([-*+][ \t]+\*\*\d{4}-\d{2}-\d{2}),[ \t]*position[ \t]+(\d+)(:?\*\*)")

MY_POSITION = "My position"
ACROSS_TOPICS = "Across topics"
HISTORY = "How my view changed"
SOURCES = "Sources"


def heading(line: str) -> tuple[int, str] | None:
    m = HEADING.match(line)
    return (len(m[1]), m[2]) if m else None


def section(lines: list[str], title: str, level: int = 2) -> tuple[int, int] | None:
    """(index of the `## title` line, index after the section's last line), or None."""
    for i, line in enumerate(lines):
        h = heading(line)
        if h and h[0] == level and h[1] == title:
            end = i + 1
            while end < len(lines):
                h2 = heading(lines[end])
                if h2 and h2[0] <= level:
                    break
                end += 1
            return i, end
    return None


@dataclass(frozen=True)
class Item:
    start: int        # the numbered line
    end: int          # after its last continuation line
    delimiter: str    # "." or ")"
    content: str      # the line after "N. "

    @property
    def sentence(self) -> str:
        """The part before the arrow: the bold sentence, maybe "(draft)" and more words."""
        return self.content.split("→", 1)[0].rstrip()

    @property
    def evidence(self) -> str | None:
        """The raw part after the arrow ("[[A]], [[B]]"), or None without an arrow."""
        parts = self.content.split("→", 1)
        return parts[1].strip() if len(parts) == 2 else None

    @property
    def draft(self) -> bool:
        return bool(DRAFT.search(self.sentence))

    @property
    def text(self) -> str:
        """The position's words in source form: without bold markers, "(draft)" and the arrow part."""
        return re.sub(r"\s{2,}", " ", DRAFT.sub("", self.sentence).replace("**", "")).strip()

    @property
    def title(self) -> str:
        """The position in short: its bold part ("**Business wants labour as powerless as possible,** even if …" →
        "Business wants labour as powerless as possible"), without a trailing comma, semicolon or colon; the whole text
        when it has no bold part or is bold throughout."""
        bold = BOLD.search(DRAFT.sub("", self.sentence))
        if not bold:
            return self.text
        return re.sub(r"\s{2,}", " ", bold.group(1)).strip().rstrip(",;:").strip() or self.text


def items(lines: list[str], span: tuple[int, int]) -> list[Item]:
    """The numbered lines of the first ordered list in a section."""
    found: list[Item] = []
    i, end = span[0] + 1, span[1]
    while i < end and not ITEM.match(lines[i]):
        i += 1
    while i < end:
        m = ITEM.match(lines[i])
        if not m:
            break
        stop = i + 1
        while stop < end and lines[stop][:1] in (" ", "\t") and lines[stop].strip():
            stop += 1
        found.append(Item(i, stop, m[2], m[3]))
        i = stop
        while i < end and not lines[i].strip():   # blank lines inside a loose list
            i += 1
        if i < end and not ITEM.match(lines[i]):
            break
    return found


def position_section(lines: list[str], across: bool) -> tuple[int, int] | None:
    return section(lines, ACROSS_TOPICS if across else MY_POSITION)


@dataclass(frozen=True)
class Entry:
    line: int
    date: str
    position: int | None
    text: str           # what Patrik thought (source form)
    why: str | None     # what changed it


def entries(lines: list[str]) -> list[Entry]:
    span = section(lines, HISTORY)
    if span is None:
        return []
    found = []
    for i in range(span[0] + 1, span[1]):
        m = ENTRY.match(lines[i])
        if not m:
            continue
        rest = re.sub(r"^I thought:\s*", "", m[3].strip(), flags=re.I)
        thought, marker, why = rest.partition("What changed it:")
        found.append(Entry(i, m[1], int(m[2]) if m[2] else None, thought.strip(),
                           why.strip() or None if marker else None))
    return found


def sentence_end(value: str) -> str:
    """The words with a full stop, unless they already end a sentence."""
    value = value.strip()
    return value if value[-1:] in ".!?…" else value + "."


def entry_line(day: str, old_text: str, why: str, position: int | None) -> str:
    where = f", position {position}" if position is not None else ""
    return f"- **{day}{where}:** I thought: {sentence_end(old_text)} What changed it: {why.strip()}"


def position_line(number: int, delimiter: str, text: str, evidence: str | None) -> str:
    line = f"{number}{delimiter} **{text.strip()}**"
    return f"{line} → {evidence}" if evidence else line


def renumber_entry(line: str, dropped: int) -> str:
    """After position `dropped` went: its entries lose their number, later positions move up by one."""
    m = ENTRY_POSITION.match(line)
    if not m:
        return line
    number = int(m[2])
    if number == dropped:
        return m[1] + m[3] + line[m.end():]
    if number > dropped:
        return f"{m[1]}, position {number - 1}{m[3]}" + line[m.end():]
    return line
