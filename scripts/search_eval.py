"""Compare meaning models for GET /search: hits@1 / hits@3, memory and query time.

    .venv/bin/python scripts/search_eval.py                       # every model fetched into ARESTOTELES_MODELS
    .venv/bin/python scripts/search_eval.py --models multilingual-e5-small-int8,jina-v2-base-de-int8
    .venv/bin/python scripts/search_eval.py --vault ~/Documents/Patrik\\ Breeck/Weltbild   # + the real vault, numbers only

Each model runs in its own process, so its memory is measured alone: "memory" is how much more the process holds
after loading the model, embedding the passages and answering the queries (now, and at its peak) than before the
model's libraries were imported (on Linux the resident size, on macOS the physical footprint, see `memory_mb`). Query time is one query's embedding plus the ranking, with the threads the
server uses (ARESTOTELES_SEARCH_THREADS, default 2).

The queries (tests/fixtures/search-queries.json) are about the made-up fixture vault: English and German, other words
than the note, figures, sources, terms, and three the vault cannot answer (they set each model's `min_similarity`).
"words" ranks by words alone, "meaning" by the model alone, "search" is what the route answers (both fused).

`--vault` adds tasks that need no hand-written queries, so nothing of that vault is read by a person or printed: each
glossary term in German (and in English) should find a passage of its "Where" note holding the English term, and each
summary box should find a passage of its own note. The vault is copied to a temporary folder first; only counts and
rates are printed.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "vault"
QUERIES = ROOT / "tests" / "fixtures" / "search-queries.json"


def memory_mb() -> tuple[float, float]:
    """(now, peak) of what the process holds. Linux: resident memory (what the server's limit is about). macOS: the
    physical footprint Activity Monitor shows (its resident size also counts the memory-mapped model file and pages
    the allocator keeps for reuse, so it says little)."""
    if sys.platform == "darwin":
        import re

        out = subprocess.run(["footprint", "-p", str(os.getpid())], capture_output=True, text=True).stdout

        def mb(label: str) -> float:
            m = re.search(label + r":?\s*([\d.]+)\s*(KB|MB|GB)", out)
            if m is None:
                return float("nan")
            return float(m[1]) * {"KB": 1 / 1024, "MB": 1, "GB": 1024}[m[2]]

        return mb("Footprint"), mb("phys_footprint_peak")
    now = int(subprocess.run(["ps", "-o", "rss=", "-p", str(os.getpid())], capture_output=True, text=True).stdout)
    return now / 1024, resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def where(p) -> tuple:
    return p.note, p.block, p.item, p.position


def targets(index, want: list[dict]) -> set[tuple]:
    found = {where(p) for w in want for p in index.passages if p.note == w["note"] and w["has"] in p.plain}
    if want and not found:
        raise SystemExit(f"a query's passage is not in the fixture: {want}")
    return found


def first_hit(order: list[tuple], wanted: set[tuple]) -> int | None:
    return next((n for n, w in enumerate(order, start=1) if w in wanted), None)


def rates(ranks: list[int | None]) -> dict:
    n = max(len(ranks), 1)
    return {"at1": sum(r == 1 for r in ranks if r) / n, "at3": sum(r <= 3 for r in ranks if r) / n,
            "mrr": sum(1 / r for r in ranks if r) / n, "n": len(ranks)}


def evaluate(index, tasks: list[tuple[str, set[tuple]]], embedder, timings: list[float] | None = None) -> dict:
    """tasks: (query, wanted passages). Ranks of the first wanted passage by words, by meaning and as searched."""
    from arestoteles.search import rank
    import numpy as np

    out = {"words": [], "meaning": [], "search": []}
    for query, wanted in tasks:
        words = [where(index.passages[i]) for i in (h.doc for h in index.words.search(query))]
        out["words"].append(first_hit(words, wanted))
        if embedder is None:
            continue
        started = time.perf_counter()
        vector = embedder.queries([query])[0]
        results = rank(index, query, vector, 30, embedder.min_similarity)
        if timings is not None:
            timings.append((time.perf_counter() - started) * 1000)
        best = index.closeness(vector)[1]
        meaning = [where(index.passages[i]) for i in np.argsort(-best, kind="stable")]
        out["meaning"].append(first_hit(meaning, wanted))
        out["search"].append(first_hit([(r["note"], r["block"], r["item"], r["position"]) for r in results], wanted))
    return {side: rates(ranks) for side, ranks in out.items() if ranks}


def vault_tasks(index, built) -> dict[str, list[tuple[str, set[tuple]]]]:
    """Tasks made from the vault's own structure (see the module's docstring)."""
    from arestoteles.passages import plain
    from arestoteles.words import fold

    tasks: dict[str, list] = {"glossary de→en": [], "glossary en→en": [], "summary→note": []}
    for term in built.vault["glossary"]:
        if not term["note"] or not term["german"] or fold(term["german"]) == fold(term["english"]):
            continue
        wanted = {where(p) for p in index.passages
                  if p.note == term["note"] and fold(term["english"]) in fold(p.plain)}
        if wanted:
            tasks["glossary de→en"].append((term["german"], wanted))
            tasks["glossary en→en"].append((term["english"], wanted))
    for note in built.vault["notes"]:
        wanted = {where(p) for p in index.passages if p.note == note["id"]}
        if note["summary"] and wanted:
            tasks["summary→note"].append((plain(note["summary"]), wanted))
    return tasks


def one(model: str, models: Path, threads: int, vault: Path | None) -> dict:
    """Everything for one model, in this process (run by `main` once per model)."""
    from arestoteles import search
    from arestoteles.index import build

    queries = json.loads(QUERIES.read_text(encoding="utf-8"))["queries"]
    index = search.SearchIndex.of(build(FIXTURE, "fixture", "-"))
    tasks = [(q["q"], targets(index, q["want"])) for q in queries if q["want"]]
    unanswerable = [q["q"] for q in queries if not q["want"]]
    if model == "words":
        return {"model": "words", "fixture": evaluate(index, tasks, None)}

    from arestoteles import meaning
    import numpy as np

    base = memory_mb()[0]
    started = time.perf_counter()
    embedder = meaning.load(model, models, threads)
    if embedder is None:
        raise SystemExit(f"{model}: not fetched into {models}")
    load_s = time.perf_counter() - started
    started = time.perf_counter()
    index.vectors = embedder.passages(index.units)
    embed_ms = (time.perf_counter() - started) * 1000 / max(len(index.units), 1)
    timings: list[float] = []
    embedder.queries(["warm up"])
    out = {"model": model, "size_mb": meaning.MODELS[model].size / 1e6, "load_s": load_s,
           "embed_ms_per_text": embed_ms, "units": len(index.units), "passages": len(index.passages),
           "fixture": evaluate(index, tasks, embedder, timings)}

    def top(query: str) -> float:
        return float(np.max(index.closeness(embedder.queries([query])[0])[1]))

    out["top1_answerable"] = sorted(top(q) for q, _ in tasks)
    out["top1_unanswerable"] = sorted(top(q) for q in unanswerable)

    if vault is not None:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                copy = Path(tmp) / "vault"
                shutil.copytree(vault, copy, symlinks=True,
                                ignore=shutil.ignore_patterns(".git", ".trash", ".obsidian", "workspace*.json"))
                real = build(copy, "real", "-")
            real_index = search.SearchIndex.of(real)
            started = time.perf_counter()
            real_index.vectors = embedder.passages(real_index.units)
            out["vault_embed_s"] = time.perf_counter() - started
            out["vault_units"] = len(real_index.units)
            out["vault_passages"] = len(real_index.passages)
            out["vault"] = {name: evaluate(real_index, t, embedder, timings) for name, t in
                            vault_tasks(real_index, real).items() if t}
        except Exception as e:   # only the exception's type: its message could hold the vault's words
            out["vault_error"] = type(e).__name__
    out["query_ms_median"] = statistics.median(timings)
    out["query_ms_max"] = max(timings)
    now, peak = memory_mb()
    out["rss_mb"], out["peak_mb"] = now - base, peak - base
    return out


def table(rows: list[dict]) -> str:
    lines = ["| model | files | memory (after / peak) | query (median / max) | words @1/@3 | meaning @1/@3 | "
             "search @1/@3 | search MRR |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        f = r["fixture"]
        w = f["words"]
        if r["model"] == "words":
            continue
        m, s = f["meaning"], f["search"]
        lines.append(f"| {r['model']} | {r['size_mb']:.0f} MB | +{r['rss_mb']:.0f} / +{r['peak_mb']:.0f} MB | "
                     f"{r['query_ms_median']:.0f} / {r['query_ms_max']:.0f} ms | {w['at1']:.0%} / {w['at3']:.0%} | "
                     f"{m['at1']:.0%} / {m['at3']:.0%} | {s['at1']:.0%} / {s['at3']:.0%} | {s['mrr']:.2f} |")
    n = rows[0]["fixture"]["words"]["n"] if rows else 0
    lines.append(f"\n{n} answerable queries on the fixture vault.")
    for r in rows:
        if r["model"] == "words":
            continue
        a, u = r["top1_answerable"], r["top1_unanswerable"]
        lines.append(f"- {r['model']}: loaded in {r['load_s']:.1f} s, {r['embed_ms_per_text']:.0f} ms per passage "
                     f"embedded; best similarity of answerable queries {min(a):.2f}–{max(a):.2f} (median "
                     f"{statistics.median(a):.2f}), of unanswerable ones {min(u):.2f}–{max(u):.2f}")
    if any("vault" in r for r in rows):
        lines += ["", "Real vault (counts and rates only):", "",
                  "| model | task | n | words @1/@3 | meaning @1/@3 | search @1/@3 |", "|---|---|---|---|---|---|"]
        for r in rows:
            for task, res in r.get("vault", {}).items():
                w, m, s = res["words"], res["meaning"], res["search"]
                lines.append(f"| {r['model']} | {task} | {w['n']} | {w['at1']:.0%} / {w['at3']:.0%} | "
                             f"{m['at1']:.0%} / {m['at3']:.0%} | {s['at1']:.0%} / {s['at3']:.0%} |")
        for r in rows:
            if "vault_embed_s" in r:
                lines.append(f"- {r['model']}: {r['vault_passages']} passages ({r['vault_units']} texts with the "
                             f"sentences) embedded in {r['vault_embed_s']:.1f} s")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--models", help="comma-separated ids (default: every model fetched)")
    parser.add_argument("--dir", type=Path, default=Path(os.environ.get("ARESTOTELES_MODELS",
                                                                          "/var/lib/arestoteles/models")))
    parser.add_argument("--threads", type=int, default=int(os.environ.get("ARESTOTELES_SEARCH_THREADS", 2)))
    parser.add_argument("--vault", type=Path, help="also the tasks made from this vault (numbers only)")
    parser.add_argument("--one", help=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true", help="print the raw numbers")
    args = parser.parse_args()
    if args.one:
        print(json.dumps(one(args.one, args.dir, args.threads, args.vault)))
        return 0

    from arestoteles.meaning import MODELS

    ids = args.models.split(",") if args.models else [m for m, s in MODELS.items() if s.present(args.dir / m)]
    if not ids:
        print(f"no model in {args.dir}: python -m arestoteles.meaning fetch --model <id> --dir {args.dir}")
        return 1
    rows = []
    for model in ids:
        command = [sys.executable, __file__, "--one", model, "--dir", str(args.dir), "--threads", str(args.threads)]
        if args.vault:
            command += ["--vault", str(args.vault)]
        done = subprocess.run(command, capture_output=True, text=True)
        if done.returncode != 0:   # with --vault, never show the output: it could hold the vault's words
            print(f"{model}: failed" + ("" if args.vault else f"\n{done.stderr[-2000:]}"), file=sys.stderr)
            continue
        rows.append(json.loads(done.stdout.strip().splitlines()[-1]))
    print(json.dumps(rows, indent=2) if args.json else table(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
