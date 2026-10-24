# Deploying Arestoteles

Two parts on the empire's server, both from the checkout `/root/Arestoteles` (a symlink to `/opt/arestoteles`):

- **The vault service** (`arestoteles.service`, root): `python -m arestoteles` on `127.0.0.1:8099`, the API of the
  iPhone app (`docs/API.md`). It keeps its own clone of the vault (`carlsenares/opinions`) in
  `/var/lib/arestoteles/vault`, pulls every 60 s and pushes the app's edits. Caddy routes
  `https://www.ares-empire.de/api/arestoteles/*` to it. Needs PocketBase (`127.0.0.1:8090`) for the app's login, `git`,
  `ssh` and `ruby` (the vault's own check; without Ruby edits still work and say the check was skipped).
- **The website** arestoteles.de, unchanged: the compose `web` container (`webauth/server.py` serving `web/`) and the
  quote refresher (`arestoteles-quotes.timer`, below).

## First install of the vault service

```bash
# 1. The vault clone (done 2026-10-24): the deploy key /root/.ssh/weltbild_deploy (read + write) is used through the
#    host alias github-weltbild in /root/.ssh/config, so the clone needs no sshCommand setting.
install -d -m 700 /var/lib/arestoteles
git clone github-weltbild:carlsenares/opinions.git /var/lib/arestoteles/vault
git -C /var/lib/arestoteles/vault config user.name "Patrik Breeck (Arestoteles app)"
git -C /var/lib/arestoteles/vault config user.email "287037715+carlsenares@users.noreply.github.com"
ruby --version                                  # the check needs it (apt install ruby if missing)

# 2. The code: main with this branch merged
cd /root/Arestoteles && git pull --ff-only
python3 -m venv .venv && .venv/bin/pip install -q -e .   # editable: a pulled change needs only a restart

# 3. The unit
cp deploy/arestoteles.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now arestoteles.service
curl -s http://127.0.0.1:8099/api/arestoteles/health     # {"ok":true,"commit":"…","pulled":"…Z","pushed":true,"notes":…}
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8099/api/arestoteles/vault   # 401 without a token
journalctl -u arestoteles -n 20                          # "vault built at …: N notes, M unresolved link targets"
```

Settings (all optional; the defaults fit this server) go in `/root/Arestoteles/vault.env`: `ARESTOTELES_VAULT`
(`/var/lib/arestoteles/vault`), `EMPIRE_AUTH_URL` (`http://127.0.0.1:8090`), `HOST`/`PORT` (`127.0.0.1`/`8099`),
`ARESTOTELES_SYNC_INTERVAL` (60), `ARESTOTELES_PULL`/`ARESTOTELES_PUSH` (1; 0 turns fetching/pushing off),
`ARESTOTELES_RUBY` (`ruby`), `ARESTOTELES_TZ` (`Europe/Berlin`).

## Caddy

In `/etc/caddy/Caddyfile`, inside the `ares-empire.de, www.ares-empire.de` site, **before** the hub's catch-all, next
to the Aresus block:

```caddy
handle /api/arestoteles/* {
	reverse_proxy 127.0.0.1:8099
}
```

Then `caddy validate --config /etc/caddy/Caddyfile && systemctl reload caddy`, and from anywhere:
`curl -s https://www.ares-empire.de/api/arestoteles/health`.

## Updates (Aresync)

```bash
cp /root/Arestoteles/deploy/aresync-hook /root/aresync/hooks/Arestoteles && chmod +x /root/aresync/hooks/Arestoteles
grep REPOS /root/aresync/config        # "Arestoteles" must be listed, so Aresync pulls the checkout
```

After each pull of a new commit the hook reinstalls when `pyproject.toml` changed, restarts `arestoteles.service`,
and recreates the `web` container when `webauth/server.py` or `docker-compose.yml` changed (`web/` itself is live on
pull). The vault is not deployed by Aresync: the service pulls it itself.

## Aresus (the province becomes active)

Replace the `arestoteles` entry in `aresus/checks.yaml` (Aresus re-reads it without a restart):

```yaml
  - slug: arestoteles
    name: Arestoteles
    expect: active
    line:
      en: "{health.notes} notes · last pull {health.pulled|ago}"
      de: "{health.notes} Notizen · letzter Pull {health.pulled|ago}"
    checks:
      - unit: arestoteles.service
        name: Server
        name_de: Server
      - json: https://www.ares-empire.de/api/arestoteles/health
        id: health
        name: Vault API
        name_de: Vault-API
      - container: arestoteles-web-1
        name: Web container
        name_de: Web-Container
      - http: https://www.arestoteles.de/
        id: website
        status: [302, 200]
      - deploy: /root/Arestoteles
```

`/health` answers `ok: false` when pulls or pushes have failed for more than 10 minutes, so the json check turns the
province into an Issue then.

## Removing the trading bot (once, on the server)

What the old deploy files created (check what exists before removing):

```bash
# the three trading timers and their services
systemctl disable --now arestoteles-morning.timer arestoteles-main.timer arestoteles-postclose.timer
rm /etc/systemd/system/arestoteles-{morning,main,postclose}.{service,timer} && systemctl daemon-reload

# the Telegram bot and the database containers (compose services `bot` and `db`), and the ledger volume
docker exec arestoteles-db-1 pg_dump -U arestoteles arestoteles | gzip > /root/arestoteles-ledger-2026-10-24.sql.gz  # optional backup
docker stop arestoteles-bot-1 arestoteles-db-1 && docker rm arestoteles-bot-1 arestoteles-db-1
docker volume rm arestoteles_pgdata
```

Keep: the `web` container, `arestoteles-quotes.timer`/`.service`, the image `arestoteles-app:latest` (the quote
refresher runs in it) and the network `arestoteles_default`. In `/opt/arestoteles/.env` only the website's keys are still
used (`AUTH_PASSWORD_HASH`, `AUTH_SESSION_SECRET`, `SSO_SECRET`, `ALPACA_PAPER_KEY`, `ALPACA_PAPER_SECRET`); the trading
ones (`DATABASE_URL`, `TELEGRAM_*`, `ANTHROPIC_API_KEY`, `ARESIUM_API_TOKEN`, `EDGAR_USER_AGENT`, `FINNHUB_API_KEY`) can
go, as can the git-ignored `config/config.toml`, `data/` and `logs/` if present. The Telegram bot account itself
(BotFather) is Patrik's to delete.

## The website

- `docker compose up -d web` serves arestoteles.de; Caddy on the host (`/etc/caddy/Caddyfile`, since 2026-10-21)
  holds the vhost and TLS (`docs/11-web-frontend.md` describes the site). Login secrets come from `.env` (`.env.example`).
- The quote refresher: `deploy/systemd/arestoteles-quotes.{service,timer}` (every 15 min) runs
  `scripts/refresh_quotes.py` in the image `arestoteles-app:latest` and writes `web/live.json`. The script needs only
  `alpaca-py` and the two paper keys. To rebuild the image small (it was built from the old trading code):
  `docker build -t arestoteles-app:latest - < deploy/quotes.Dockerfile`, then `systemctl start arestoteles-quotes` and
  `journalctl -u arestoteles-quotes -n 5` ("wrote …/live.json (14 quotes …)").
