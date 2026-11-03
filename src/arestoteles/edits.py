"""Every edit of the contract (docs/API.md → Edits) as a change to the vault's files, by the vault's own rules.

Pure: the current files come in, the new files go out (`Plan`); writing, checking, committing and pushing is the
service's job. Positions keep their bold, numbering, `→` links and Positions.md's embeds; changed and dropped views go
to "How my view changed"; every edited note gets `updated: <today>`; a quick note is written verbatim (its
frontmatter says what it is about and whether it is a "discuss later" mark).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from . import notefile
from . import positions as pos
from .index import Built
from .reader import callout_spans

CONFIDENCE_TYPES = ("topic", "mechanism", "event", "question")
FORBIDDEN_IN_NAMES = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]')
QUOTE_MARK = re.compile(r"^ {0,3}> ?")


class EditError(Exception):
    """An edit that cannot apply: 404 / 409 / 422 with a texts key; 409 names the note to send as `current`."""

    def __init__(self, status: int, key: str, current: str | None = None, **values: object):
        super().__init__(key)
        self.status, self.key, self.current, self.values = status, key, current, values


@dataclass
class Plan:
    message: str = ""
    files: dict[str, str] = field(default_factory=dict)   # path → new text (LF)
    created: list[str] = field(default_factory=list)      # paths of new files
    changed: list[str] = field(default_factory=list)      # note ids
    reads: set[str] = field(default_factory=set)          # files (or folder prefixes) the edit depends on


@dataclass
class _Note:
    """One note's file being edited: frontmatter prefix + body lines."""
    id: str
    path: str
    prefix: str
    lines: list[str]

    @property
    def text(self) -> str:
        return self.prefix + "\n".join(self.lines)

    @property
    def frontmatter(self) -> dict:
        m = notefile.FRONTMATTER.match(self.prefix)
        return notefile.parse(m[1]) if m else {}

    def set_field(self, key: str, value: str, after: tuple[str, ...] = ()) -> None:
        self._new_prefix(notefile.set_field(self.prefix, key, value, after))

    def remove_field(self, key: str) -> None:
        self._new_prefix(notefile.remove_field(self.prefix, key))

    def _new_prefix(self, prefix: str) -> None:
        if notefile.FRONTMATTER.fullmatch(prefix):
            self.prefix = prefix


class Editor:
    def __init__(self, vault: Built, read: Callable[[str], bytes], today: str, now: datetime):
        self.vault, self.read, self.today, self.now = vault, read, today, now
        self.reads: set[str] = set()

    # ── shared steps ──
    def note(self, note_id: str, version: str | None = None) -> _Note:
        path = self.vault.paths.get(note_id)
        if path is None:
            raise EditError(404, "unknown_note")
        if note_id in self.vault.duplicates:
            raise EditError(409, "ambiguous_note", current=note_id)
        try:
            raw = self.read(path)
        except FileNotFoundError:
            raise EditError(409, "note_changed", current=None) from None
        if version is not None and notefile.blob_hash(raw) != version:
            raise EditError(409, "note_changed", current=note_id)
        self.reads.add(path)
        try:
            text = raw.decode("utf-8").replace("\r\n", "\n")
        except UnicodeDecodeError:
            raise EditError(422, "invalid_encoding") from None
        m = notefile.FRONTMATTER.match(text)
        prefix = m[0] if m else ""
        return _Note(note_id, path, prefix, text[len(prefix):].split("\n"))

    def finish(self, plan: Plan, *notes: _Note) -> Plan:
        """Put the edited notes into the plan with `updated` set, unless nothing changed."""
        for n in notes:
            new = n.text
            old = notefile.decode(self.read(n.path))
            if new == old:
                continue
            plan.files[n.path] = notefile.set_field(new, "updated", self.today, after=("created", "type"))
            plan.changed.append(n.id)
        if not plan.files:
            plan.message = ""
        return plan

    def position(self, position_id: str, single_line: bool = False) -> tuple[_Note, list[pos.Item], int]:
        note_id, sep, number = position_id.rpartition("#")
        if not sep or not number.isdigit() or note_id not in self.vault.paths:
            raise EditError(404, "unknown_position")
        n = self.note(note_id)
        across = self.vault.notes[note_id]["type"] == "positions"
        span = pos.position_section(n.lines, across)
        items = pos.items(n.lines, span) if span else []
        if not items and not self.vault.notes[note_id]["positions"] and note_id not in self.vault.overviews:
            raise EditError(404, "unknown_position")
        k = int(number)
        if not 1 <= k <= len(items):
            raise EditError(409, "position_gone", current=note_id)
        if single_line and items[k - 1].end != items[k - 1].start + 1:
            raise EditError(422, "position_multiline")
        return n, items, k

    def history(self, n: _Note, line: str) -> None:
        """Add an entry at the top of "How my view changed" (made before "Sources", else at the end)."""
        span = pos.section(n.lines, pos.HISTORY)
        if span is not None:
            first = next((i for i in range(span[0] + 1, span[1]) if pos.BULLET.match(n.lines[i])), None)
            at = first if first is not None else _content_end(n.lines, span)
            n.lines.insert(at, line)
            return
        sources = pos.section(n.lines, pos.SOURCES)
        if sources is not None:
            n.lines[sources[0]:sources[0]] = [f"## {pos.HISTORY}", line, ""]
        else:
            _append_section(n.lines, [f"## {pos.HISTORY}", line])

    # ── the ops ──
    def confirm_position(self, position: str) -> Plan:
        n, items, k = self.position(position)
        item = items[k - 1]
        n.lines[item.start] = pos.DRAFT.sub("", n.lines[item.start]).rstrip()
        return self.finish(Plan(f"App: confirm position {k} ({n.id})"), n)

    def reword_position(self, position: str, text: str) -> Plan:
        words = _position_words(text)
        n, items, k = self.position(position, single_line=True)
        item = items[k - 1]
        n.lines[item.start:item.end] = [pos.position_line(k, item.delimiter, words, item.evidence)]
        return self.finish(Plan(f"App: reword position {k} ({n.id})"), n)

    def change_position(self, position: str, text: str, why: str) -> Plan:
        words, reason = _position_words(text), _why(why)
        n, items, k = self.position(position, single_line=True)
        item = items[k - 1]
        old = item.text
        n.lines[item.start:item.end] = [pos.position_line(k, item.delimiter, words, item.evidence)]
        self.history(n, pos.entry_line(self.today, old, reason, k))
        return self.finish(Plan(f"App: change position {k} ({n.id})"), n)

    def drop_position(self, position: str, why: str) -> Plan:
        reason = _why(why)
        n, items, k = self.position(position, single_line=True)
        item = items[k - 1]
        del n.lines[item.start:item.end]
        across = self.vault.notes[n.id]["type"] == "positions"
        span = pos.position_section(n.lines, across)
        for number, later in enumerate(pos.items(n.lines, span) if span else [], start=1):
            n.lines[later.start] = re.sub(r"^\d+", str(number), n.lines[later.start], count=1)
        history = pos.section(n.lines, pos.HISTORY)
        if history is not None:
            for i in range(history[0] + 1, history[1]):
                n.lines[i] = pos.renumber_entry(n.lines[i], k)
        self.history(n, pos.entry_line(self.today, item.text, reason, None))
        return self.finish(Plan(f"App: drop position {k} ({n.id})"), n, *self._inbox_after_drop(n.id, k))

    def _inbox_after_drop(self, note_id: str, dropped: int) -> list[_Note]:
        """Inbox notes about a position move with the list as history entries do: those about the dropped position
        lose their number (they stay about the note), those about later positions move up by one."""
        self.reads.add("Inbox/")   # a concurrently added mark must be renumbered too
        moved = []
        for inbox_id, other in sorted(self.vault.notes.items()):
            about = other.get("inbox") or {}
            if about.get("about") != note_id or about.get("position") is None:
                continue
            n = self.note(inbox_id)
            number = n.frontmatter.get("position")
            if not isinstance(number, int) or isinstance(number, bool) or number < dropped:
                continue
            if number == dropped:
                n.remove_field("position")
            else:
                n.set_field("position", str(number - 1))
            moved.append(n)
        return moved

    def add_position(self, note: str, text: str, evidence: list[str]) -> Plan:
        words = _position_words(text)
        if note not in self.vault.paths:
            raise EditError(404, "unknown_note")
        across = self.vault.notes[note]["type"] == "positions"
        if not across and note not in self.vault.overviews:
            raise EditError(422, "not_position_note")
        for target in evidence:
            if target not in self.vault.paths:
                raise EditError(422, "unknown_evidence", note=target)
            self.reads.add(self.vault.paths[target])
        n = self.note(note)
        links = ", ".join(f"[[{target}]]" for target in dict.fromkeys(evidence))
        span = pos.position_section(n.lines, across)
        touched = [n]
        if span is None:
            k = 1
            line = pos.position_line(k, ".", words, links or None)
            title = pos.ACROSS_TOPICS if across else pos.MY_POSITION
            _create_position_section(n.lines, title, line, across)
            if not across:
                touched += self._embed_on_positions_page(note)
        else:
            items = pos.items(n.lines, span)
            k = len(items) + 1
            line = pos.position_line(k, items[0].delimiter if items else ".", words, links or None)
            n.lines.insert(items[-1].end if items else _content_end(n.lines, span), line)
        return self.finish(Plan(f"App: add position {k} ({note})"), *touched)

    def _embed_on_positions_page(self, topic: str) -> list[_Note]:
        page_id = next((i for i, note in self.vault.notes.items() if note["type"] == "positions"), None)
        if page_id is None:
            return []
        page = self.note(page_id)
        embed = f"![[{topic}#My position]]"
        if any(embed in line for line in page.lines):
            return []
        block = [f"### {self.vault.notes[topic]['title']}", embed]
        span = pos.section(page.lines, "By topic")
        if span is None:
            _append_section(page.lines, ["## By topic", "", *block])
        else:
            end = _content_end(page.lines, span)
            page.lines[end:end] = ["", *block] if end > span[0] + 1 else block
        return [page]

    def set_confidence(self, note: str, confidence: str) -> Plan:
        n = self.note(note)
        if self.vault.notes[note]["type"] not in CONFIDENCE_TYPES:
            raise EditError(422, "no_confidence")
        n.set_field("confidence", confidence, after=("type",))
        return self.finish(Plan(f"App: set confidence {confidence} ({note})"), n)

    def _callout(self, note: str, callout: int, version: str) -> tuple[_Note, int, int]:
        n = self.note(note, version)
        spans = callout_spans("\n".join(n.lines))
        if not 0 <= callout < len(spans):
            raise EditError(404, "unknown_callout")
        return n, *spans[callout]

    def adopt_callout(self, note: str, callout: int, version: str) -> Plan:
        n, start, end = self._callout(note, callout, version)
        body = [QUOTE_MARK.sub("", line) for line in n.lines[start:end]]
        first = re.sub(r"^\[![A-Za-z][\w-]*\][-+]?.*$", "", body[0]).strip()   # the marker and the title go
        paragraph = ([first] if first else []) + body[1:]
        n.lines[start:end] = paragraph
        if not any(line.strip() for line in paragraph):
            _drop_blank_run(n.lines, start)
        return self.finish(Plan(f"App: adopt callout {callout + 1} ({note})"), n)

    def dismiss_callout(self, note: str, callout: int, version: str) -> Plan:
        n, start, end = self._callout(note, callout, version)
        del n.lines[start:end]
        _drop_blank_run(n.lines, start)
        return self.finish(Plan(f"App: dismiss callout {callout + 1} ({note})"), n)

    def edit_note(self, note: str, version: str, markdown: str) -> Plan:
        n = self.note(note, version)
        body = markdown.replace("\r\n", "\n")
        if not body.strip():
            raise EditError(422, "empty_text")
        n.lines = (body if body.endswith("\n") else body + "\n").split("\n")
        return self.finish(Plan(f"App: edit ({note})"), n)

    def quick_note(self, text: str, about: str | None = None, kind: str = "note") -> Plan:
        """A new Inbox note, the text verbatim. `about` names a note or a position ("<note>#<n>"); a "discuss
        later" mark (`kind` "discuss") may come without text when it is about something."""
        content = text.replace("\r\n", "\n")
        target = self._about(about) if about else None
        if not content.strip() and (kind != "discuss" or target is None):
            raise EditError(422, "empty_text")
        if content.strip():
            words = _first_words(content)
        else:
            words = _first_words(f"discuss {self.vault.notes[target[0]]['title']}", count=8, limit=60)
        stem = f"{self.today} {self.now:%H%M} {words}".strip()
        name, count = stem, 1
        used = {notefile.name_key(i).casefold() for i in self.vault.paths}
        while notefile.name_key(name).casefold() in used:
            count += 1
            name = f"{stem} {count}"
        path = f"Inbox/{name}.md"
        frontmatter = ["type: inbox", "status: new", f"created: {self.today}"]
        if kind == "discuss":
            frontmatter.append("kind: discuss")
        if target is not None:
            note_id, number = target
            if number is None:
                frontmatter.append(f"about: {_yaml_string(f'[[{note_id}]]')}")
            else:
                heading = pos.ACROSS_TOPICS if self.vault.notes[note_id]["type"] == "positions" else pos.MY_POSITION
                frontmatter += [f"about: {_yaml_string(f'[[{note_id}#{heading}]]')}", f"position: {number}"]
        body = (content if content.endswith("\n") else content + "\n") if content.strip() else ""
        what = "discuss later" if kind == "discuss" else "quick note"
        plan = Plan(f"App: {what} ({name})", created=[path], changed=[name])
        plan.files[path] = "---\n" + "\n".join(frontmatter) + "\n---\n" + body
        return plan

    def _about(self, about: str) -> tuple[str, int | None]:
        """(note id, position number or None) of a quick note's `about`: 404 when unknown, 409 when the position
        is gone."""
        if about in self.vault.paths:
            return about, None
        if "#" not in about:
            raise EditError(404, "unknown_note")
        n, _, k = self.position(about)
        return n.id, k

    def set_inbox_status(self, note: str, status: str) -> Plan:
        """Ticks an Inbox note off (`processed`) or back (`new`); the text stays as it is."""
        n = self.note(note)
        if self.vault.notes[note]["type"] != "inbox":
            raise EditError(422, "not_inbox")
        n.set_field("status", status, after=("type",))
        return self.finish(Plan(f"App: mark {status} ({note})"), n)


OPS = ("confirm_position", "reword_position", "change_position", "drop_position", "add_position", "set_confidence",
       "adopt_callout", "dismiss_callout", "edit_note", "quick_note", "set_inbox_status")


def apply(edit: dict, editor: Editor, *, require_versions: bool = False) -> Plan:
    """Run one edit (already checked against models.Edit) on the editor."""
    op = edit["op"]
    if op not in OPS:
        raise ValueError(f"unknown edit {op!r}")
    args = {k: v for k, v in edit.items() if k != "op"}

    def canonical(value: str) -> str:
        note, sep, number = value.rpartition("#")
        name = note if sep else value
        matches = [i for i in editor.vault.paths if notefile.name_key(i) == notefile.name_key(name)]
        if len(matches) > 1:
            raise EditError(409, "ambiguous_note")
        found = matches[0] if matches else name
        return f"{found}#{number}" if sep else found

    for field in ("note", "position", "about"):
        if args.get(field):
            args[field] = canonical(args[field])
    if "evidence" in args:
        args["evidence"] = [canonical(i) for i in args["evidence"]]
    target = args.get("note") or args.get("position") or args.get("about")
    if target:
        note_id = target.rpartition("#")[0] if "#" in target else target
        if note_id in editor.vault.paths:
            if args.get("version") is None and require_versions:
                raise EditError(428, "version_required")
            editor.note(note_id, args.get("version"))
    if op not in ("edit_note", "adopt_callout", "dismiss_callout"):
        args.pop("version", None)
    plan = getattr(editor, op)(**args)
    plan.reads = editor.reads
    return plan


# ── text rules ──
def _position_words(value: str) -> str:
    words = value.strip()
    if not words:
        raise EditError(422, "empty_text")
    if "\n" in words or "\r" in words or "→" in words or "**" in words:
        raise EditError(422, "position_one_line")
    return words


def _why(value: str) -> str:
    reason = " ".join(value.split())
    if not reason:
        raise EditError(422, "empty_why")
    return reason


def _yaml_string(value: str) -> str:
    """A double-quoted YAML string (JSON's quoting is valid YAML)."""
    return json.dumps(value, ensure_ascii=False)


def _first_words(text: str, count: int = 4, limit: int = 40) -> str:
    words = [FORBIDDEN_IN_NAMES.sub("", w) for w in text.split()]
    words = [w.strip(".") for w in words if w.strip(".")]
    out = ""
    for word in words[:count]:
        if len(out) + len(word) + 1 > limit and out:
            break
        out = f"{out} {word}".strip()
    return out[:limit].strip() or "note"


# ── line helpers ──
def _content_end(lines: list[str], span: tuple[int, int]) -> int:
    """After the section's last non-blank line."""
    end = span[1]
    while end > span[0] + 1 and not lines[end - 1].strip():
        end -= 1
    return end


def _append_section(lines: list[str], block: list[str]) -> None:
    while lines and not lines[-1].strip():
        lines.pop()
    lines += ["", *block, ""]


def _create_position_section(lines: list[str], title: str, line: str, across: bool) -> None:
    """`## My position` right after the summary box (or the title); Positions.md's list before "By topic"."""
    if across:
        by_topic = pos.section(lines, "By topic")
        if by_topic is not None:
            lines[by_topic[0]:by_topic[0]] = [f"## {title}", line, ""]
            return
    at = 0
    for i, current in enumerate(lines):
        if current.startswith("> [!summary]") or (current.startswith("# ") and at == 0):
            at = i + 1
            while at < len(lines) and lines[at].startswith(">"):
                at += 1
            if current.startswith("> [!summary]"):
                break
    block = [f"## {title}", line]
    if at < len(lines) and lines[at].strip():
        block.append("")
    lines[at:at] = ["", *block] if at > 0 else block


def _drop_blank_run(lines: list[str], at: int) -> None:
    """Remove a doubled blank line left where a block was taken out."""
    if 0 < at < len(lines) and not lines[at].strip() and not lines[at - 1].strip():
        del lines[at]
    elif at == len(lines) and at > 0 and not lines[at - 1].strip() and at > 1 and not lines[at - 2].strip():
        del lines[at - 1]
