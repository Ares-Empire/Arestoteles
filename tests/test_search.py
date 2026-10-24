"""GET /search (docs/API.md → Search): the passages, the word side, the ranking, the background embedding and its cache,
the model files, and the route. Everything here runs with the fake meaning model (tests/fakes.py); the real model has
its own optional test (test_search_model.py)."""

from __future__ import annotations

import io
import json
import logging
import threading

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from arestoteles import meaning, search as search_module
from arestoteles.api import create_app
from arestoteles.meaning import ModelFile, ModelSpec, _batches, fetch, load
from arestoteles.models import SearchAnswer
from arestoteles.passages import passages, plain, split
from arestoteles.search import Search, SearchIndex, rank
from arestoteles.texts import text
from arestoteles.vectors import VectorCache, key
from arestoteles.words import WordIndex, fold

from conftest import APP, ROOT, SAMPLES, edit, note
from fakes import FakeEmbedder

BASE = "/api/arestoteles"
QUERIES = ROOT / "tests" / "fixtures" / "search-queries.json"


def where(result: dict) -> tuple:
    return result["note"], result["block"], result["item"], result["position"]


def ask(index: SearchIndex, query: str, limit: int = 12, words_only: bool = False) -> list[dict]:
    vector = None if words_only else FakeEmbedder().queries([query])[0]
    return rank(index, query, vector, limit, FakeEmbedder.min_similarity)


@pytest.fixture
def index(service) -> SearchIndex:
    assert service.search.meaning
    return service.search.index


# ── passages ──
def test_passages_of_the_notes_people_read(service):
    vault = service.current().vault
    found = passages(vault)
    assert {p.note for p in found}.isdisjoint({"Home", "Glossary", "2026-10-23 2110 discuss Printing press"})
    for p in found:   # each points at its block, under the heading above it
        block = note(vault, p.note)["blocks"][p.block]
        assert block["kind"] in ("paragraph", "quote", "list", "callout", "table", "positions")
        assert (p.item is not None) == (block["kind"] == "list")
        assert (p.position is not None) == (block["kind"] == "positions")
        headings = [b for b in note(vault, p.note)["blocks"][:p.block] if b["kind"] == "heading"]
        assert p.heading == (plain(headings[-1]["text"]) if headings else None)

    # Positions.md gives only its own positions; a topic's positions stand in its positions block
    assert [(p.position, p.block, p.heading, p.text) for p in found if p.note == "Positions"] == [
        ("Positions#1", 2, "Across topics", "Who controls the copies controls the argument.")]
    assert [p.position for p in found if p.note == "Printing press" and p.position] == ["Printing press#1",
                                                                                        "Printing press#2"]
    callout = next(p for p in found if p.note == "Printing press" and p.block == 7)
    assert callout.text.startswith("**A rival view** Elizabeth Eisenstein (*The Printing Press")
    assert callout.sentences == ("Elizabeth Eisenstein (The Printing Press as an Agent of Change, 1979) gives the "
                                 "press the leading role; Andrew Pettegree argues that pamphlets mattered more than "
                                 "books.",)
    table = next(p for p in found if p.note == "Spread of print" and p.block == 4)
    assert (table.item, table.text.split("\n")[0]) == (None, "City · First press")
    assert table.sentences == ("Mainz · 1450", "Venice · 1469", "Lyon · 1473")
    source = next(p for p in found if p.note == "Printing press" and p.heading == "Sources" and p.item == 1)
    assert source.text == "Andrew Pettegree, *Brand Luther*, 2015"
    assert source.plain == "Andrew Pettegree, Brand Luther, 2015"
    assert not any(p.plain.startswith("Part of") for p in found)   # a section page's line naming its overview
    two = next(p for p in found if p.note == "Printing press" and p.block == 3)
    assert two.sentences == ("Within fifty years of the Gutenberg Bible, presses ran in more than 250 European towns "
                             "(Druckorte).", "Print followed trade routes, not borders.")


@pytest.mark.parametrize("markdown,expected", [
    ("**Bold**, *italic* and `code`", "Bold, italic and code"),
    ("the [Gutenberg Bible](arestoteles://note/Gutenberg%20Bible) in Mainz", "the Gutenberg Bible in Mainz"),
    ("[Printing press, Wikipedia](https://en.wikipedia.org/wiki/Printing_(press))", "Printing press, Wikipedia"),
    ("snake_case stays, _this_ goes", "snake_case stays, this goes"),
    ("an escaped \\* and \\[bracket\\]", "an escaped * and [bracket]"),
    ("[not a link] here", "[not a link] here"),
])
def test_plain(markdown, expected):
    assert plain(markdown) == expected


@pytest.mark.parametrize("value,expected", [
    ("One. Two! Three?", ["One.", "Two!", "Three?"]),
    ("E.g. this is one. And this, i.e. that, too.", ["E.g. this is one.", "And this, i.e. that, too."]),
    ("A. Pettegree wrote it in 2015. It sold.", ["A. Pettegree wrote it in 2015.", "It sold."]),
    ("About 1.5 million copies. Then more.", ["About 1.5 million copies.", "Then more."]),
    ("ca. 1450 in Mainz.", ["ca. 1450 in Mainz."]),
    ("Really? yes, really.", ["Really? yes, really."]),
    ('He wrote "Stop." Then he left.', ['He wrote "Stop."', "Then he left."]),
    ("line one\nline two", ["line one", "line two"]),
    ("• first item\n• second item", ["first item", "second item"]),
    ("  ", []),
])
def test_sentences(value, expected):
    assert split(value) == expected


# ── words ──
def test_folding_like_the_app():
    assert fold("Handelsstädte") == "handelsstadte"
    assert fold("CAFÉ Straße") == "cafe strasse"


def test_word_forms():
    words = WordIndex([("the trading cities (Handelsstädte) of the Rhine", "", ""),
                       ("presses ran in more than 250 towns (Druckorte)", "", ""),
                       ("printers reprinted whatever sold", "", ""),
                       ("a press release from 2026", "", "")])

    def docs(query: str) -> list[int]:
        return sorted(h.doc for h in words.search(query))

    assert docs("Handelsstadte") == docs("HANDELSSTÄDTE") == [0]
    assert docs("Druck") == [1]                 # a beginning finds the compound
    assert docs("Druckorten") == [1]            # another ending of the same word
    assert docs("printing") == [2]              # the stem: print-ing, print-ers
    assert docs("Stadt") == [0]                 # inside a compound, weakly
    assert docs("press") == [1, 3]              # presses, press
    assert docs("20") == [] and docs("250") == [1]   # numbers only as they are
    assert docs("the") == [0]                   # small words count when there is nothing else
    assert docs("the Rhine") == [0] and docs("of the") == [0]


def test_all_words_and_share():
    words = WordIndex([("Monk and professor in Wittenberg", "", "Martin Luther"),
                       ("Luther's theses of 1517", "", "Reformation"),
                       ("Mainz · 1450", "Trade routes, not borders", "Spread of print"),
                       ("Print followed trade routes, not borders.", "1. How print spread", "Printing press")])
    hits = {h.doc: h for h in words.search("Luther Wittenberg")}
    assert hits[0].complete and not hits[1].complete   # a title word counts, with one in the passage's own text
    hits = {h.doc: h for h in words.search("trade routes")}
    assert hits[3].complete and not hits[2].complete   # its heading alone does not make a passage hold the words
    assert hits[3].score > hits[2].score
    assert all(0 < h.share <= 1 for h in hits.values())
    luther = words.search("Luther")[0].share
    assert words.search("Luther Eiffelturm")[0].share < luther   # a word no passage holds: only partly found


# ── ranking ──
def test_words_only_while_the_meaning_is_not_ready(index):
    results = ask(index, "Handelsstadte", words_only=True)
    assert [(where(r), r["match"]) for r in results] == [(("Spread of print", 2, None, None), "words")]
    assert results[0]["sentence"] == ("Printers went where paper, money and readers were: the trading cities "
                                      "(Handelsstädte) of the Rhine and northern Italy.")
    assert ask(index, "Bücher", words_only=True) == []


def test_a_german_word_finds_english_passages_by_meaning(index):
    results = ask(index, "Bücher")
    assert results and all(r["match"] == "meaning" for r in results)
    assert ("Reformation", 2, 0, None) in [where(r) for r in results[:3]]   # "pamphlets outsold books"


def test_passages_holding_every_word_rank_first_and_give_their_sentence(index):
    first = ask(index, "trade routes")[0]
    assert (where(first), first["match"]) == (("Printing press", 3, None, None), "both")
    assert first["heading"] == "1. How print spread"
    assert first["sentence"] == "Print followed trade routes, not borders."   # the sentence holding the words
    assert first["text"].startswith("Within fifty years of the [Gutenberg Bible](arestoteles://note/")


def test_positions_and_the_limit(index):
    results = ask(index, "Who controls the copies", limit=2)
    assert len(results) == 2
    assert results[0] == {"note": "Positions", "block": 2, "item": None, "position": "Positions#1",
                          "heading": "Across topics", "text": "Who controls the copies controls the argument.",
                          "sentence": "Who controls the copies controls the argument.", "match": "both"}
    assert len(ask(index, "print", limit=30)) > 12


def test_nothing_found_for_what_the_vault_does_not_hold(index):
    assert ask(index, "Eiffelturm") == []


def test_every_result_follows_the_contract(index):
    for query in ("print", "Bücher", "Wann endete die Reformation?", "1450"):
        SearchAnswer.model_validate({"commit": "a1b2c3d", "meaning": True, "results": ask(index, query)})


def test_the_comparison_queries_name_real_passages(index):
    """tests/fixtures/search-queries.json (scripts/search_eval.py) stays valid when the fixture changes."""
    queries = json.loads(QUERIES.read_text(encoding="utf-8"))["queries"]
    assert len(queries) >= 20
    assert {q["lang"] for q in queries} == {"en", "de"}
    for q in queries:
        for want in q["want"]:
            assert any(p.note == want["note"] and want["has"] in p.plain for p in index.passages), want


# ── the background embedding and its cache ──
def test_meaning_comes_when_the_passages_are_embedded(world):
    gate = threading.Event()
    service = world.service(world.search(FakeEmbedder(gate), background=True))
    waiting = service.search.query("Bücher", 12)
    assert (waiting["meaning"], waiting["results"]) == (False, [])
    words = service.search.query("Handelsstadte", 12)
    assert (words["meaning"], [r["match"] for r in words["results"]]) == (False, ["words"])
    gate.set()
    assert service.search.wait(10)
    ready = service.search.query("Bücher", 12)
    assert ready["meaning"] is True and ready["results"]
    assert ready["commit"] == service.current().commit


def test_embeddings_are_kept_by_text_hash(world):
    service = world.service()
    units = len(set(service.search.index.keys))
    assert world.embedder.embedded == units
    # a restart embeds nothing: everything comes from the cache on disk
    restarted = world.service()
    assert world.embedder.embedded == 0 and restarted.search.meaning
    # an edit re-embeds only what it changed: a reworded position is one passage
    client = TestClient(create_app(restarted))
    assert edit(client, op="reword_position", position="Printing press#2",
                text="Printers were traders first; they printed what sold.").status_code == 200
    assert world.embedder.embedded == 1 and restarted.search.meaning
    assert restarted.search.query("traders", 12)["results"][0]["position"] == "Printing press#2"
    # an edit that changes no passage needs no embedding at all, not even a background run
    assert edit(client, op="set_inbox_status", note="2026-10-22 0915 paper was the bottleneck",
                status="processed").status_code == 200
    assert world.embedder.embedded == 1 and restarted.search.meaning


def test_a_newer_vault_while_embedding_wins(world, monkeypatch):
    monkeypatch.setattr(search_module, "CHUNK", 4)
    gate = threading.Event()
    service = world.service(world.search(FakeEmbedder(gate), background=True))
    first = service.search.index
    world.laptop_commit("Library/Actors/Martin Luther.md", lambda t: t + "\nHe married Katharina von Bora.\n")
    service.sync()   # a new commit while the first is still being embedded
    second = service.search.index
    assert second is not first and second.commit != first.commit
    gate.set()
    assert service.search.wait(10)
    assert first.vectors is None and second.vectors is not None   # the old one was left for the new one
    assert service.search.query("Katharina", 12)["results"][0]["note"] == "Martin Luther"


def test_without_a_model_the_words_still_answer(world, caplog):
    service = world.service(Search(lambda: None, world.tmp / "search", background=False))
    answer = service.search.query("Handelsstadte", 12)
    assert answer["meaning"] is False and [r["note"] for r in answer["results"]] == ["Spread of print"]

    def broken():
        raise RuntimeError("bad model file")

    with caplog.at_level(logging.ERROR, logger="arestoteles"):
        service = world.service(Search(broken, None, background=False))
    assert service.search.query("Handelsstadte", 12)["meaning"] is False
    assert "embedding the passages failed" in caplog.text


def test_a_query_the_model_cannot_embed_answers_with_words(world, caplog):
    service = world.service()
    world.embedder.queries = lambda texts: (_ for _ in ()).throw(RuntimeError("broken"))
    with caplog.at_level(logging.ERROR, logger="arestoteles"):
        answer = service.search.query("Handelsstadte", 12)
    assert answer["meaning"] is False and answer["results"][0]["match"] == "words"


def test_vector_cache(tmp_path):
    path = tmp_path / "fake.sqlite"
    cache = VectorCache(path, "one")
    vectors = {key(f"text {n}"): np.full(3, n, dtype=np.float32) for n in range(3)}
    cache.put(vectors)
    got = cache.get([key("text 1"), key("unknown")])
    assert list(got) == [key("text 1")] and got[key("text 1")].tolist() == [1.0, 1.0, 1.0]
    assert cache.keep({key("text 0")}) == 2 and len(cache) == 1
    cache.close()
    assert len(VectorCache(path, "one")) == 1
    assert len(VectorCache(path, "two")) == 0   # another model (or its settings): emptied


# ── the model files ──
def test_batches_keep_to_the_token_budget():
    lengths = [10] * 40 + [300] * 10 + [2000]
    batches = _batches(list(range(len(lengths))), lengths)
    assert sum(len(b) for b in batches) == len(lengths)
    assert all(len(b) <= meaning.BATCH_TEXTS for b in batches)
    assert all(len(b) * max(lengths[i] for i in b) <= meaning.BATCH_TOKENS for b in batches if len(b) > 1)
    assert batches[-1] == [50]   # a long text runs alone


def _spec(content: bytes) -> ModelSpec:
    import hashlib

    file = ModelFile("onnx/model.onnx", hashlib.sha256(content).hexdigest(), len(content))
    return ModelSpec(id="tiny", repo="example/tiny", revision="0" * 40, model=file,
                     tokenizer=ModelFile("tokenizer.json", hashlib.sha256(b"{}").hexdigest(), 2))


def test_fetch_checks_every_file(tmp_path):
    served: dict[str, bytes] = {"/example/tiny/resolve/" + "0" * 40 + "/onnx/model.onnx": b"weights",
                                "/example/tiny/resolve/" + "0" * 40 + "/tokenizer.json": b"{}"}
    asked: list[str] = []

    def hub(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        return httpx.Response(200, content=served[request.url.path])

    spec = _spec(b"weights")
    folder = fetch(spec, tmp_path, io.StringIO(), httpx.Client(transport=httpx.MockTransport(hub)))
    assert (folder / "model.onnx").read_bytes() == b"weights" and spec.present(folder)
    fetch(spec, tmp_path, io.StringIO(), httpx.Client(transport=httpx.MockTransport(hub)))
    assert len(asked) == 2   # files already there and correct are not fetched again

    served["/example/tiny/resolve/" + "0" * 40 + "/onnx/model.onnx"] = b"tampered"
    (folder / "model.onnx").unlink()
    with pytest.raises(RuntimeError, match="expected 7 bytes"):
        fetch(spec, tmp_path, io.StringIO(), httpx.Client(transport=httpx.MockTransport(hub)))
    assert sorted(f.name for f in folder.iterdir()) == ["tokenizer.json"]   # no half or wrong file left


def test_load_without_files_or_with_an_unknown_model(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="arestoteles"):
        assert load("embeddinggemma-300m-q4", tmp_path) is None
        assert load("no-such-model", tmp_path) is None
        assert load("off", tmp_path) is None
    assert "python -m arestoteles.meaning fetch" in caplog.text


def test_every_model_is_pinned():
    for spec in meaning.MODELS.values():
        assert len(spec.revision) == 40
        assert all(len(f.sha256) == 64 and f.size > 0 for f in spec.files), spec.id
        assert "{text}" in spec.query and "{context}" in spec.passage and "{text}" in spec.passage
    from arestoteles.config import Settings
    assert Settings().search_model in meaning.MODELS


# ── the route ──
def test_the_route_answers_the_contract(client, service):
    answer = client.get(BASE + "/search", params={"q": "trade routes"}, headers=APP)
    assert answer.status_code == 200
    body = SearchAnswer.model_validate(answer.json())
    assert body.commit == service.repo.head(short=True) and body.meaning is True
    assert where(answer.json()["results"][0]) == ("Printing press", 3, None, None)
    assert len(body.results) <= 12
    assert len(client.get(BASE + "/search", params={"q": "print", "limit": "3"}, headers=APP).json()["results"]) == 3
    assert client.get(BASE + "/search", params={"q": "  print  ", "limit": "30"}, headers=APP).status_code == 200
    assert client.get(BASE + "/search", params={"q": "x" * 200}, headers=APP).status_code == 200


@pytest.mark.parametrize("language_", ["en", "de"])
@pytest.mark.parametrize("params,key", [
    ({}, "bad_query"), ({"q": ""}, "bad_query"), ({"q": "   "}, "bad_query"), ({"q": "x" * 201}, "bad_query"),
    ({"q": "print", "limit": "0"}, "bad_limit"), ({"q": "print", "limit": "31"}, "bad_limit"),
    ({"q": "print", "limit": "two"}, "bad_limit"), ({"q": "print", "limit": "-1"}, "bad_limit"),
    ({"q": "print", "limit": "1.5"}, "bad_limit"),
])
def test_bad_queries_in_both_languages(client, params, key, language_):
    answer = client.get(BASE + "/search", params=params, headers={**APP, "Accept-Language": language_})
    assert (answer.status_code, answer.json()) == (400, {"error": text(key).get(language_)})
    assert answer.headers["Content-Language"] == language_


@pytest.mark.parametrize("token,status,key", [(None, 401, "unauthenticated"), ("other-token", 403, "forbidden")])
def test_the_route_needs_the_login(client, token, status, key):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    answer = client.get(BASE + "/search", params={"q": "print"}, headers=headers)
    assert (answer.status_code, answer.json()) == (status, {"error": text(key).en})


def test_not_ready_before_the_vault(world):
    import shutil

    shutil.rmtree(world.vault)
    client = TestClient(create_app(world.service()))
    answer = client.get(BASE + "/search", params={"q": "print"}, headers=APP)
    assert (answer.status_code, answer.json()) == (503, {"error": text("not_ready").en})


def test_the_sample_points_at_the_sample_vault():
    """docs/samples/search.json follows the contract and every result is a passage of docs/samples/vault.json as it
    stands (the real model's answer itself is checked in test_search_model.py, when the model is there)."""
    sample = json.loads((SAMPLES / "search.json").read_text(encoding="utf-8"))
    SearchAnswer.model_validate(sample)
    vault = json.loads((SAMPLES / "vault.json").read_text(encoding="utf-8"))
    assert sample["commit"] == vault["commit"] and sample["meaning"] is True
    by_place = {(p.note, p.block, p.item, p.position): p for p in passages(vault)}
    assert sample["results"] and {r["match"] for r in sample["results"]} >= {"meaning"}
    for r in sample["results"]:
        p = by_place[where(r)]
        assert (r["heading"], r["text"]) == (p.heading, p.text) and r["sentence"] in p.sentences
