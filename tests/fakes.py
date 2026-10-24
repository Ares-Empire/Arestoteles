"""A made-up meaning model for the tests: deterministic, no download, no ONNX.

A text becomes counts of a few "concepts" (English and German words for the same thing are one concept), plus its
other words hashed into a few more dimensions, so a German question finds the English passage by its meaning, and a
query in other words finds its passage, as the real model does on the fixture vault.
"""

from __future__ import annotations

import threading
import zlib
from typing import Sequence

import numpy as np

from arestoteles.words import tokens

CONCEPTS: dict[str, tuple[str, ...]] = {
    "print": ("print", "press", "druck", "buchdruck"),
    "book": ("book", "buch", "bucher", "bibel", "bible", "copies", "exemplar"),
    "town": ("town", "city", "citie", "stadt", "stadte"),
    "money": ("money", "geld", "paper", "papier", "reader", "leser"),
    "reformation": ("reformation", "luther", "theses", "thesen"),
    "peace": ("peace", "frieden", "ended", "endete"),
    "teach": ("professor", "lehrte", "teacher", "lehrer"),
    "cheap": ("cheap", "billig", "cost", "kosten"),
}
HASHED = 64


def concept(word: str) -> int | None:
    for n, forms in enumerate(CONCEPTS.values()):
        if any(word.startswith(form) for form in forms):
            return n
    return None


class FakeEmbedder:
    id = "fake"
    fingerprint = "fake-1"
    min_similarity = 0.3

    def __init__(self, gate: threading.Event | None = None):
        self.gate = gate            # set: embedding may run (a test holds it to see the time before)
        self.embedded = 0           # passage texts embedded so far

    def _vector(self, text: str) -> np.ndarray:
        v = np.zeros(len(CONCEPTS) + HASHED, dtype=np.float32)
        for word in tokens(text):
            n = concept(word)
            if n is not None:
                v[n] += 1.0
            else:
                v[len(CONCEPTS) + zlib.crc32(word.encode()) % HASHED] += 0.3
        norm = np.linalg.norm(v)
        return v / norm if norm else v

    def queries(self, texts: Sequence[str]) -> np.ndarray:
        return np.stack([self._vector(t) for t in texts])

    def passages(self, texts: Sequence[tuple[str, str]]) -> np.ndarray:
        if self.gate is not None:
            self.gate.wait(10)
        self.embedded += len(texts)
        return np.stack([self._vector(t) for _, t in texts])
