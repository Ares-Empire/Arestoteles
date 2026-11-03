"""The contract's types (docs/API.md) as pydantic models: `Edit` parses requests; the others check answers in the
tests (the routes serve the built JSON directly, so a shape mismatch fails the tests, not a request)."""

from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

Confidence = Literal["solid", "my-read", "shaky"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── edits ──
class _Versioned(_Strict):
    # Accepted from new clients during rollout; the service can require them once old clients are updated.
    version: str | None = None


class ConfirmPosition(_Versioned):
    op: Literal["confirm_position"]
    position: str


class RewordPosition(_Versioned):
    op: Literal["reword_position"]
    position: str
    text: str


class ChangePosition(_Versioned):
    op: Literal["change_position"]
    position: str
    text: str
    why: str


class DropPosition(_Versioned):
    op: Literal["drop_position"]
    position: str
    why: str


class AddPosition(_Versioned):
    op: Literal["add_position"]
    note: str
    text: str
    evidence: list[str] = Field(default_factory=list)


class SetConfidence(_Versioned):
    op: Literal["set_confidence"]
    note: str
    confidence: Confidence


class AdoptCallout(_Strict):
    op: Literal["adopt_callout"]
    note: str
    callout: int
    version: str


class DismissCallout(_Strict):
    op: Literal["dismiss_callout"]
    note: str
    callout: int
    version: str


class EditNote(_Strict):
    op: Literal["edit_note"]
    note: str
    version: str
    markdown: str


class QuickNote(_Versioned):
    op: Literal["quick_note"]
    text: str
    about: Optional[str] = None                        # a note id, or a position id "<note>#<n>"
    kind: Literal["note", "discuss"] = "note"


class SetInboxStatus(_Versioned):
    op: Literal["set_inbox_status"]
    note: str
    status: Literal["new", "processed"]


Edit = Annotated[Union[ConfirmPosition, RewordPosition, ChangePosition, DropPosition, AddPosition, SetConfidence,
                       AdoptCallout, DismissCallout, EditNote, QuickNote, SetInboxStatus], Field(discriminator="op")]
EDIT = TypeAdapter(Edit)


# ── answers ──
Lines = Optional[tuple[int, int]]   # [start, end) in the note's source body; null for blocks the server makes up


class _Block(_Strict):
    lines: Lines


class Heading(_Block):
    kind: Literal["heading"]
    level: Literal[2, 3, 4]
    text: str
    anchor: str


class Paragraph(_Block):
    kind: Literal["paragraph"]
    text: str


class ListItem(_Strict):
    text: str
    depth: int
    lines: Lines


class ListBlock(_Block):
    kind: Literal["list"]
    ordered: bool
    items: list[ListItem]


class PositionsBlock(_Block):
    kind: Literal["positions"]
    ids: list[str]


class CalloutBlock(_Block):
    kind: Literal["callout"]
    style: Literal["claude", "shaky", "note"]
    title: Optional[str]
    text: str
    index: int


class Quote(_Block):
    kind: Literal["quote"]
    text: str


class Embed(_Block):
    kind: Literal["embed"]
    note: str
    anchor: Optional[str]


class Table(_Block):
    kind: Literal["table"]
    header: list[str]
    rows: list[list[str]]


class SectionLink(_Block):
    kind: Literal["section_link"]
    note: str


class Rule(_Block):
    kind: Literal["rule"]


Block = Annotated[Union[Heading, Paragraph, ListBlock, PositionsBlock, CalloutBlock, Quote, Embed, Table,
                        SectionLink, Rule], Field(discriminator="kind")]


class Callout(_Strict):
    index: int
    style: Literal["claude", "shaky"]
    title: Optional[str]
    text: str


class Term(_Strict):
    english: str
    german: str
    note: Optional[str]


class BriefSection(_Strict):
    title: str
    summary: str
    note: Optional[str]


class Counterpoint(_Strict):
    note: str
    title: Optional[str]
    text: str


class Shaky(_Strict):
    note: str
    text: str


class Brief(_Strict):
    positions: list[str]
    sections: list[BriefSection]
    counterpoints: list[Counterpoint]
    shaky: list[Shaky]
    terms: list[Term]
    questions: list[str]


class Inbox(_Strict):
    status: str
    kind: Literal["note", "discuss"]
    about: Optional[str]
    position: Optional[int]


class PartOf(_Strict):
    note: str
    section: int


class Event(_Strict):
    from_: Optional[int] = Field(alias="from")
    to: Optional[int]
    where: list[str]


class Note(_Strict):
    id: str
    path: str
    type: Literal["topic", "mechanism", "event", "actor", "question", "session", "inbox", "home", "positions",
                  "glossary"]
    title: str
    summary: Optional[str]
    confidence: Optional[Confidence]
    created: Optional[str]
    updated: Optional[str]
    tags: list[str]
    topic: Optional[str]
    part_of: Optional[PartOf]
    event: Optional[Event]
    led_to: list[str]
    links: list[str]
    backlinks: list[str]
    positions: list[str]
    callouts: list[Callout]
    blocks: list[Block]
    brief: Optional[Brief]
    inbox: Optional[Inbox]
    version: str


class HistoryEntry(_Strict):
    date: str
    text: str
    why: Optional[str]


class Position(_Strict):
    id: str
    note: str
    number: int
    text: str
    title: str
    draft: bool
    evidence: list[str]
    history: list[HistoryEntry]


class PositionGroup(_Strict):
    title: str
    note: str
    positions: list[Position]


class Home(_Strict):
    learn_next: list[str]


class Vault(_Strict):
    version: Literal[1]
    commit: str
    built: str
    notes: list[Note]
    positions: list[PositionGroup]
    glossary: list[Term]
    home: Home


class NoteSource(_Strict):
    id: str
    version: str
    markdown: str


class EditResult(_Strict):
    vault: Vault
    changed: list[str]
    pushed: bool
    warnings: list[str]


class Health(_Strict):
    ok: bool
    commit: str
    pulled: Optional[str]
    pushed: bool
    notes: int


class SearchResult(_Strict):
    note: str
    block: int
    item: Optional[int]
    position: Optional[str]
    heading: Optional[str]
    text: str
    sentence: str
    match: Literal["words", "meaning", "both"]


class SearchAnswer(_Strict):
    commit: str
    meaning: bool
    results: list[SearchResult]


class Conflict(_Strict):
    error: str
    current: Optional[Note]

