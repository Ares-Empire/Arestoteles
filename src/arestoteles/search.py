"""`GET /search` (docs/API.md → Search): the vault's passages found by their words and by their meaning, best first.
No text is written by a model: every result is a passage as it stands, with its best sentence for the query.

- **Words** (`words.py`): BM25 with the app's folding. Answers from the moment the vault is built.
- **Meaning** (`meaning.py`): the query's and the passages' embeddings. A passage counts with its best part, the
  whole passage or one of its sentences (a table: one of its rows), so one fact in a long paragraph is found too.
  The passages are embedded in a background thread (kept on disk by text hash, `vectors.py`); until they are,
  answers are word matches with `"meaning": false`.
- **Ranking:** a passage's score is half how close it is in meaning (scaled from the model's floor to the query's
  closest passage) and half how much of the query's words it holds (BM25 over the query's total), plus a bonus when
  it holds every word, so those rank higher. This beat reciprocal rank fusion for every model compared
  (scripts/search_eval.py): rank fusion lets a weak word match (a title word) push a close passage down.
- `match` says which side found a result: "words" when it holds words of the query, "meaning" when it is among the
  `limit` passages closest in meaning, "both". `sentence` is the passage's sentence holding the most of the query's
  words, then the closest in meaning.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import numpy as np

from .meaning import release_memory
from .passages import Passage, passages
from .vectors import VectorCache, key
from .words import Hit, WordIndex, tokens

if TYPE_CHECKING:
    from .config import Settings
    from .index import Built
    from .meaning import Embedder

log = logging.getLogger("arestoteles")

MEANING = 0.5       # the meaning side's share of a score; the words have the rest
ALL_WORDS = 0.1     # added for a passage holding every word of the query
CHUNK = 64          # texts embedded between two looks at whether a newer vault is waiting


def context(passage: Passage) -> str:
    """Where a passage stands, for the model: the note's title and the heading above it."""
    if not passage.heading or passage.heading == passage.title:
        return passage.title
    return f"{passage.title} · {passage.heading}"


class SearchIndex:
    """One vault commit's passages: the word index at once, the vectors once the background worker sets them.

    The meaning side reads "units": each passage, followed by its sentences when it has more than one (a passage of
    one sentence is its own sentence). `starts[i]` is passage i's first unit."""

    def __init__(self, commit: str, found: list[Passage]):
        self.commit = commit
        self.passages = found
        self.words = WordIndex([(p.plain, p.heading or "", p.title) for p in found])
        units: list[tuple[str, str]] = []
        starts: list[int] = []
        for p in found:
            starts.append(len(units))
            units.append((context(p), p.plain))
            if len(p.sentences) > 1:
                units.extend((context(p), s) for s in p.sentences)
        self.units = units
        self.keys = [key(f"{c}\n{t}") for c, t in units]
        self.starts = np.array(starts, dtype=np.int64)
        self.vectors: np.ndarray | None = None      # (units, dims), set once, all at once

    @classmethod
    def of(cls, built: Built) -> SearchIndex:
        return cls(built.commit, passages(built.vault))

    def closeness(self, vector: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Each unit's and each passage's (its best unit's) cosine similarity to a query."""
        sims = self.vectors @ vector
        return sims, np.maximum.reduceat(sims, self.starts)

    def sentence(self, doc: int, hit: Hit | None, sims: np.ndarray | None) -> str:
        p = self.passages[doc]
        if len(p.sentences) == 1:
            return p.sentences[0]
        first = int(self.starts[doc]) + 1          # the sentences' units follow the passage's own
        forms = hit.words if hit else frozenset()

        def score(i: int) -> tuple[int, float, int]:
            held = len(forms.intersection(tokens(p.sentences[i])))
            return held, float(sims[first + i]) if sims is not None else 0.0, -i

        return p.sentences[max(range(len(p.sentences)), key=score)]


def rank(index: SearchIndex, query: str, vector: np.ndarray | None, limit: int,
         floor: float = 0.0) -> list[dict]:
    """The best `limit` passages for the query; `vector` is the query's embedding (None: words only), `floor` the
    model's similarity below which a passage is not close in meaning."""
    if not index.passages:
        return []
    scores = np.zeros(len(index.passages))
    hits = index.words.search(query)
    by_doc = {h.doc: h for h in hits}
    for h in hits:
        scores[h.doc] += (1 - MEANING) * h.share + (ALL_WORDS if h.complete else 0.0)
    sims = None
    close: set[int] = set()
    if vector is not None and index.vectors is not None:
        sims, best = index.closeness(vector)
        top = float(best.max())
        if top > floor:
            scores += MEANING * np.clip((best - floor) / (top - floor), 0.0, 1.0)
            close = {int(i) for i in np.argsort(-best, kind="stable")[:limit] if best[i] > floor}
    order = [int(i) for i in np.argsort(-scores, kind="stable")[:limit] if scores[i] > 0]
    results = []
    for doc in order:
        p = index.passages[doc]
        match = "both" if doc in by_doc and doc in close else "words" if doc in by_doc else "meaning"
        results.append({"note": p.note, "block": p.block, "item": p.item, "position": p.position,
                        "heading": p.heading, "text": p.text, "sentence": index.sentence(doc, by_doc.get(doc), sims),
                        "match": match})
    return results


class Search:
    """The search of the current vault. `update` (after each rebuild) makes the new word index at once and hands the
    embedding to a background thread; `query` answers from whatever is ready."""

    def __init__(self, load: Callable[[], Embedder | None], cache: Path | None = None, *, background: bool = True):
        self._load = load                    # called in the background until it gives a model
        self._cache = cache
        self._background = background
        self._embedder: Embedder | None = None
        self._index: SearchIndex | None = None
        self._pending: SearchIndex | None = None
        self._known: dict[bytes, np.ndarray] = {}   # the vectors of the last index made ready, by text hash
        self._working = False
        self._lock = threading.Lock()
        self._idle = threading.Event()
        self._idle.set()

    @classmethod
    def from_settings(cls, settings: Settings) -> Search:
        from . import meaning

        return cls(lambda: meaning.load(settings.search_model, settings.models, settings.search_threads),
                   settings.search_cache)

    @property
    def index(self) -> SearchIndex | None:
        return self._index

    @property
    def meaning(self) -> bool:
        """The meaning side is ready for the current vault."""
        index = self._index
        return index is not None and index.vectors is not None and self._embedder is not None

    def update(self, built: Built) -> None:
        index = SearchIndex.of(built)
        run_here = False
        with self._lock:
            if self._embedder is not None and all(k in self._known for k in index.keys):
                index.vectors = _stack(index.keys, self._known)   # nothing new to embed (e.g. a status edit)
            self._index = index
            if index.vectors is None:
                self._pending = index
                if not self._working:
                    self._working = True
                    self._idle.clear()
                    run_here = not self._background
                    if self._background:
                        threading.Thread(target=self._work, name="arestoteles-search", daemon=True).start()
        if run_here:
            self._work()

    def wait(self, timeout: float | None = None) -> bool:
        """Until the background work is done (for tests and scripts)."""
        return self._idle.wait(timeout)

    def query(self, query: str, limit: int) -> dict:
        index = self._index
        if index is None:
            raise LookupError("no vault indexed yet")
        embedder = self._embedder
        ready = index.vectors is not None and embedder is not None
        vector = None
        if ready and index.passages:
            try:
                vector = embedder.queries([query])[0]
            except Exception:   # a broken model must not break the search: the words still answer
                log.exception("embedding a query failed; answering with words only")
                ready = False
        results = rank(index, query, vector, limit, embedder.min_similarity if embedder else 0.0)
        return {"commit": index.commit, "meaning": ready, "results": results}

    # ── the background worker ──
    def _work(self) -> None:
        while True:
            with self._lock:
                index, self._pending = self._pending, None
                if index is None:
                    self._working = False
                    self._idle.set()
                    return
            try:
                self._embed(index)
            except Exception:
                log.exception("embedding the passages failed; the search answers with words only")

    def _embed(self, index: SearchIndex) -> None:
        if self._embedder is None:
            self._embedder = self._load()
            if self._embedder is None:
                return
        embedder = self._embedder
        started = time.perf_counter()
        have = {k: self._known[k] for k in index.keys if k in self._known}
        cache = VectorCache(self._cache / f"{embedder.id}.sqlite", embedder.fingerprint) if self._cache else None
        try:
            missing = [k for k in dict.fromkeys(index.keys) if k not in have]
            cached = cache.get(missing) if cache is not None and missing else {}
            have.update(cached)
            unit_of = dict(zip(index.keys, index.units, strict=True))
            todo = [k for k in missing if k not in have]
            for start in range(0, len(todo), CHUNK):
                if self._pending is not None:   # a newer vault waits: embed for that one (this work is kept)
                    return
                chunk = todo[start:start + CHUNK]
                fresh = dict(zip(chunk, embedder.passages([unit_of[k] for k in chunk]), strict=True))
                if cache is not None:
                    cache.put(fresh)
                have.update(fresh)
            if cache is not None:
                cache.keep(set(index.keys))
        finally:
            if cache is not None:
                cache.close()
        with self._lock:
            index.vectors = _stack(index.keys, have)
            self._known = dict(zip(index.keys, index.vectors, strict=True))
        if todo:
            release_memory()
        log.info("search: %d passages ready for meaning search in %.1f s (%d texts embedded, %d from the cache)",
                 len(index.passages), time.perf_counter() - started, len(todo), len(cached))


def _stack(keys: list[bytes], vectors: dict[bytes, np.ndarray]) -> np.ndarray:
    if not keys:
        return np.zeros((0, 1), dtype=np.float32)
    return np.stack([vectors[k] for k in keys]).astype(np.float32, copy=False)
