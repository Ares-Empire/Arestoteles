# Arestoteles

The province of Patrik's **Weltbild**: his Obsidian vault of topics, positions, mechanisms, events and questions
(repo `carlsenares/opinions`). Decided 2026-10-24 (`~/ares-empire/docs/ARESTOTELES-APP.md`); the trading bot that
lived here before is gone (git keeps its history).

Two parts:

- **The vault service** (`src/arestoteles/`): the server of the Arestoteles iPhone app. It keeps a clone of the
  vault, pulls it every minute, builds the whole index (notes with each block's place in the source, positions with
  their history, links and backlinks, glossary, a brief per topic, Inbox notes and "discuss later" marks), applies
  the app's edits by the vault's own rules, checked with the vault's own check, committed and pushed, and searches
  the vault's passages by their words and their meaning (a German question finds the English passage; a small
  embedding model on the CPU, no generated text). Contract: [`docs/API.md`](docs/API.md), samples in `docs/samples/`.
- **The website** arestoteles.de (`web/`, `webauth/`, the compose `web` service, `scripts/refresh_quotes.py`):
  unchanged, see [`docs/11-web-frontend.md`](docs/11-web-frontend.md).

## Run and test

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q
.venv/bin/python -m arestoteles.meaning fetch --dir models   # optional: the meaning model, for its own test
# against a copy of a vault, without fetching or pushing (the app routes need an Empire login):
ARESTOTELES_VAULT=/tmp/vault-copy ARESTOTELES_PULL=0 ARESTOTELES_PUSH=0 .venv/bin/python -m arestoteles
curl -s http://127.0.0.1:8099/api/arestoteles/health
```

Deploying (server, Caddy, Aresync, Aresus): [`deploy/README.md`](deploy/README.md).

## Files

| | |
|---|---|
| `CLAUDE.md` | Notes for Claude sessions: the layout, the rules, the website's operating notes. |
| `docs/API.md` | The contract (version 1) with the server's marked additions. |
| `docs/11-web-frontend.md` | The website's design brief. |
| `deploy/` | The systemd unit, the Aresync hook, the quotes timer and image, the website's TLS script. |
| `tests/fixtures/vault/` | A small made-up vault: it builds exactly `docs/samples/vault.json`. |
| `scripts/search_eval.py` | Compares meaning models for the search (queries in `tests/fixtures/search-queries.json`). |
