"""Word search over the passages: BM25 with case and accent folding like the app's VaultSearch ("Handelsstadte"
finds "Handelsstädte").

A query word finds a passage's word when it is the same word, when the passage's word starts with it ("Druck" finds
"Druckorte", "press" finds "presses"), when both share the stem without a common ending ("printing" finds
"printers", "Druckorten" finds "Druckorte"), and, more weakly, when it stands inside a longer word ("Stadt" in
"Handelsstädte"). Numbers match only as they are. Small words ("the", "der", "wie") only count when the query has
nothing else.

Each passage is scored over its text, and more weakly over the heading it stands under and its note's title
("Luther Wittenberg" finds the passage "Monk and professor in Wittenberg" of the note "Martin Luther").
"""

from __future__ import annotations

import bisect
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

_WORD = re.compile(r"[^\W_]+")

K1, B = 1.2, 0.75
CONTEXT = 0.5      # weight of a heading's or title's words against the passage's own
WEAK = 0.4         # a word found inside a longer one
NEAR = 0.7         # a longer form or a shared stem

STOPWORDS = frozenset("""
    a an the of in on at to for from by with and or but nor is are was were be been being am do does did done
    what when where who whom whose which why how that this these those it its as than then there their they them
    he she his her i my me we our us you your not no so if into about after before can could would should will
    shall may might must has have had having any some many much more most very just also only
    der die das den dem des ein eine einen einem einer eines und oder aber ist sind war waren wird wurde wurden
    werden worden hat haben hatte hatten wie was wer wen wem wo wann warum wieso weshalb welche welcher welches
    im ins am an auf aus bei mit nach von vom vor zu zum zur fur uber unter um bis durch gegen ohne nicht kein
    keine es er sie ich mein meine wir uns ihr ihre sich dass als auch so viele viel noch schon nur man gab gibt
    denn doch ja nein sehr mehr dies diese dieser dieses jener jene
""".split())

# Endings taken off a query word to find the other forms of it (English and German); the longest that fits first.
_ENDINGS = ("ungen", "ings", "ing", "ies", "ied", "ers", "ern", "ung", "en", "er", "es", "ed", "em", "e", "s", "n")


def fold(text: str) -> str:
    """Lower case without accents or umlaut dots, so typing on any keyboard finds the words."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def tokens(text: str) -> list[str]:
    return _WORD.findall(fold(text))


def stem(word: str) -> str:
    for ending in _ENDINGS:
        if not word.endswith(ending) or (ending == "s" and word.endswith("ss")):
            continue
        rest = word[: -len(ending)]
        if ending in ("ies", "ied") and len(rest) >= 3:
            return rest + "y"
        if len(rest) >= 4:
            return rest
    return word


def query_words(query: str) -> list[str]:
    """The query's words that count: without the small words (unless there is nothing else), each once."""
    words = list(dict.fromkeys(tokens(query)))
    content = [w for w in words if w not in STOPWORDS]
    return content or words


@dataclass(frozen=True)
class Hit:
    doc: int
    score: float            # BM25
    share: float            # how much of the query it holds, 0–1: BM25 over the sum of the query words' IDF
    complete: bool          # holds every word of the query (the same word, a longer form or the stem), at least one
                            # in its own text: a heading alone does not make all its passages complete
    words: frozenset[str]   # the passage's words that matched (folded), for picking a sentence


class WordIndex:
    def __init__(self, docs: list[tuple[str, str, str]]):
        """`docs`: per passage (text, heading, title), plain text."""
        self.size = len(docs)
        self._postings: dict[str, list[tuple[int, float, bool]]] = {}   # word → (doc, weighted count, in its text)
        lengths: list[float] = []
        for doc, (text, heading, title) in enumerate(docs):
            own = Counter(tokens(text))
            counts: Counter[str] = Counter({word: float(n) for word, n in own.items()})
            length = float(sum(own.values()))
            for field in (heading, title):
                words = tokens(field)
                length += CONTEXT * len(words)
                for word in words:
                    counts[word] += CONTEXT
            lengths.append(length)
            for word, count in counts.items():
                self._postings.setdefault(word, []).append((doc, count, word in own))
        self._lengths = lengths
        self._average = (sum(lengths) / len(lengths)) if lengths else 1.0
        self._vocabulary = sorted(self._postings)

    def _forms(self, word: str) -> dict[str, float]:
        """The vocabulary's words a query word finds, with their weight."""
        forms: dict[str, float] = {}
        if word in self._postings:
            forms[word] = 1.0
        if any(c.isdigit() for c in word) or len(word) < 3:
            return forms
        longest = None if len(word) >= 5 else len(word) + 3   # short words: only their endings, not compounds
        for form in self._starting(word):
            if longest is None or len(form) <= longest:
                forms.setdefault(form, NEAR)
        root = stem(word)
        if root != word:
            for form in self._starting(root):
                if len(form) <= len(root) + 4:
                    forms.setdefault(form, NEAR)
        if len(word) >= 5:
            for form in self._vocabulary:
                if word in form:
                    forms.setdefault(form, WEAK)
        return forms

    def _starting(self, prefix: str) -> list[str]:
        start = bisect.bisect_left(self._vocabulary, prefix)
        out = []
        for form in self._vocabulary[start:]:
            if not form.startswith(prefix):
                break
            out.append(form)
        return out

    def search(self, query: str) -> list[Hit]:
        """Every passage holding at least one of the query's words, best first (BM25)."""
        words = query_words(query)
        scores: dict[int, float] = {}
        strong: dict[int, int] = {}
        in_text: set[int] = set()
        matched: dict[int, set[str]] = {}
        total = 0.0
        for word in words:
            forms = self._forms(word)
            tf: dict[int, float] = {}
            near: set[int] = set()
            for form, weight in forms.items():
                for doc, count, own in self._postings[form]:
                    tf[doc] = tf.get(doc, 0.0) + weight * count
                    matched.setdefault(doc, set()).add(form)
                    if weight >= NEAR:
                        near.add(doc)
                        if own:
                            in_text.add(doc)
            idf = math.log(1 + (self.size - len(tf) + 0.5) / (len(tf) + 0.5))
            total += idf   # a word no passage holds counts fully: the query is then only partly found
            if not tf:
                continue
            for doc, f in tf.items():
                norm = K1 * (1 - B + B * self._lengths[doc] / self._average)
                scores[doc] = scores.get(doc, 0.0) + idf * f * (K1 + 1) / (f + norm)
            for doc in near:
                strong[doc] = strong.get(doc, 0) + 1
        hits = [Hit(doc, score, min(1.0, score / total), strong.get(doc, 0) == len(words) and doc in in_text,
                    frozenset(matched[doc])) for doc, score in scores.items()]
        hits.sort(key=lambda h: (-h.score, h.doc))
        return hits
