# External PostgreSQL setup

This project now expects Docker Compose to connect to a PostgreSQL service running on the host machine. The app containers use `host.docker.internal:5432`, while tools running directly on the host, including pgAdmin, can use `127.0.0.1:5432`.

## 1) Start the host PostgreSQL service

On this workstation, PostgreSQL 16 is installed. Start and verify the default cluster:

```bash
sudo systemctl enable --now postgresql
sudo pg_ctlcluster 16 main start
pg_lsclusters
pg_isready -h 127.0.0.1 -p 5432
```

If `pg_lsclusters` shows the cluster as `down` and the data/config paths are owned by `nobody:nogroup`, repair ownership first:

```bash
sudo chown postgres:postgres /var/lib/postgresql /var/lib/postgresql/16
sudo chown -R postgres:postgres /var/lib/postgresql/16/main
sudo chown -R postgres:postgres /etc/postgresql/16/main
sudo chown root:postgres /var/log/postgresql
sudo chmod 700 /var/lib/postgresql/16/main
sudo chmod 1775 /var/log/postgresql
sudo systemctl restart postgresql
```

## 2) Create the app role and database

```bash
sudo -u postgres createuser --pwprompt price_tracker
sudo -u postgres createdb --owner=price_tracker price_tracker
```

Use the password you choose here as `POSTGRES_PASSWORD` in `.env`.

## 3) Allow Docker containers to reach host PostgreSQL

Edit `/etc/postgresql/16/main/postgresql.conf` and make PostgreSQL listen beyond localhost:

```conf
listen_addresses = '*'
```

Edit `/etc/postgresql/16/main/pg_hba.conf` and allow the Compose subnet:

```conf
host    price_tracker    price_tracker    172.30.0.0/24    scram-sha-256
```

Then restart PostgreSQL:

```bash
sudo systemctl restart postgresql
pg_isready -h 127.0.0.1 -p 5432
```

The Compose file pins the app network to `172.30.0.0/24` by default. If you change `DOCKER_SUBNET`, update `pg_hba.conf` to match.

## 4) Configure the app

Copy `.env.example` to `.env` and set at least:

```env
POSTGRES_DB=price_tracker
POSTGRES_USER=price_tracker
POSTGRES_PASSWORD=<password-you-created>
POSTGRES_HOST=host.docker.internal
POSTGRES_PORT=5432
DOCKER_SUBNET=172.30.0.0/24
AUTH_BOOTSTRAP_TOKEN=<choose-a-bootstrap-token>
```

For host-local commands, this URL is useful:

```env
DATABASE_URL=postgresql+psycopg://price_tracker:<password-you-created>@127.0.0.1:5432/price_tracker
```

Compose builds its own container-facing `DATABASE_URL` from the `POSTGRES_*` values.

## 5) Run migrations and start the stack

The `database-migrate` service runs automatically before the application services:

```bash
make docker-run
```

To rerun migrations without restarting everything:

```bash
make docker-migrate
```

To stop the app without stopping PostgreSQL:

```bash
docker compose stop price-tracker dashboard telegram-bot caddy
```

`make docker-stop` / `docker compose down` removes the containers and network, but it no longer deletes database data because PostgreSQL is outside Compose.

## 6) Connect with pgAdmin

Install pgAdmin desktop if you do not already have it:

```bash
sudo apt install curl ca-certificates gnupg
curl -fsS https://www.pgadmin.org/static/packages_pgadmin_org.pub \
  | sudo gpg --dearmor -o /usr/share/keyrings/packages-pgadmin-org.gpg
echo "deb [signed-by=/usr/share/keyrings/packages-pgadmin-org.gpg] https://ftp.postgresql.org/pub/pgadmin/pgadmin4/apt/noble pgadmin4 main" \
  | sudo tee /etc/apt/sources.list.d/pgadmin4.list
sudo apt update
sudo apt install pgadmin4-desktop
```

Register a server with:

- Host: `127.0.0.1`
- Port: `5432`
- Maintenance database: `price_tracker`
- Username: `price_tracker`
- Password: the `POSTGRES_PASSWORD` value

## 7) Optional backup from the old Compose PostgreSQL container

If the old `price-tracker-postgres` container is still running and contains data you want:

```bash
docker exec -i price-tracker-postgres \
  pg_dump -U price_tracker -d price_tracker -Fc \
  > price_tracker-before-external.dump
```

Restore it into the host database:

```bash
pg_restore -h 127.0.0.1 -U price_tracker -d price_tracker \
  --clean --if-exists price_tracker-before-external.dump
```

