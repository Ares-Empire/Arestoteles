# Arestoteles — notes for Claude

The Weltbild province: the server of the **Arestoteles iPhone app** (`empire-ios/Arestoteles`) and the website
arestoteles.de. Read first: `~/ares-empire/EMPIRE.md` (the empire's map, "How we build apps"),
`~/ares-empire/docs/ARESTOTELES-APP.md` (why, and the settled decisions), `docs/API.md` (the contract; keep
`docs/samples/` valid when it changes), and the vault's own `CLAUDE.md` (its rules are what the edits apply).

## What it is

One Python process (`python -m arestoteles`, FastAPI + uvicorn on `127.0.0.1:8099`) on the server, as root:

- **Sync loop (60 s):** fetch the vault clone (`/var/lib/arestoteles/vault`), fast-forward or rebase app commits on
  top, push what waits, rebuild the index when the commit changed. A local commit that cannot be replayed is kept on
  a branch `arestoteles-app/conflict-<time>`; nothing is ever lost.
- **API:** `GET /vault` (the whole index, ETag = commit), `GET /notes/{id}/source`, `POST /edits`, `GET /health`.
  Login: the Empire token, service `arestoteles` (as Aresus).

## Layout

```
src/arestoteles/
  inline.py     wikilinks, resolution, Text       notefile.py  frontmatter, body, blob hash
  positions.py  position and history line rules  reader.py    one note file → Note (markdown-it-py + Obsidian)
  index.py      the whole Vault                   edits.py     every edit op, pure (files in, files out)
  check.py      the vault's check.rb              gitrepo.py   the git commands
  service.py    state, sync loop, edit flow       api.py       routes        auth.py  Empire login
  texts.py      English + German sentences        models.py    the contract as pydantic models
  config.py     settings from the environment     main.py      start
tests/   fixtures/vault/ (made up)   deploy/ (unit, Aresync hook, install steps)
```

## Rules

- **Patrik's vault is his.** The real vault (`~/Documents/Patrik Breeck/Weltbild`) is read only for development:
  never write to it, never copy its notes into this repo, a test or a log. `tests/test_real_vault.py` works on a
  temporary copy and prints and asserts counts only. The fixture vault and the samples are made up.
- Edits follow the vault's rules and live in `edits.py` with tests: positions keep bold, numbering, `→` links and
  Positions.md's embeds; changed or dropped views go to "How my view changed" (with `, position N` so they attach to
  their position); `updated` is set; quick notes are verbatim. The vault check's *new* errors undo an edit.
- Everything that touches the clone runs under the service's lock; tests use a temporary bare remote, never GitHub.
- Language: `~/ares-empire/docs/LANGUAGES.md`. All of the server's sentences are in `texts.py` (English and German);
  vault content and the check's own lines are never translated. Every answer sets `Content-Language`.
- No secrets in the repo: `.env` and `vault.env` are git-ignored; never log a token.

## Test and run

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q          # needs git and ruby; the real-vault test runs only on Patrik's Mac
ARESTOTELES_VAULT=/tmp/vault-copy ARESTOTELES_PULL=0 ARESTOTELES_PUSH=0 .venv/bin/python -m arestoteles
```

## The website (arestoteles.de)

- `web/` is the Claude-Design portal (zero-build React from CDN, `docs/11-web-frontend.md`), served by the compose
  `web` container (`python:3.12-alpine` running `webauth/server.py`, stdlib only), bound to `172.18.0.1:5180` for the
  shared `insureai_nginx` proxy, which holds the vhost and TLS (`deploy/enable-tls-arestoteles.sh`).
- Login gate: `AUTH_PASSWORD_HASH` (scrypt, `:`-delimited, made with `webauth/gen_password.py`) and
  `AUTH_SESSION_SECRET` in `.env`; the gate is active only when both are set. `SSO_SECRET` accepts the hub's hand-off
  tokens. Open paths: `/login`, `/logout`, `/brand/*`, `/favicon`.
- `web/` is mounted read-only, so a pulled change is live on reload; `webauth/server.py` needs the container
  recreated (the Aresync hook does it).
- `web/live.json` (git-ignored) is the watchlist feed: `arestoteles-quotes.timer` runs `scripts/refresh_quotes.py`
  every 15 min in the `arestoteles-app:latest` image (`deploy/quotes.Dockerfile`), read-only Alpaca market data,
  fail-closed (a failed refresh leaves the last file).
- The server checkout is `/opt/arestoteles` (`/root/Arestoteles` links to it); deploy steps in `deploy/README.md`.
