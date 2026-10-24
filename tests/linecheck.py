"""The check behind `Block.lines` (docs/API.md), for the fixture vault and (counts only) the real vault.

For every block and list item of a note: its range lies in the source body and has no blank lines at its ends; the
app's step (replace the lines with a text, see `replace_lines`) with the same text gives back the identical body; and
the lines read again on their own give the same blocks, so the range holds exactly that block (nothing missing,
nothing of a neighbour). Ranges of different blocks do not overlap.
"""

from __future__ import annotations

from collections import Counter

from arestoteles.inline import Resolver
from arestoteles.reader import read

# Read again behind a title and a summary box, so a slice's own "# " heading or "[!summary]" callout reads as it did
# in its note (there they were not the first).
PREFIX = "# Title\n\n> [!summary]\n> Summary.\n\n"
PREFIX_LINES = PREFIX.count("\n")


def replace_lines(body: str, lines: list[int], text: str) -> str:
    """What the app does to edit one block: the body's lines [start, end) replaced by the text's lines."""
    rows = body.split("\n")
    start, end = lines
    return "\n".join(rows[:start] + text.split("\n") + rows[end:])


def _shifted(block: dict, by: int) -> dict:
    """The block with its ranges moved by `by` lines, and a callout's index (its place in the note) left out."""
    out = dict(block)
    if out.get("lines"):
        out["lines"] = [out["lines"][0] + by, out["lines"][1] + by]
    if "items" in out:
        out["items"] = [_shifted(item, by) for item in out["items"]]
    if out.get("kind") == "callout" and out.get("style") != "note":
        out["index"] = None
    return out


def _reread(note: dict, text: str, resolve: Resolver) -> list[dict]:
    raw = f"---\ntype: {note['type']}\n---\n{PREFIX}{text}\n".encode()
    return read(note["path"], raw, resolve).note["blocks"]


def _same(again: list[dict], blocks: list[dict]) -> bool:
    if len(blocks) == 1 and blocks[0]["kind"] == "positions":
        # the positions list read without its "## My position" heading is a plain ordered list
        return (len(again) == 1 and again[0]["kind"] == "list" and again[0]["ordered"]
                and sum(item["depth"] == 0 for item in again[0]["items"]) == len(blocks[0]["ids"]))
    return [_shifted(b, 0) for b in again] == [_shifted(b, 0) for b in blocks]


def check_note(note: dict, body: str, resolve: Resolver) -> Counter:
    """Counts: "blocks", "items", and one key per kind of problem (none expected)."""
    counts: Counter = Counter()
    rows = body.split("\n")

    def valid(lines: list[int] | None) -> bool:
        if lines is None:
            counts["no lines"] += 1
            return False
        start, end = lines
        if not (0 <= start < end <= len(rows)) or not rows[start].strip(" \t") or not rows[end - 1].strip(" \t"):
            counts["bad range"] += 1
            return False
        if replace_lines(body, lines, "\n".join(rows[start:end])) != body:
            counts["not identical"] += 1
        return True

    groups: dict[tuple[int, int], list[dict]] = {}   # blocks by range (a "→ [[A]], [[B]]" line gives two)
    for block in note["blocks"]:
        counts["blocks"] += 1
        if not valid(block["lines"]):
            continue
        groups.setdefault(tuple(block["lines"]), []).append(block)
        last = block["lines"][0]
        for item in block.get("items", []):
            counts["items"] += 1
            if valid(item["lines"]):
                start, end = item["lines"]
                if start < last or end > block["lines"][1]:
                    counts["item outside its list"] += 1
                last = end
    previous_end = 0
    for (start, end), blocks in groups.items():
        if start < previous_end:
            counts["overlap"] += 1
        previous_end = end
        again = _reread(note, "\n".join(rows[start:end]), resolve)
        if not _same([_shifted(b, start - PREFIX_LINES) for b in again], blocks):
            counts["read again differs"] += 1
    return counts


def problems(counts: Counter) -> dict[str, int]:
    return {key: value for key, value in counts.items() if key not in ("blocks", "items")}
