"""Patrik's real vault, read-only: runs only where it exists (his Mac). It is copied to a temporary folder first and
nothing is written to the original. Only counts are printed and asserted, never content (also not on failure)."""

from __future__ import annotations

import re
import shutil
import time
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from arestoteles import check
from arestoteles.api import create_app
from arestoteles.inline import Resolver
from arestoteles.models import SearchAnswer, Vault
from arestoteles.search import SearchIndex

from conftest import APP, World
from linecheck import check_note, problems

REAL = Path.home() / "Documents" / "Patrik Breeck" / "Weltbild"
LINK = re.compile(r"!?\[\[([^\[\]\n]+?)\]\]")
NUMBERED = re.compile(r"^\d+[.)] ")

pytestmark = pytest.mark.skipif(not REAL.is_dir(), reason="the real vault is only on Patrik's Mac")


@pytest.fixture(scope="module")
def copy(tmp_path_factory) -> Path:
    target = tmp_path_factory.mktemp("real") / "vault"
    shutil.copytree(REAL, target, symlinks=True, ignore=shutil.ignore_patterns(".trash", "workspace*.json"))
    return target


@pytest.fixture(scope="module")
def setup(copy, tmp_path_factory):
    world = World(tmp_path_factory.mktemp("world"))   # only for the fake login and the clock
    world.vault = copy
    failed = None
    service = None
    try:
        started = time.perf_counter()
        service = world.service(pull=False, push=False)
        build_ms = (time.perf_counter() - started) * 1000
    except Exception as e:   # only the exception's type may be shown
        failed, build_ms = type(e).__name__, 0.0
    assert failed is None
    return world, service, build_ms


def _numbered_lines(text: str, title: str) -> int:
    """An independent count of the numbered lines in a `## title` section."""
    count, inside = 0, False
    for line in text.split("\n"):
        if line.startswith("#"):
            inside = line.strip() == f"## {title}" or (inside and line.startswith("###"))
            continue
        if inside and NUMBERED.match(line):
            count += 1
    return count


def test_real_vault_builds(setup, copy):
    world, service, build_ms = setup
    built = service.current()
    vault = built.vault
    notes = vault["notes"]

    errors = 0
    try:
        Vault.model_validate(vault)
    except ValidationError as e:
        errors = e.error_count()
    assert errors == 0

    # every position found: the numbered lines of each "My position" (and Positions.md's "Across topics")
    missing_positions = 0
    for n in notes:
        text = (copy / n["path"]).read_text(encoding="utf-8").replace("\r\n", "\n")
        title = "Across topics" if n["type"] == "positions" else "My position"
        missing_positions += abs(_numbered_lines(text, title) - len(n["positions"]))
    in_groups = sum(len(g["positions"]) for g in vault["positions"])
    on_notes = sum(len(n["positions"]) for n in notes)
    assert missing_positions == 0
    assert in_groups == on_notes

    # every link resolved or reported
    resolve = Resolver(built.paths)
    resolved = reported = lost = absent = 0
    for n in notes:
        text = (copy / n["path"]).read_text(encoding="utf-8")
        for m in LINK.finditer(text):
            target = m[1].replace("\\|", "|").split("|")[0].split("#")[0].strip()
            if not target:
                continue
            note_id = resolve(target)
            if note_id is not None:
                resolved += 1
                absent += note_id != n["id"] and note_id not in n["links"]
            elif target in built.unresolved:
                reported += 1
            else:
                lost += 1
    assert lost == 0
    assert absent == 0

    client = TestClient(create_app(service))
    started = time.perf_counter()
    answer = client.get("/api/arestoteles/vault", headers=APP)
    request_ms = (time.perf_counter() - started) * 1000
    assert answer.status_code == 200
    assert request_ms < 1000
    assert build_ms < 1000

    result = check.run(copy)
    assert result.skipped is None

    print(f"\nREAL VAULT: {len(notes)} notes, {len(vault['positions'])} position groups, {on_notes} positions, "
          f"{sum(1 for n in notes if n['brief'])} briefs, {len(vault['glossary'])} glossary terms, "
          f"{sum(len(n['callouts']) for n in notes)} callouts, {sum(len(n['blocks']) for n in notes)} blocks")
    print(f"REAL VAULT: links {resolved} resolved, {reported} unresolved (reported, {len(built.unresolved)} distinct "
          f"targets), 0 lost; {len(built.duplicates)} duplicate names")
    print(f"REAL VAULT: build {build_ms:.0f} ms, GET /vault {request_ms:.0f} ms, {len(answer.content) // 1024} KB; "
          f"vault check {len(result.errors)} errors, {len(result.warnings)} warnings")


def test_real_vault_lines_round_trip(setup):
    """Every block and list item of every note: its lines lie in the source body, put back unchanged they give the
    identical body, and read again on their own they give the same block (tests/linecheck.py). Counts only."""
    world, service, _ = setup
    built = service.current()
    resolve = Resolver(built.paths)
    counts: Counter = Counter()
    for n in built.vault["notes"]:
        counts += check_note(n, service.source(n["id"])["markdown"], resolve)
    found = problems(counts)   # keys are the check's own words, never vault content
    print(f"\nREAL VAULT: lines of {counts['blocks']} blocks and {counts['items']} list items checked; problems: "
          + (", ".join(f"{key} {value}" for key, value in sorted(found.items())) or "none"))
    assert counts["blocks"] > 0
    assert sum(found.values()) == 0


def test_real_vault_edits_on_the_copy(setup, copy):
    """A few structured edits on the temporary copy (committed there only, never pushed): no new check errors, and a
    "discuss later" mark and its status pass the vault's own check without warnings."""
    world, service, _ = setup
    client = TestClient(create_app(service))
    groups = service.current().vault["positions"]
    topic = next((g for g in groups if g["note"] != "Positions" and len(g["positions"]) >= 2), None)
    assert topic is not None
    first, second = topic["positions"][0]["id"], topic["positions"][1]["id"]
    statuses, warnings, discuss = [], 0, None
    for body in ({"op": "change_position", "position": first, "text": "A made-up test view.", "why": "A test."},
                 {"op": "add_position", "note": topic["note"], "text": "Another made-up view.", "evidence": []},
                 {"op": "quick_note", "text": "", "kind": "discuss", "about": second},
                 {"op": "drop_position", "position": second, "why": "A test."},
                 {"op": "quick_note", "text": "a made-up test note"},
                 {"op": "set_inbox_status", "note": None, "status": "processed"}):
        if body["op"] == "set_inbox_status":
            body["note"] = discuss
        answer = client.post("/api/arestoteles/edits", json=body, headers=APP)
        statuses.append(answer.status_code)
        assert answer.status_code == 200
        assert answer.json()["pushed"] is False
        if body["op"] in ("quick_note", "set_inbox_status"):
            warnings += len(answer.json()["warnings"])
        if body.get("kind") == "discuss":
            discuss = answer.json()["changed"][0]
    after = next(g for g in service.current().vault["positions"] if g["note"] == topic["note"])
    assert len(after["positions"]) == len(topic["positions"])   # one added, one dropped
    assert len(after["positions"][0]["history"]) == len(topic["positions"][0]["history"]) + 1
    assert warnings == 0
    inbox = service.current().notes[discuss]["inbox"]
    follows = inbox["about"] == topic["note"] and inbox["position"] is None and inbox["status"] == "processed"
    assert follows   # the mark on the dropped position stays on its note (a bool, so no name is ever shown)
    print(f"\nREAL VAULT (copy): {len(statuses)} edits applied, statuses {sorted(set(statuses))}, "
          f"{warnings} new check warnings from the Inbox edits")


def test_real_vault_search(setup):
    """Search over the real vault with the fake meaning model: every passage points at its block, the index builds
    quickly, a query answers quickly. Counts and times only."""
    world, service, _ = setup
    built = service.current()
    started = time.perf_counter()
    index = SearchIndex.of(built)
    index_ms = (time.perf_counter() - started) * 1000
    misplaced = 0
    for p in index.passages:
        blocks = built.notes[p.note]["blocks"]
        misplaced += not (0 <= p.block < len(blocks)) or (p.item is not None and blocks[p.block]["kind"] != "list")
    assert misplaced == 0
    assert len(index.passages) > 0
    client = TestClient(create_app(service))
    assert service.search.meaning
    times = []
    for query in ("the", "Wie viele", "why did it happen", "1900"):   # made-up queries, results never shown
        started = time.perf_counter()
        answer = client.get("/api/arestoteles/search", params={"q": query}, headers=APP)
        times.append((time.perf_counter() - started) * 1000)
        assert answer.status_code == 200
        SearchAnswer.model_validate(answer.json())
    assert index_ms < 1000 and max(times) < 300
    print(f"\nREAL VAULT: {len(index.passages)} passages ({len(index.units)} texts with the sentences), search index "
          f"built in {index_ms:.0f} ms, a query answered in {max(times):.0f} ms at most (fake meaning model)")
