# Price Tracker Operations Runbook

This document is a practical, current-state guide for running the app locally, running it in Docker, executing tests, deploying to a VPS, and validating Telegram bot workflows.

It is based on the repository as it exists today:

- `make run`, `make dashboard`, `make ready`, `make test`, and `make db-migrate` are defined in `Makefile`
- The Docker stack is defined in `docker-compose.yml`
- The app entrypoint is `src/app/main.py`
- The Telegram bot entrypoint is `src/app/bot/main.py`
- The deploy-time readiness CLI is `src/app/readiness.py`

## 1) Run locally

### Recommended local prerequisites

- Python 3.11 or newer
- A writable working copy
- Optional but recommended: a virtual environment

### Set up the environment

```bash
cd /home/ninad_p/workspaces/price_tracker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install
```

### Create a local config file

```bash
cp .env.example .env
```

Then edit `.env` with the values you actually want to use.

For a local SQLite setup, the default database path is:

```env
DATABASE_URL=sqlite:///./data/price_tracker.db
```

If you hit `attempt to write a readonly database`, point `DATABASE_URL` at a writable location such as `/tmp/price_tracker.db`, or fix the permissions on the `data/` directory.

### Initialize the database

```bash
make init
```

If you prefer the explicit Python one-liner, the Makefile target expands to a `python -c` call that imports `init_db()` from `app.database.db`.

### Start the app

```bash
PYTHONPATH=./src ./.venv/bin/python -m app.main
```

or:

```bash
make run
```

### Start the dashboard separately

```bash
PYTHONPATH=./src ./.venv/bin/python -m app.dashboard --host 0.0.0.0 --port 8000
```

or:

```bash
make dashboard
```

### Start the Telegram bot separately

```bash
PYTHONPATH=./src ./.venv/bin/python -m app.bot.main
```

If you are running the bot on its own outside Docker, set `TELEGRAM_REQUIRE_CHAT_ID=false` unless you also want to provide `TELEGRAM_CHAT_ID`.

Notes:

- The main app and dashboard can run from the same environment, but they are separate processes.
- The bot performs a live call to Telegram during startup, so it needs a real bot token and outbound network access.
- `make dev` currently runs the same command as `make run`; it does not add auto-reload yet.

## 2) Run via Docker

### What the compose stack currently starts

The current `docker-compose.yml` includes:

- `postgres`
- `price-tracker`
- `dashboard`
- `telegram-bot`
- `caddy`

### Minimal deployment flow

1. Copy the sample env file:

```bash
cp .env.example .env
```

2. Fill in the secrets and deployment settings:

```env
POSTGRES_PASSWORD=...
OPENAI_API_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
AUTH_BOOTSTRAP_TOKEN=...
CADDY_DOMAIN=your-domain.example
```

3. Build and start the stack:

```bash
make docker-build
make docker-run
```

4. Apply database migrations for the Postgres stack:

```bash
docker compose exec price-tracker python -m app.migrations upgrade head
```

5. Verify service status:

```bash
docker compose ps
docker compose logs -f
docker compose exec price-tracker python -m app.readiness --service all
```

### Docker notes

- `price-tracker` runs the scheduler and collectors.
- `dashboard` is only exposed internally and is proxied by Caddy.
- `telegram-bot` uses polling and only needs outbound access to Telegram.
- `TELEGRAM_REQUIRE_CHAT_ID=false` is set for the standalone bot container because it only needs the bot token.
- The Postgres volume is named `pgdata`.

### Choosing between local and Docker

Do one runtime path at a time unless you intentionally want to share the same database.

## 3) Manually run test cases

The repository already has `pytest` in the local virtualenv, and the safest way to run tests is with the same interpreter and `PYTHONPATH=./src`.

### Full suite

```bash
PYTHONPATH=./src ./.venv/bin/python -m pytest src/tests -v
```

### Unit tests only

```bash
PYTHONPATH=./src ./.venv/bin/python -m pytest src/tests/unit -v
```

### Integration tests only

```bash
PYTHONPATH=./src ./.venv/bin/python -m pytest src/tests/integration -v
```

### Recommended focused checks

Run the tests that cover the operational paths you just changed:

```bash
PYTHONPATH=./src ./.venv/bin/python -m pytest \
  src/tests/unit/test_dashboard_auth.py \
  src/tests/unit/test_telegram_bot_inputs.py \
  src/tests/unit/test_readiness.py \
  src/tests/unit/test_bot_runtime.py \
  src/tests/unit/test_auth_primitives.py \
  src/tests/unit/test_database_migration.py \
  -v
```

### Useful manual checks

- `PYTHONPATH=./src ./.venv/bin/python -m app.readiness --service all`
- `PYTHONPATH=./src ./.venv/bin/python -m app.dashboard --help`
- `PYTHONPATH=./src ./.venv/bin/python -m app.bot.main --help`

### Current caveat

In this workspace, the existing SQLite file in `data/` was not writable from the current user, so the readiness CLI failed until I pointed `DATABASE_URL` to a writable temp file. That means your local environment should use either:

- a writable `data/` directory, or
- a temp SQLite path, or
- Postgres through Docker

## 4) Deploy on a VPS

### Recommended topology

Use Docker Compose on an Ubuntu VPS:

- `postgres` for the database
- `price-tracker` for collectors and scheduler
- `dashboard` for the admin portal
- `telegram-bot` for user chat flows
- `caddy` for HTTPS and reverse proxying

This matches the current compose file and keeps the public surface area small.

### Provision the VPS

1. Provision an Ubuntu 22.04 or 24.04 VPS.
2. SSH in as a non-root user.
3. Update the machine:

```bash
sudo apt update
sudo apt upgrade -y
```

4. Install Docker Engine and the Compose plugin using Docker’s official Linux installation docs for Ubuntu, then verify:

```bash
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl status docker --no-pager
sudo docker run hello-world
```

5. Allow your non-root user to run Docker:

```bash
sudo groupadd docker || true
sudo usermod -aG docker "$USER"
newgrp docker
docker run hello-world
```

6. Install Git and a firewall:

```bash
sudo apt install -y git ufw
sudo ufw allow OpenSSH
sudo ufw allow 80
sudo ufw allow 443
sudo ufw enable
```

Note: Docker publishes container ports through its own networking layer, so keep the public port list small and only expose what you actually need.

### Deploy the code

```bash
sudo mkdir -p /opt/price_tracker
sudo chown "$USER":"$USER" /opt/price_tracker
cd /opt/price_tracker
git clone <your-repo-url> .
```

### Configure secrets

Create a private `.env` file or export the variables in your shell before running Compose.

At minimum, set:

```env
ENV=production
LOG_LEVEL=INFO
POSTGRES_PASSWORD=use-a-long-random-password
OPENAI_API_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
AUTH_BOOTSTRAP_TOKEN=use-a-long-random-bootstrap-token
CADDY_DOMAIN=tracker.example.com
```

Important operational notes:

- `AUTH_BOOTSTRAP_TOKEN` is only needed for first admin creation.
- After creating the first admin, remove or rotate `AUTH_BOOTSTRAP_TOKEN`.
- `CADDY_DOMAIN` controls whether Caddy serves `localhost` or your real domain.
- If you want the Telegram bot process only, it needs `TELEGRAM_BOT_TOKEN` but not `TELEGRAM_CHAT_ID` because `TELEGRAM_REQUIRE_CHAT_ID=false` is set in the bot service.

### Start the stack

```bash
make docker-build
make docker-run
```

If you prefer a single command on the server, you can also use:

```bash
docker compose up -d --build
```

### Run database migrations

```bash
docker compose exec price-tracker python -m app.migrations upgrade head
```

### Verify readiness

```bash
docker compose exec price-tracker python -m app.readiness --service all
docker compose ps
docker compose logs -f
```

### Bootstrap the first admin

1. Point your DNS record for `CADDY_DOMAIN` to the VPS IP.
2. Open the dashboard over HTTPS.
3. Visit:

```text
https://tracker.example.com/bootstrap
```

4. Create the first admin account using the bootstrap token.
5. Log in at:

```text
https://tracker.example.com/login
```

6. Remove or rotate `AUTH_BOOTSTRAP_TOKEN` after the first admin account exists.

### Production checks before sharing the server

- Confirm the dashboard loads only through Caddy.
- Confirm the dashboard accepts admin login and rejects regular users.
- Confirm the bot process is healthy and polling.
- Confirm `make ready` / readiness passes for the relevant services.
- Confirm Postgres data is on the `pgdata` volume or an equivalent backup-backed location.

### Backup reminder

Back up the `pgdata` volume regularly. A simple operational backup is a `pg_dump` run from the Postgres container or a snapshot from your VPS provider.

## 5) Communicate with the bot through Telegram

### Create the bot

1. Open Telegram and talk to `@BotFather`.
2. Create a bot with `/newbot`.
3. Copy the token into `TELEGRAM_BOT_TOKEN`.
4. Restart the `telegram-bot` service.

### What the bot accepts

The current bot UX is structured and command-driven:

- `/start` — register or refresh your Telegram profile
- `/help` — show the command guide
- `/status` — show uptime and your alert count
- `/add` — guided alert creation
- `/list` — list your alerts
- `/edit <id> key:value ...` — edit alert fields
- `/pause <id>` — disable an alert
- `/resume <id>` — re-enable an alert
- `/delete <id>` — remove an alert
- `/cancel` — abort the current flow

### How `/add` works

The bot asks for one value at a time:

1. product URL
2. brand
3. model name
4. alert title
5. platforms, such as `myntra, ajio`
6. sizes, such as `8, 8.5, 9`
7. optional notes
8. confirmation with `YES` or `NO`

The bot only accepts structured inputs here; it is not trying to interpret free-form natural language yet.

### How to ask other users to verify

1. Ask the person to open the bot in their own private Telegram chat.
2. Have them send `/start`.
3. Have them send `/help` and confirm the command list appears.
4. Have them send `/status` to confirm the bot responds.
5. In the dashboard, search for that Telegram user by name or Telegram ID and select them before creating a wishlist entry.
6. Have them try `/add` with a test product URL.
7. Have them send `/list` after creation to confirm the alert was stored.

### Verification advice for testers

- Use private chat, not a group, for the first verification pass.
- Tell each user to use their own Telegram account; the bot stores the Telegram user ID for scoping.
- Regular users can only interact through Telegram; they should not need dashboard access.
- The current cap is 5 active alerts per user.

### Bot startup caveat

The bot startup calls Telegram over the network during initialization. If the VPS cannot reach Telegram’s API or the token is invalid, the bot process will fail fast. That is expected and useful during deployment.

## 6) Practical notes worth keeping in mind

- The dashboard is admin-only.
- Regular users are Telegram-only.
- The scheduler and the bot are separate processes.
- The app currently uses Postgres in Docker and SQLite locally by default.
- `make dev` does not yet add live reload.
- `make ready` is a good preflight before exposing the VPS.
- If you are validating a deployment, check the logs and the readiness output before asking other people to test it.

## 7) Quick command summary

### Local

```bash
cp .env.example .env
make install
make init
make run
```

### Docker

```bash
make docker-build
make docker-run
docker compose exec price-tracker python -m app.migrations upgrade head
docker compose exec price-tracker python -m app.readiness --service all
```

### Tests

```bash
PYTHONPATH=./src ./.venv/bin/python -m pytest src/tests -v
```

### VPS

```bash
docker compose up -d --build
docker compose exec price-tracker python -m app.migrations upgrade head
docker compose exec price-tracker python -m app.readiness --service all
```
