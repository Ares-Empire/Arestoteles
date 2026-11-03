"""A note file as text: its frontmatter (read and line-edited, never re-dumped), its body, its git blob hash."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date

import yaml

FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)   # the vault check's own pattern


def name_key(name: str) -> str:
    """Compare macOS's decomposed names with names sent by clients, without renaming files."""
    return unicodedata.normalize("NFC", name)


def blob_hash(raw: bytes) -> str:
    """The git blob hash of a file's bytes (what `git hash-object` prints)."""
    return hashlib.sha1(b"blob %d\x00" % len(raw) + raw).hexdigest()


def decode(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace").replace("\r\n", "\n")


def encode(text: str, crlf: bool = False) -> bytes:
    return (text.replace("\n", "\r\n") if crlf else text).encode("utf-8")


def split(text: str) -> tuple[str | None, str]:
    """(frontmatter source or None, body). The body is everything after the closing `---` line."""
    m = FRONTMATTER.match(text)
    return (m[1], text[m.end():]) if m else (None, text)


def parse(frontmatter: str | None) -> dict:
    if not frontmatter:
        return {}
    try:
        data = yaml.safe_load(frontmatter)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def iso(value: object) -> str | None:
    if isinstance(value, date):
        return value.isoformat()[:10]
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _field(lines: list[str], key: str) -> tuple[int, int] | None:
    """The frontmatter lines [start, end) of a top-level `key:` with its multi-line value (indented or list lines)."""
    for i, current in enumerate(lines):
        if re.match(rf"{re.escape(key)}\s*:", current):
            end = i + 1
            while end < len(lines) and lines[end][:1] in (" ", "\t", "-") and lines[end].strip():
                end += 1
            return i, end
    return None


def set_field(text: str, key: str, value: str, after: tuple[str, ...] = ()) -> str:
    """Set a top-level scalar `key: value` in the frontmatter, keeping every other line as it is.

    A missing key goes after the first of `after` that exists, else at the end. A note without frontmatter is
    returned unchanged (the vault check reports it)."""
    m = FRONTMATTER.match(text)
    if not m:
        return text
    lines = m[1].split("\n")
    line = f"{key}: {value}"
    span = _field(lines, key)
    if span is not None:
        lines[span[0]:span[1]] = [line]   # an old multi-line value goes with it
    else:
        at = len(lines)
        for anchor in after:
            hit = _field(lines, anchor)
            if hit is not None:
                at = hit[1]   # after its whole value
                break
        lines.insert(at, line)
    return "---\n" + "\n".join(lines) + "\n---\n" + text[m.end():]


def remove_field(text: str, key: str) -> str:
    """Remove a top-level `key:` (and its multi-line value) from the frontmatter; every other line stays."""
    m = FRONTMATTER.match(text)
    if not m:
        return text
    lines = m[1].split("\n")
    span = _field(lines, key)
    if span is None:
        return text
    del lines[span[0]:span[1]]
    return "---\n" + "\n".join(lines) + "\n---\n" + text[m.end():]
