"""The meaning side of search: a multilingual sentence-embedding model on the CPU through ONNX Runtime (no torch).

The model sits behind `Embedder` (texts in, unit vectors out); the server uses `OnnxEmbedder` on files in
`ARESTOTELES_MODELS/<model id>/`, fetched once by the deploy command (never during a request):

    python -m arestoteles.meaning fetch            # the model ARESTOTELES_SEARCH_MODEL names (config.py)
    python -m arestoteles.meaning check            # loads it, embeds a few sentences, prints the time and memory
    python -m arestoteles.meaning list             # the candidates scripts/search_eval.py compares

Every file is pinned to a Hugging Face commit and checked against its size and SHA-256. The tests use a fake embedder.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Sequence

import numpy as np

log = logging.getLogger("arestoteles")

BATCH_TOKENS = 2048   # tokens per run of the model: bounds the memory a batch needs (a long text runs alone)
BATCH_TEXTS = 32


class Embedder(Protocol):
    id: str                  # names its cache file
    fingerprint: str         # changes whenever its vectors would (a cache with another one is emptied)
    min_similarity: float    # below this a passage is not found by its meaning (each model has its own scale)

    def queries(self, texts: Sequence[str]) -> np.ndarray: ...     # (n, d) float32, each row of length 1

    def passages(self, texts: Sequence[tuple[str, str]]) -> np.ndarray: ...
        # (context, text): where the passage stands (the note's title and heading) and its words


@dataclass(frozen=True)
class ModelFile:
    path: str        # in the Hugging Face repo at `revision`; stored under its file name
    sha256: str
    size: int

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]


@dataclass(frozen=True)
class ModelSpec:
    id: str                          # the folder under ARESTOTELES_MODELS and the name in ARESTOTELES_SEARCH_MODEL
    repo: str
    revision: str
    model: ModelFile                 # the ONNX graph
    tokenizer: ModelFile
    extra: tuple[ModelFile, ...] = ()   # files the graph needs beside it (external weights)
    query: str = "{text}"                       # how the model wants a query written
    passage: str = "{context}\n{text}"          # and a passage, with where it stands
    max_length: int = 512
    pooling: str = "mean"            # "mean" over the tokens, or "output": the graph's own `sentence_embedding`
    min_similarity: float = 0.0
    license: str = ""
    notes: str = field(default="", compare=False)

    @property
    def files(self) -> tuple[ModelFile, ...]:
        return (self.model, self.tokenizer, *self.extra)

    @property
    def size(self) -> int:
        return sum(f.size for f in self.files)

    @property
    def fingerprint(self) -> str:
        """Changes whenever the vectors would: a cache made with another fingerprint is thrown away."""
        return "|".join([self.id, self.revision, self.model.sha256, self.query, self.passage, str(self.max_length),
                         self.pooling])

    def present(self, folder: Path) -> bool:
        return all((folder / f.name).is_file() and (folder / f.name).stat().st_size == f.size for f in self.files)


# The candidates compared in scripts/search_eval.py (results in docs/API.md → Search, deploy/README.md). Int8 builds:
# Xenova's `model_quantized.onnx` is quantized per channel with reduce_range, which is exact enough on every x86 CPU
# (also without AVX-512 VNNI) and on ARM.
MODELS: dict[str, ModelSpec] = {spec.id: spec for spec in (
    ModelSpec(
        id="multilingual-e5-small-int8", repo="Xenova/multilingual-e5-small",
        revision="761b726dd34fb83930e26aab4e9ac3899aa1fa78",
        model=ModelFile("onnx/model_quantized.onnx",
                        "f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193", 118308185),
        tokenizer=ModelFile("tokenizer.json",
                            "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39", 17082730),
        query="query: {text}", passage="passage: {context}\n{text}", min_similarity=0.78, license="MIT",
        notes="intfloat/multilingual-e5-small, int8"),
    ModelSpec(
        id="multilingual-e5-small", repo="Xenova/multilingual-e5-small",
        revision="761b726dd34fb83930e26aab4e9ac3899aa1fa78",
        model=ModelFile("onnx/model.onnx",
                        "4aa845c27760e06e9a686b9d8b5d440eae4b6612cd09e5b522b716d3941f77ff", 470268533),
        tokenizer=ModelFile("tokenizer.json",
                            "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39", 17082730),
        query="query: {text}", passage="passage: {context}\n{text}", min_similarity=0.78, license="MIT",
        notes="intfloat/multilingual-e5-small, float32"),
    ModelSpec(
        id="paraphrase-multilingual-minilm-int8", repo="Xenova/paraphrase-multilingual-MiniLM-L12-v2",
        revision="2c4055b12046f11709e9df2c122e59ffbdc2f900",
        model=ModelFile("onnx/model_quantized.onnx",
                        "66fc00f5f29afcaff34092e1bdd20008ca3918265a82fb9695a551e510cc4ebc", 118308126),
        tokenizer=ModelFile("tokenizer.json",
                            "b60b6b43406a48bf3638526314f3d232d97058bc93472ff2de930d43686fa441", 17082913),
        max_length=128, min_similarity=0.22, license="Apache-2.0",
        notes="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2, int8 (trained on 128 tokens)"),
    ModelSpec(
        id="jina-v2-base-de-int8", repo="jinaai/jina-embeddings-v2-base-de",
        revision="3f9eede875721714945b6a99a3198299243cf2be",
        model=ModelFile("onnx/model_quantized.onnx",
                        "b19a38d186594d9784e6a2c8954035a6928b5da1df402e7942d25021cf488b6b", 161565240),
        tokenizer=ModelFile("tokenizer.json",
                            "376c53a06d6911569afc19f584002a11dbcd6b871afb6d96b8600eb3c4e7e7a7", 2633554),
        min_similarity=0.25, license="Apache-2.0", notes="jinaai/jina-embeddings-v2-base-de (German-English), int8"),
    ModelSpec(
        id="embeddinggemma-300m-int8", repo="onnx-community/embeddinggemma-300m-ONNX",
        revision="5090578d9565bb06545b4552f76e6bc2c93e4a66",
        model=ModelFile("onnx/model_quantized.onnx",
                        "172efde319fe1542dc41f31be6154910b05b78f7a861c265c4600eec906bd6d8", 567874),
        extra=(ModelFile("onnx/model_quantized.onnx_data",
                         "705626e28e4c23c82ade34566b4197d97f534c12275fa406dfb71e9937d388c0", 308890624),),
        tokenizer=ModelFile("tokenizer.json",
                            "4dda02faaf32bc91031dc8c88457ac272b00c1016cc679757d1c441b248b9c47", 20323312),
        query="task: search result | query: {text}", passage="title: {context} | text: {text}", pooling="output",
        min_similarity=0.20, license="Gemma Terms of Use", notes="google/embeddinggemma-300m, int8"),
    ModelSpec(
        id="embeddinggemma-300m-q4", repo="onnx-community/embeddinggemma-300m-ONNX",
        revision="5090578d9565bb06545b4552f76e6bc2c93e4a66",
        model=ModelFile("onnx/model_q4.onnx",
                        "ad1dfee81a70f7944b9b9d1cc6e48075b832881cf33fab2f2b248be78f3f0043", 519322),
        extra=(ModelFile("onnx/model_q4.onnx_data",
                         "599962c3143b040de2dd05e5975be3e9091dd067cacc6a8f7186e3203bab9e02", 196725760),),
        tokenizer=ModelFile("tokenizer.json",
                            "4dda02faaf32bc91031dc8c88457ac272b00c1016cc679757d1c441b248b9c47", 20323312),
        query="task: search result | query: {text}", passage="title: {context} | text: {text}", pooling="output",
        min_similarity=0.20, license="Gemma Terms of Use", notes="google/embeddinggemma-300m, 4-bit"),
)}

class OnnxEmbedder:
    """A sentence-embedding model through ONNX Runtime: tokens → the graph → mean over the tokens → length 1."""

    def __init__(self, spec: ModelSpec, folder: Path, threads: int = 2):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.spec, self.id, self.fingerprint, self.min_similarity = spec, spec.id, spec.fingerprint, spec.min_similarity
        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, threads)
        options.inter_op_num_threads = 1
        options.enable_cpu_mem_arena = False      # memory goes back after a batch instead of staying reserved
        options.log_severity_level = 3
        self._session = ort.InferenceSession(str(folder / spec.model.name), options,
                                             providers=["CPUExecutionProvider"])
        self._inputs = {i.name for i in self._session.get_inputs()}
        outputs = [o.name for o in self._session.get_outputs()]
        self._output = outputs.index("sentence_embedding") if spec.pooling == "output" else 0
        self._tokenizer = Tokenizer.from_file(str(folder / spec.tokenizer.name))
        self._tokenizer.enable_truncation(spec.max_length)
        self._tokenizer.no_padding()
        pad = self._tokenizer.token_to_id("<pad>")
        self._pad = 0 if pad is None else pad

    def queries(self, texts: Sequence[str]) -> np.ndarray:
        return self._embed([self.spec.query.format(text=t) for t in texts])

    def passages(self, texts: Sequence[tuple[str, str]]) -> np.ndarray:
        return self._embed([self.spec.passage.format(context=c, text=t) for c, t in texts])

    def _embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        encodings = self._tokenizer.encode_batch(texts)
        order = sorted(range(len(texts)), key=lambda i: len(encodings[i].ids))   # little padding per batch
        rows: dict[int, np.ndarray] = {}
        for batch in _batches(order, [len(e.ids) for e in encodings]):
            width = max(len(encodings[i].ids) for i in batch)
            ids = np.full((len(batch), width), self._pad, dtype=np.int64)
            mask = np.zeros((len(batch), width), dtype=np.int64)
            for row, i in enumerate(batch):
                n = len(encodings[i].ids)
                ids[row, :n] = encodings[i].ids
                mask[row, :n] = 1
            feeds = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self._inputs:
                feeds["token_type_ids"] = np.zeros_like(ids)
            out = self._session.run(None, feeds)[self._output]
            if self.spec.pooling == "output":
                vectors = out
            else:
                weights = mask[:, :, None].astype(np.float32)
                vectors = (out * weights).sum(axis=1) / np.maximum(weights.sum(axis=1), 1e-9)
            for row, i in enumerate(batch):
                rows[i] = vectors[row]
        matrix = np.stack([rows[i] for i in range(len(texts))]).astype(np.float32)
        return matrix / np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)


def _batches(order: list[int], lengths: list[int]) -> list[list[int]]:
    """Texts sorted by length → runs of at most BATCH_TEXTS texts and BATCH_TOKENS tokens (padded), at least one."""
    batches: list[list[int]] = []
    batch: list[int] = []
    for i in order:
        if batch and (len(batch) == BATCH_TEXTS or (len(batch) + 1) * lengths[i] > BATCH_TOKENS):
            batches.append(batch)
            batch = []
        batch.append(i)
    if batch:
        batches.append(batch)
    return batches


def release_memory() -> None:
    """Hand the memory a big embedding run left free back to the system (glibc keeps it otherwise)."""
    if sys.platform.startswith("linux"):
        import ctypes

        try:
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except (OSError, AttributeError):
            pass


_reported: set[str] = set()


def load(model: str, models: Path, threads: int = 2) -> OnnxEmbedder | None:
    """The configured model, or None (meaning search off; the words still work) when it is unknown or not fetched."""
    def once(message: str, *args: object) -> None:
        if message not in _reported:
            _reported.add(message)
            log.warning(message, *args)

    if not model or model == "off":
        once("meaning search is off (ARESTOTELES_SEARCH_MODEL=%s)", model)
        return None
    spec = MODELS.get(model)
    if spec is None:
        once("meaning search is off: unknown model %s (known: %s)", model, ", ".join(MODELS))
        return None
    folder = models / spec.id
    if not spec.present(folder):
        once("meaning search is off: the model files are not in %s (python -m arestoteles.meaning fetch)", folder)
        return None
    started = time.perf_counter()
    embedder = OnnxEmbedder(spec, folder, threads)
    log.info("meaning model %s loaded in %.1f s", spec.id, time.perf_counter() - started)
    return embedder


# ── fetching (the deploy command) ──
def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(spec: ModelSpec, models: Path, out=sys.stdout, client=None) -> Path:
    """Download the model's files into `models/<id>/` (pinned commit, checked size and SHA-256); files already there
    and correct are kept. A failed download leaves no half file behind."""
    import httpx

    folder = models / spec.id
    folder.mkdir(parents=True, exist_ok=True)
    with client or httpx.Client(timeout=httpx.Timeout(60.0, connect=20.0), follow_redirects=True) as client:
        for f in spec.files:
            target = folder / f.name
            if target.is_file() and target.stat().st_size == f.size and sha256(target) == f.sha256:
                print(f"{f.name}: already there", file=out)
                continue
            url = f"https://huggingface.co/{spec.repo}/resolve/{spec.revision}/{f.path}"
            part = target.with_name(target.name + ".part")
            digest = hashlib.sha256()
            try:
                with client.stream("GET", url) as response, part.open("wb") as file:
                    response.raise_for_status()
                    for chunk in response.iter_bytes(1 << 20):
                        file.write(chunk)
                        digest.update(chunk)
                size = part.stat().st_size
                if size != f.size or digest.hexdigest() != f.sha256:
                    raise RuntimeError(f"{f.name}: got {size} bytes with SHA-256 {digest.hexdigest()}, "
                                       f"expected {f.size} bytes with {f.sha256}")
                os.replace(part, target)
            finally:
                part.unlink(missing_ok=True)
            print(f"{f.name}: {f.size / 1e6:.0f} MB fetched", file=out)
    return folder


def _rss_mb() -> float:
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / 1e6 if sys.platform == "darwin" else peak / 1e3   # bytes on macOS, kilobytes on Linux


def main(argv: list[str] | None = None) -> int:
    from .config import Settings

    settings = Settings.from_env()
    parser = argparse.ArgumentParser(prog="python -m arestoteles.meaning", description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["fetch", "check", "list"])
    parser.add_argument("--model", default=settings.search_model, help=f"default: {settings.search_model}")
    parser.add_argument("--dir", type=Path, default=settings.models, help=f"default: {settings.models}")
    args = parser.parse_args(argv)
    if args.command == "list":
        for spec in MODELS.values():
            mark = "*" if spec.id == args.model else " "
            print(f"{mark} {spec.id:38s} {spec.size / 1e6:5.0f} MB  {spec.license:20s} {spec.notes}")
        return 0
    spec = MODELS.get(args.model)
    if spec is None:
        print(f"unknown model {args.model}; known: {', '.join(MODELS)}", file=sys.stderr)
        return 2
    if args.command == "fetch":
        folder = fetch(spec, args.dir)
        print(f"{spec.id} ready in {folder} ({spec.size / 1e6:.0f} MB)")
        return 0
    before = _rss_mb()
    started = time.perf_counter()
    embedder = load(spec.id, args.dir, settings.search_threads)
    if embedder is None:
        print(f"{spec.id} is not in {args.dir / spec.id}: run `python -m arestoteles.meaning fetch` first",
              file=sys.stderr)
        return 1
    loaded = time.perf_counter() - started
    passages = embedder.passages([("Printing press", "Within fifty years presses ran in more than 250 towns."),
                                  ("Printing press", "Luther's pamphlets were cheap, short and in German.")])
    started = time.perf_counter()
    query = embedder.queries(["Wie viele Städte hatten eine Druckerpresse?"])[0]
    query_ms = (time.perf_counter() - started) * 1000
    print(f"{spec.id}: loaded in {loaded:.1f} s, a query embedded in {query_ms:.0f} ms, "
          f"similarities {passages @ query}, peak memory {_rss_mb():.0f} MB ({_rss_mb() - before:+.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
