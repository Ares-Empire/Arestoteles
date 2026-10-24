"""The whole vault → the contract's `Vault` (docs/API.md → Types): ids, links, backlinks, topics, positions, glossary,
briefs and Home's "To learn about next". Built from the files on disk; nothing here writes."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .inline import Resolver
from .reader import Parsed, read

log = logging.getLogger("arestoteles")


@dataclass
class Built:
    vault: dict
    body: bytes                                   # the Vault as JSON, served as it is
    notes: dict[str, dict]                        # id → Note
    paths: dict[str, str]                         # id → path inside the vault
    overviews: set[str]                           # topic overview ids
    unresolved: dict[str, list[str]] = field(default_factory=dict)   # link target → notes linking it
    duplicates: dict[str, list[str]] = field(default_factory=dict)   # note id → every path with that name

    @property
    def commit(self) -> str:
        return self.vault["commit"]

    def position(self, position_id: str) -> dict | None:
        for group in self.vault["positions"]:
            for p in group["positions"]:
                if p["id"] == position_id:
                    return p
        return None


def note_files(root: Path) -> list[str]:
    """Every note's path: all .md files except Templates/, CLAUDE.md and hidden folders (as the vault check)."""
    paths = []
    for file in root.rglob("*.md"):
        rel = file.relative_to(root).as_posix()
        if any(part.startswith(".") for part in PurePosixPath(rel).parts) or rel.startswith("Templates/"):
            continue
        if rel == "CLAUDE.md" or not file.is_file():
            continue
        paths.append(rel)
    return sorted(paths)


def build(root: Path, commit: str, built: str) -> Built:
    paths: dict[str, str] = {}
    duplicates: dict[str, list[str]] = {}
    for rel in note_files(root):
        note_id = PurePosixPath(rel).stem
        if note_id in paths:
            duplicates.setdefault(note_id, [paths[note_id]]).append(rel)
            continue
        paths[note_id] = rel
    resolve = Resolver(paths)
    parsed: dict[str, Parsed] = {note_id: read(rel, (root / rel).read_bytes(), resolve) for note_id, rel in paths.items()}
    notes = {note_id: p.note for note_id, p in parsed.items()}

    overviews = {note_id for note_id, rel in paths.items()
                 if notes[note_id]["type"] == "topic" and _overview_of(rel) == note_id}
    for note_id, rel in paths.items():
        folder = _overview_of(rel)
        notes[note_id]["topic"] = folder if folder in overviews else None

    for note_id in sorted(notes):
        for target in notes[note_id]["links"]:
            notes[target]["backlinks"].append(note_id)

    unresolved: dict[str, list[str]] = {}
    for note_id, p in parsed.items():
        for target in p.unresolved:
            unresolved.setdefault(target, []).append(note_id)

    glossary = _glossary(parsed)
    for note_id in overviews:
        notes[note_id]["brief"] = _brief(note_id, parsed, notes, glossary)

    vault = {
        "version": 1,
        "commit": commit,
        "built": built,
        "notes": [notes[note_id] for note_id in sorted(notes)],
        "positions": _groups(parsed, notes),
        "glossary": glossary,
        "home": {"learn_next": next((p.learn_next for p in parsed.values() if p.note["type"] == "home"), [])},
    }
    if duplicates:
        log.warning("duplicate note names (first path kept): %s", ", ".join(sorted(duplicates)))
    body = json.dumps(vault, ensure_ascii=False, separators=(",", ":")).encode()
    return Built(vault=vault, body=body, notes=notes, paths=paths, overviews=overviews,
                 unresolved=unresolved, duplicates=duplicates)


def _overview_of(rel: str) -> str | None:
    """The topic folder a path is in (Topics/<Topic>/…), or None outside Topics/."""
    parts = PurePosixPath(rel).parts
    return parts[1] if len(parts) >= 3 and parts[0] == "Topics" else None


def _groups(parsed: dict[str, Parsed], notes: dict[str, dict]) -> list[dict]:
    """Positions.md's "Across topics" first, then each topic it embeds, in the page's order. Topics with positions
    that the page does not embed yet (the vault check warns) follow, sorted by id, so no position is hidden."""
    groups: list[dict] = []
    page = parsed.get("Positions")
    if page is None:
        page = next((p for p in parsed.values() if p.note["type"] == "positions"), None)
    order: list[str] = []
    if page is not None:
        if page.positions:
            groups.append({"title": "Across topics", "note": page.note["id"], "positions": page.positions})
        for note_id, anchor in page.embeds:
            if (anchor or "").casefold() == "my position" and note_id not in order:
                order.append(note_id)
    order += sorted(note_id for note_id, p in parsed.items()
                    if p.positions and note_id not in order and (page is None or note_id != page.note["id"]))
    for note_id in order:
        if parsed[note_id].positions:
            groups.append({"title": notes[note_id]["title"], "note": note_id, "positions": parsed[note_id].positions})
    return groups


def _glossary(parsed: dict[str, Parsed]) -> list[dict]:
    page = parsed.get("Glossary") or next((p for p in parsed.values() if p.note["type"] == "glossary"), None)
    return sorted(page.terms, key=lambda t: t["english"].casefold()) if page else []


def _brief(overview: str, parsed: dict[str, Parsed], notes: dict[str, dict], glossary: list[dict]) -> dict:
    members = [overview] + sorted(n for n, note in notes.items() if note["topic"] == overview and n != overview)
    counterpoints, shaky, questions = [], [], []
    for member in members:
        for callout in notes[member]["callouts"]:
            if callout["style"] == "claude":
                counterpoints.append({"note": member, "title": callout["title"], "text": callout["text"]})
            else:
                shaky.append({"note": member, "text": callout["text"]})
        for target in notes[member]["links"]:
            if notes[target]["type"] == "question" and target not in questions:
                questions.append(target)
    return {
        "positions": notes[overview]["positions"],
        "sections": parsed[overview].sections,
        "counterpoints": counterpoints,
        "shaky": shaky,
        "terms": [t for t in glossary if t["note"] is not None and notes[t["note"]]["topic"] == overview],
        "questions": questions,
    }
