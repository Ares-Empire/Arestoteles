"""Write docs/samples/search.json: the server's answer for one query on the fixture vault (the made-up vault behind
docs/samples, with the sample vault's commit), through the same `Search` the route uses, with the real meaning model.

    .venv/bin/python -m arestoteles.meaning fetch --dir models      # once
    ARESTOTELES_MODELS=models .venv/bin/python scripts/make_search_sample.py

tests/test_search_model.py checks the sample is still the answer (when the model is there).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "vault"
SAMPLES = ROOT / "docs" / "samples"
QUERY = "Wie viele Bücher wurden bis 1500 gedruckt?"   # a figure, asked in German, written in English
LIMIT = 5


def answer() -> dict:
    from arestoteles import meaning
    from arestoteles.config import Settings
    from arestoteles.index import build
    from arestoteles.search import Search

    settings = Settings.from_env()
    commit = json.loads((SAMPLES / "vault.json").read_text(encoding="utf-8"))["commit"]
    search = Search(lambda: meaning.load(settings.search_model, settings.models, settings.search_threads),
                    background=False)
    search.update(build(FIXTURE, commit, "-"))
    if not search.meaning:
        raise SystemExit(f"the meaning model {settings.search_model} is not in {settings.models}")
    return search.query(QUERY, LIMIT)


def main() -> int:
    target = SAMPLES / "search.json"
    target.write_text(json.dumps(answer(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {target.relative_to(ROOT)} ({QUERY!r})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
