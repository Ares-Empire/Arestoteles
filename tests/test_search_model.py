"""The real meaning model on the fixture vault: runs only where its files are (ARESTOTELES_MODELS, else ./models;
fetch them with `python -m arestoteles.meaning fetch --dir models`). CI and a fresh checkout skip it."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from arestoteles import meaning
from arestoteles.config import Settings
from arestoteles.index import build
from arestoteles.search import Search

from conftest import FIXTURE, ROOT, SAMPLES

MODELS = Path(os.environ.get("ARESTOTELES_MODELS", ROOT / "models"))
MODEL = Settings().search_model
SPEC = meaning.MODELS[MODEL]

pytestmark = pytest.mark.skipif(not SPEC.present(MODELS / SPEC.id), reason=f"the model {MODEL} is not in {MODELS}")


@pytest.fixture(scope="module")
def search() -> Search:
    search = Search(lambda: meaning.load(MODEL, MODELS), background=False)
    search.update(build(FIXTURE, json.loads((SAMPLES / "vault.json").read_text(encoding="utf-8"))["commit"], "-"))
    assert search.meaning
    return search


def test_the_comparison_queries(search):
    """The queries of scripts/search_eval.py: the passage that answers comes first (all of them when this was written,
    with a little room for another CPU's rounding), and a query the vault cannot answer finds nothing by meaning."""
    queries = json.loads((ROOT / "tests" / "fixtures" / "search-queries.json").read_text(encoding="utf-8"))["queries"]
    first = 0
    answerable = [q for q in queries if q["want"]]
    for q in answerable:
        top = search.query(q["q"], 3)["results"]
        assert any(r["note"] == w["note"] and w["has"] in _plain(search, r) for r in top for w in q["want"]), q["q"]
        first += any(top[0]["note"] == w["note"] and w["has"] in _plain(search, top[0]) for w in q["want"])
    assert first >= len(answerable) - 2
    for q in queries:
        if not q["want"]:
            assert all(r["match"] != "meaning" for r in search.query(q["q"], 12)["results"]), q["q"]


def test_the_sample_is_the_real_answer(search):
    sys.path.insert(0, str(ROOT / "scripts"))
    import make_search_sample

    sample = json.loads((SAMPLES / "search.json").read_text(encoding="utf-8"))
    assert search.query(make_search_sample.QUERY, make_search_sample.LIMIT) == sample


def _plain(search: Search, result: dict) -> str:
    p = next(p for p in search.index.passages
             if (p.note, p.block, p.item, p.position) == (result["note"], result["block"], result["item"],
                                                          result["position"]))
    return p.plain
