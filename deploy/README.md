# Deploying to the Hetzner host

Phase 1 target (docs/10): pollers run unattended for a week; risk engine green.
Server TZ must be `Europe/Berlin` (the timers assume it): `timedatectl set-timezone Europe/Berlin`.

## 1. First-time setup

```bash
# as root or a docker-capable user
git clone https://github.com/carlsenares/Arestoteles.git /opt/arestoteles
cd /opt/arestoteles

cp .env.example .env && chmod 600 .env
# fill in: ALPACA_PAPER_KEY/SECRET, TELEGRAM_BOT_TOKEN/CHAT_ID, EDGAR_USER_AGENT,
#          FINNHUB_API_KEY; ANTHROPIC_API_KEY stays empty until Phase 2.
# DATABASE_URL stays as in the example (compose-internal postgres).

cp config/config.example.toml config/config.toml   # tune only with care: [risk] is the enforcement layer

docker compose build
docker compose up -d db
docker compose run --rm app python -m arestoteles.db.migrate
docker compose up -d bot         # then send /status to the bot to verify
```

## 2. Smoke test by hand (before enabling timers)

```bash
docker compose run --rm app python -m arestoteles.runs.morning_sweep
# expect: runs row ok, events ingested; check via psql or /status
docker compose run --rm app python -m arestoteles.runs.main_run --force
docker compose run --rm app python -m arestoteles.runs.post_close --force   # needs Alpaca keys; sends the digest
```

## 3. Schedules (systemd timers)

```bash
cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now arestoteles-morning.timer arestoteles-main.timer arestoteles-postclose.timer
systemctl list-timers 'arestoteles-*'
```

| Timer | When (Berlin) | Run |
|---|---|---|
| arestoteles-morning | Mon–Fri 07:30 | `runs.morning_sweep` (ingest; no market gate) |
| arestoteles-main | Mon–Fri 13:30 | `runs.main_run` (market-gated via Alpaca clock) |
| arestoteles-postclose | Mon–Fri 22:15 | `runs.post_close` (market-gated; digest 22:15+) |

Weekly/monthly review timers arrive with Phase 2 (they need the AI pipeline).

## 4. Updating

```bash
cd /opt/arestoteles && git pull && docker compose build && \
  docker compose run --rm app python -m arestoteles.db.migrate && \
  docker compose up -d bot
```

## 5. Operations

- Kill switch: send `/halt` to the bot (every run checks the flag first); `/resume` clears.
- Logs: `journalctl -u arestoteles-main.service -n 100`; bot/db: `docker compose logs`.
- Failure policy: any failed stage ⇒ runs row `failed` + Telegram alert + no trades.
- Optional: add a healthchecks.io ping as `ExecStartPost` per service.
- Backups: `pgdata` volume holds the ledger — snapshot it (Hetzner volume snapshot or
  `docker compose exec db pg_dump -U arestoteles arestoteles | gzip > backup.sql.gz` via cron).
