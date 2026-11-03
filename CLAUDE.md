# Arestoteles — notes for Claude

The Weltbild province: the server of the **Arestoteles iPhone app** (`empire-ios/Arestoteles`) and the website
arestoteles.de. Read first: `~/ares-empire/EMPIRE.md` (the empire's map, "How we build apps"),
`~/ares-empire/docs/ARESTOTELES-APP.md` (why, and the settled decisions), `docs/API.md` (the contract; keep
`docs/samples/` valid when it changes), and the vault's own `CLAUDE.md` (its rules are what the edits apply).

## What it is

One Python process (`python -m arestoteles`, FastAPI + uvicorn on `127.0.0.1:8099`) on the server, as root:

- **Sync loop (60 s):** fetch the vault clone (`/var/lib/arestoteles/vault`), fast-forward or rebase app commits on
  top, push what waits, rebuild the index when the commit changed. A local commit that cannot be replayed is kept on
  a unique branch `arestoteles-app/conflict-<time>[-<counter>]`; health stays unhealthy until it is reconciled.
- **API:** `GET /vault` (the whole index, ETag = commit), `GET /notes/{id}/source`, `POST /edits`, `GET /search`,
  `GET /health`. Login: the Empire token, service `arestoteles`, and the account must be the owner
  (`EMPIRE_ALLOWED_USERS` in `vault.env`; empty = nobody), as Aresus and Aresium.
- **Search:** each rebuild makes the passages' word index at once and embeds them in a background thread with the
  meaning model (EmbeddingGemma-300m 4-bit, ONNX Runtime on the CPU, files in `/var/lib/arestoteles/models`), kept on
  disk by text hash (`/var/lib/arestoteles/search`), so a pull re-embeds only what changed. Without the model files
  the search answers with words only (`"meaning": false`).

## Layout

```
src/arestoteles/
  inline.py     wikilinks, resolution, Text       notefile.py  frontmatter, body, blob hash
  positions.py  position and history line rules  reader.py    one note file → Note (markdown-it-py + Obsidian)
  index.py      the whole Vault                   edits.py     every edit op, pure (files in, files out)
  check.py      the vault's check.rb              gitrepo.py   the git commands
  transaction.py atomic writes, crash recovery and persisted edit dependencies
  service.py    state, sync loop, edit flow       api.py       routes        auth.py  Empire login
  texts.py      English + German sentences        models.py    the contract as pydantic models
  config.py     settings from the environment     main.py      start
  passages.py   what search finds (and sentences) words.py     word search: folding, BM25
  meaning.py    the meaning model (ONNX), fetch   vectors.py   embeddings on disk by text hash
  search.py     GET /search: the index, the ranking, the background embedding
tests/   fixtures/vault/ (made up)   linecheck.py (the Block.lines proof)   fakes.py (the fake meaning model)
scripts/ search_eval.py (compares meaning models)   make_search_sample.py (docs/samples/search.json)
deploy/  (unit, Aresync hook, install)
```

## Rules

- **Patrik's vault is his.** The real vault (`~/Documents/Patrik Breeck/Weltbild`) is read only for development:
  never write to it, never copy its notes into this repo, a test or a log. `tests/test_real_vault.py` works on a
  temporary copy and prints and asserts counts only. The fixture vault and the samples are made up.
- Edits follow the vault's rules and live in `edits.py` with tests: positions keep bold, numbering, `→` links and
  Positions.md's embeds; changed or dropped views go to "How my view changed" (with `, position N` so they attach to
  their position); `updated` is set; quick notes are verbatim (a "discuss later" mark or a note about a note or
  position only adds `kind: discuss`, `about`, `position` to the frontmatter; a drop moves `position` with the list,
  as it does the history). The vault check's *new* errors undo an edit.
- Every block and list item carries `lines`, its range in the source body (the app edits one paragraph with it).
  `tests/linecheck.py` proves the ranges on the fixture and (counts only) the real vault: keep it passing.
- Everything that touches the clone runs under the service's lock; tests use a temporary bare remote, never GitHub.
- Supplied note versions are always checked. `ARESTOTELES_REQUIRE_VERSIONS` defaults off for rollout: old
  unversioned structured edits and linked quick notes are accepted and logged once per kind. Deploy the server
  first, install the version-sending app, then enable the setting and restart to reject missing versions with 428.
  Free text/callout versions remain required. See `docs/API.md` and `docs/225-edit-safety.md`; the iPhone
  client must capture versions when drafts are created. Recovery journals and dependency records live in `.git`;
  never remove them or recovery refs to make a dirty checkout appear clean.
- Language: `~/ares-empire/docs/LANGUAGES.md`. All of the server's sentences are in `texts.py` (English and German);
  vault content and the check's own lines are never translated. Every answer sets `Content-Language`.
- No secrets in the repo: `.env` and `vault.env` are git-ignored; never log a token.
- Search: no model writes text, every result is a passage as it stands. The tests use `tests/fakes.py` (no
  download); only `tests/test_search_model.py` runs the real model, skipped without its files. A change to the
  ranking: run `scripts/search_eval.py` before and after (on the real vault it prints numbers only), and write
  `docs/samples/search.json` again (`scripts/make_search_sample.py`).

## Test and run

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q          # needs git and ruby; the real-vault test runs only on Patrik's Mac
.venv/bin/python -m arestoteles.meaning fetch --dir models     # the meaning model (git-ignored), for the model test
ARESTOTELES_VAULT=/tmp/vault-copy ARESTOTELES_PULL=0 ARESTOTELES_PUSH=0 ARESTOTELES_MODELS=models \
  ARESTOTELES_SEARCH_CACHE=/tmp/arestoteles-search .venv/bin/python -m arestoteles
.venv/bin/python scripts/search_eval.py --dir models          # compare the models (scripts/search_eval.py)
```

## The website (arestoteles.de)

- `web/` is the Claude-Design portal (zero-build React, `docs/11-web-frontend.md`; React, Babel and Lucide in
  `web/vendor/`, fonts in `web/fonts/`: nothing loads from another host), served by the compose
  `web` container (`python:3.12-alpine` running `webauth/server.py`, stdlib only), bound to `172.18.0.1:5180` for the
  host's Caddy (`/etc/caddy/Caddyfile`), which holds the vhost and TLS.
- Login gate: `AUTH_PASSWORD_HASH` (scrypt, `:`-delimited, made with `webauth/gen_password.py`) and
  `AUTH_SESSION_SECRET` in `.env`; the gate is active only when both are set. The access key is the only way in: the
  old `/sso` hand-off from the hub is gone (2026-10-25; its tokens named no account, so they could not be limited to
  the owner, and the hub stopped minting them on 2026-10-23). Open paths: `/login`, `/logout`, `/favicon.ico`, the login image and its fonts
  (`OPEN_PATHS`, exact paths only).
- `web/` is mounted read-only, so a pulled change is live on reload; `webauth/server.py` needs the container
  recreated (the Aresync hook does it).
- `web/live.json` (git-ignored) is the watchlist feed: `arestoteles-quotes.timer` runs `scripts/refresh_quotes.py`
  every 15 min in the `arestoteles-app:latest` image (`deploy/quotes.Dockerfile`), read-only Alpaca market data,
  fail-closed (a failed refresh leaves the last file).
- The server checkout is `/opt/arestoteles` (`/root/Arestoteles` links to it); deploy steps in `deploy/README.md`.
