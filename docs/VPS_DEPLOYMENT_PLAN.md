# 🧭 VPS Deployment Plan — Excruciatingly Detailed

This is **not** a “just dockerize it and forget it” setup. For a VPS deployment, the work is split between **infrastructure**, **application hardening**, **observability**, and **operational runbooks**.

I’ve reviewed the current repo and the main current assumptions:

- The app is currently **single-process**, using the scheduler in `main.py`
- Containerization exists via `Dockerfile` and `docker-compose.yml`
- Secrets are currently handled via a local `.env` file
- The dashboard is currently a **local HTTP UI** and is **not authenticated**
- The app uses **SQLite**, which is fine for a POC, but it affects scaling and multi-agent design

---

## 1. Deployment Strategy Overview

### Recommended target architecture

#### Phase A — production-safe POC

Use **one container** on a VPS:

- `price-tracker` container
- Host-mounted SQLite DB volume
- Host-mounted logs volume
- Optional reverse proxy (Caddy or Nginx)
- Optional basic-auth protection for the dashboard
- Optional health checks and log rotation

#### Phase B — production hardening

Upgrade to:

- Dedicated app service
- Dedicated proxy service
- `promtail` / `vector` log shipping (optional)
- `watchtower` or manual image updates (optional)
- Remote kill switch script / automation

#### Phase C — multi-agent readiness

Only after the app is changed to support **distributed locking / job ownership**.

> Right now, do **not** run multiple app containers against the same SQLite DB. That will create race conditions and duplicate work.

---

## 2. Current Gaps You Need to Close Before VPS

### Security and correctness gaps

- Secrets are currently committed in `.env`
- This is a **high-risk issue**
- You must rotate:
  - Telegram bot token
  - OpenAI API key
- Remove `.env` from source control and stop copying it into the image
- The Docker image currently copies `.env`
- `Dockerfile` currently copies `.env`
- This is **not acceptable for production**
- The dashboard is not authenticated
- The dashboard is currently not safe to expose externally
- It must be protected behind auth if used remotely
- SQLite is a single-node data store
- Good for POC
- Not suitable for multi-agent or high-concurrency workloads
- There is no remote kill-switch implementation
- You need one operationally, even if it is just a scripted stop path
- There is no metrics endpoint
- Right now, you have logs but no Prometheus-style telemetry
- No structured operational runbook exists
- This plan will cover that

---

## 3. Recommended Deployment Topology

### Option 1 — simplest safe VPS deployment (recommended first)

Use:

- Docker Compose
- Single application container
- Caddy reverse proxy
- Host-mounted DB and logs
- Basic auth on dashboard endpoint
- Health check and log rotation
- SSH hardening and firewall

This is enough for a safe POC.

### Option 2 — “multi-agent” setup (not recommended until later)

If you want multiple containers:

- You need a shared database + lock mechanism
- You need a single scheduler owner or a distributed job queue
- Right now the app is not multi-agent safe

> Important: running multiple copies of the current scheduler against the same SQLite DB is **not safe**.

---

## 4. Containerization Plan

### Current state

The current `Dockerfile` is a good starting point, but it needs improvements.

#### Problems to fix

- Copying `.env` into image
- Installing Playwright browsers in image
- No non-root user
- No healthcheck for full app readiness
- No log rotation
- No security hardening

### Target container model

Your production image should ideally:

- Use a slim Python base
- Install only runtime dependencies
- Run as a non-root user
- Read secrets from environment variables or Docker secrets
- Mount:
  - `/app/data`
  - `/app/logs`
- Serve health status via a lightweight endpoint if you want probing
- Use `restart: unless-stopped`

### Recommended Dockerfile improvements

Future implementation should:

- Remove `.env` copy
- Install Playwright dependencies only if needed
- Create a non-root user
- Expose a health endpoint or use a script-based health check
- Use `ENTRYPOINT` or `CMD` only

---

## 5. Docker Compose Plan

### Minimum viable Compose for VPS

Use one app service and one reverse proxy.

You can later add other services.

#### Proposed services

- `price-tracker`
- `caddy` or `nginx`
- Optional `watchtower` or `uptime-kuma` later

#### Volumes

- `price_tracker_data`
- `price_tracker_logs`
- `caddy_data`
- `caddy_config`

#### Networks

- `tracker_net`

#### Important behavior

- Use `env_file` or Docker secrets
- Do **not** mount `.env` into the container
- Use host-side files or secrets for sensitive values

---

## 6. Sequence of Deployment Steps

### Phase 0 — Pre-flight hardening

Do this first on the VPS.

1. **Provision VPS**
   - Pick a KVM-based host with:
     - Ubuntu 22.04 or 24.04
     - At least 2 vCPU
     - 4 GB RAM
     - 20 GB disk
     - IPv4 and basic outbound access

2. **Create a non-root user**
   - Use a dedicated admin user, not root.

3. **Harden SSH**
   - Disable password auth
   - Disable root login
   - Require key-based auth
   - Use a non-default port if you want extra friction

4. **Install Docker and Compose**
   - Install `docker`, `docker compose`, and `curl`

5. **Install firewall**
   - Use `ufw`
   - Allow:
     - `22`
     - `80`
     - `443`
     - Optionally allow `8000` only locally, not externally

6. **Install fail2ban**
   - Protect SSH and proxy access

7. **Rotate secrets**
   - Rotate Telegram token and OpenAI key before doing anything else

### Phase 1 — Secrets and config prep

1. **Move secrets out of repo**
   - Remove the current `.env` from source control and stop committing it.

2. **Store secrets securely**
   - For the initial version, use:
     - environment variables in a host file outside the repo
     - or Docker secrets if you want a more production-like setup

3. **Define environment variables**
   - At minimum:
     - `ENV=production`
     - `LOG_LEVEL=INFO`
     - `DATABASE_URL=sqlite:///data/price_tracker.db`
     - `TELEGRAM_BOT_TOKEN`
     - `TELEGRAM_CHAT_ID`
     - `ENABLE_SCHEDULER=true`
     - `WATCHLIST_SCAN_INTERVAL_HOURS=1`
     - `PLAYWRIGHT_HEADLESS=true`

4. **Validate all variables**
   - No container should start if required secrets are missing.

### Phase 2 — Containerize and package

1. **Update Dockerfile**
   - Change:
     - remove `.env` copy
     - add non-root user
     - add healthcheck
     - optionally mount log dir
     - ensure Playwright is installed correctly

2. **Update `docker-compose.yml`**
   - Change:
     - remove `.env` mount
     - use `env_file` or secrets
     - add volumes for DB and logs
     - add restart policy
     - add resource limits optionally
     - add healthcheck
     - add `depends_on` if proxy is added

3. **Add Caddy or Nginx service**
   - If you want remote access:
     - Caddy is simpler
     - Nginx is more explicit
   - Use reverse proxy only if you need remote dashboard access or metrics access.

### Phase 3 — First VPS deployment

1. **Upload compose files**
   - Place them on the VPS

2. **Create secrets or env file**
   - For example:
     - `/opt/price-tracker/.env`
     - or Docker secrets

3. **Build image**
   - Use `docker compose build`

4. **Start the stack**
   - Use `docker compose up -d`

5. **Verify container health**
   - Check:
     - container is running
     - logs are healthy
     - DB file exists
     - scheduler is running

6. **Test the app end-to-end**
   - Test:
     - container health
     - app startup
     - dashboard accessibility via proxy
     - a manual watchlist scan
     - Telegram notification path if possible

### Phase 4 — Monitoring and observability

1. **Centralize logs**
   - Send container logs to:
     - stdout/stderr
     - host log files
     - optional log shipper later

2. **Add application health signals**
   - You want:
     - app process alive
     - scheduler running
     - DB writable
     - last successful scan timestamp
     - last Telegram send timestamp

3. **Add metrics**
   - A future step should include:
     - `scan_success_total`
     - `scan_failure_total`
     - `alerts_created_total`
     - `telegram_send_success_total`
     - `telegram_send_failure_total`
     - `watchlist_scan_duration_seconds`

4. **Set alerts**
   - Monitor:
     - container restarts
     - failed scans
     - failed alert sends
     - DB write errors
     - disk usage
     - memory usage
     - CPU usage

---

## 7. What to Monitor in Production

### Infrastructure monitoring

Monitor:

- CPU
- RAM
- disk usage
- container restarts
- Docker daemon health
- host uptime

### Application monitoring

Monitor:

- scheduler status
- latest watchlist scan timestamp
- latest scan success/failure
- alert creation count
- Telegram send success/failure
- DB write failures
- Playwright/browser failures
- scraping exceptions
- HTTP errors from target sites

### Business / operational monitoring

Monitor:

- number of active wishlist entries
- number of current alerts
- number of price drops detected
- size mismatches
- scan summary messages
- unexpected zero-product scans

---

## 8. Logging, Telemetry, and Observability Plan

### Current status

The app has logging in place, but:

- it is not yet fully centralized
- there is no metrics pipeline
- there is no structured operational dashboard

### Recommended observability stack

#### Minimal observability

- Structured logs to stdout
- Log rotation on host
- Healthcheck endpoint or health script
- Basic error alerts by email or Telegram

#### Better observability

- Prometheus + Grafana
- Loki or Vector for logs
- Alert rules for failures

### What to log

Structured fields for every run:

- `scan_type`
- `entry_count`
- `products_updated`
- `alerts_created`
- `errors`
- `telegram_sent`
- `telegram_failed`
- `duration_ms`

### What to expose

At minimum:

- `/health`
- `/metrics` if you add Prometheus metrics

---

## 9. Connectivity Plan

### Outbound connectivity requirements

The app needs outbound access to:

- target e-commerce sites
- Telegram API
- optionally OpenAI API if AI features are enabled
- DNS resolution

### Inbound connectivity requirements

You only need inbound access if:

- you expose the dashboard
- you expose metrics
- you expose a remote kill switch endpoint

### Recommended approach

Do **not** expose the app directly on port `8000`.

Instead:

- Expose only `443` on the reverse proxy
- Keep internal app port private
- Optionally protect access with basic auth

### Network hardening

- Allow only required ports
- Block all unnecessary inbound traffic
- Enable `ufw`
- Restrict Docker bridge if needed

---

## 10. Security and Auth Concerns

### Current security posture

Right now, the app is **not ready for internet-facing access** because:

- the dashboard is not protected
- secrets are in a file
- the container copies secrets into the image
- there is no explicit auth model

### Recommended authentication model

#### If you expose the dashboard

Use one of:

- Basic auth at the reverse proxy
- OAuth / SSO via proxy if needed
- mTLS if you want extra strength

#### If you do not expose dashboard

- Keep it internal-only and use SSH for admin work

### Secrets management

#### Initial phase

- Use a host file outside repo
- Never commit secrets
- Rotate them regularly

#### Later phase

- Use Docker secrets or a vault-like service
- Keep application secrets separate from source code

### Threat model to think about

- Credential leakage from `.env`
- Exposed dashboard
- Compromised bot token
- Malicious requests to admin endpoints
- Overly permissive firewall
- Accidental public exposure of internal container port

---

## 11. Login and Admin Access

### Recommended admin model

For now, I would treat the app as **operator-managed**, not user-authenticated.

That means:

- No public login flow for regular users
- Only operator access for monitoring and maintenance
- Dashboard access only behind auth

### Future enhancement options

- Add an admin login if you want a multi-user system
- Add role-based access
- Add audit logs for dashboard actions

> If you want this app to be more than a single-operator POC, those are worthwhile later.

---

## 12. Multi-Agent Setup Plan

### Important warning

The current app is **not safe for multi-agent deployment**.

#### Why

The app uses a scheduler and a shared SQLite DB.

Multiple containers running the same scheduler can:

- Duplicate work
- Create duplicate alerts
- Race on DB writes
- Produce inconsistent scan state

### What to do instead

#### For now

- Run **one app container only**

#### Later, if you want scale

Add:

- A distributed lock
- A job ownership mechanism
- A queue or background worker model
- Database migration away from SQLite

### Recommended future architecture

- `scheduler` container
- `worker` containers
- Shared Postgres
- Redis or queue service
- One leader election / lock service

> That is **not** the first thing you should build.

---

## 13. Remote Killswitch Plan

You asked for this explicitly, so here’s the recommended approach.

### Minimum viable remote kill switch

Use a single operational command that you can run from your local machine or a protected automation host:

```bash
ssh user@your-vps 'cd /opt/price-tracker && docker compose down'
```

That is the simplest “killswitch”.

### Better operational killswitch

Add a dedicated script:

- `kill-switch.sh`
- Stops the container
- Disables scheduler or disables the app at runtime
- Optionally writes a marker file

You can later add:

- A protected webhook
- Or an authenticated admin endpoint

### What I recommend for now

#### Level 1

- SSH access to the VPS
- Docker Compose stop command
- Documented runbook

#### Level 2

- Add a small operator command script
- Keep it in a locked directory
- Require SSH keys only

#### Level 3

- Add a protected admin endpoint or webhook
- Then the app can be shut down remotely without SSH

> Given your current app shape, I would **not** build a complex remote kill switch yet. Start with a scripted and documented stop path.

---

## 14. Exact Run Sequence to Follow

### Sequence A — initial VPS setup

1. Provision Ubuntu KVM VPS
2. Create non-root user
3. Harden SSH
4. Install Docker + Compose
5. Install UFW and fail2ban
6. Rotate secrets
7. Create deployment directory
8. Create compose file and env file
9. Build image
10. Start services
11. Verify health and logs
12. Test the Telegram path
13. Set up monitoring and alerting
14. Document the runbook

### Sequence B — first production deployment

1. Place `.env` outside repo
2. Update `Dockerfile` to remove `.env` copy
3. Update Compose to use `env_file` or secrets
4. Build container
5. Start container
6. Verify logs
7. Check database file exists
8. Verify scheduler is running
9. Trigger a manual test scan if possible
10. Verify Telegram delivery
11. Check dashboard access via proxy
12. Confirm firewall rules
13. Confirm backup path exists

### Sequence C — operators’ daily checklist

Each day:

1. Check container status
2. Check latest scan timestamp
3. Check latest Telegram delivery success
4. Check disk usage
5. Check CPU and memory
6. Review logs for exceptions
7. Review alerts and warnings

---

## 15. What to Back Up

At minimum:

- SQLite database file
- logs directory
- compose file
- secrets file or secret store config
- reverse proxy config
- any custom scripts

For a first POC:

- Daily automated backup of `price_tracker.db`
- Retain 7 to 14 days
- Store backups off-host if possible

---

## 16. Failure Modes You Should Plan For

### Expected failures

- Target site blocks or changes DOM/API payload
- Telegram API failure
- Playwright browser crash
- DB write failure
- Disk full
- Outbound network blocked
- Reverse proxy misconfig
- Docker image update issues

### Responses

- App should log and continue where possible
- Missing Telegram should not crash the app
- Scan failures should be visible in logs and monitoring
- Failed scans should not silently disappear

---

## 17. Recommended Implementation Roadmap

### Phase 1 — production-safe dockerization

- Remove `.env` from image
- Add non-root user
- Add healthcheck
- Add persistent DB/log volumes
- Add reverse proxy
- Add basic auth for dashboard
- Add log rotation

### Phase 2 — observability

- Add structured log fields for scan, alert, Telegram, and errors
- Add health endpoint or status reporter
- Add metrics endpoint
- Add monitoring alerts

### Phase 3 — security hardening

- Rotate secrets
- Remove sensitive file from repo
- Add firewall and fail2ban
- Add SSH hardening and backups
- Add remote kill switch script

### Phase 4 — scale readiness

- Move from SQLite to Postgres
- Add distributed lock or queue
- Only then consider multi-agent deployment

---

## 18. My Recommended “Do This First” Order

If you want to implement this one step at a time, I would do it in this order:

1. **Harden containerization**
   - Fix `Dockerfile`
   - Fix `docker-compose.yml`
   - Stop copying `.env`

2. **Add release-safe secrets management**
   - Remove sensitive file from repo
   - Rotate secrets
   - Use host env file or Docker secrets

3. **Add reverse proxy and auth**
   - Add Caddy/Nginx
   - Protect dashboard
   - Do not expose raw app port

4. **Add health and observability**
   - Add health checks
   - Add metrics
   - Add structured logs and retention

5. **Deploy to VPS**
   - Install Docker, firewall, fail2ban
   - Build and launch container
   - Validate scan + Telegram

6. **Add remote killswitch**
   - Script-based stop path
   - Document it in a runbook

7. **Only then consider multi-agent**
   - Migrate to Postgres
   - Add lock or queue
   - Then evaluate clustering

---

## 19. Practical Notes for Hostinger / KVM

For a KVM-based VPS like Hostinger:

- Assume you get full root or equivalent
- Verify Docker Engine is available
- Ensure outbound network is allowed
- Use `ufw` or host firewall
- Keep app data on a mounted volume or disk if possible
- Do not rely on ephemeral container storage for SQLite

---

## 20. What I Would Implement First in Code

If you want me to start implementing this in the repo, I recommend doing these in order:

1. **Remove `.env` from the image**
   - Update `Dockerfile` and `docker-compose.yml`

2. **Add a proper production compose profile**
   - App + reverse proxy + volumes

3. **Add HTTP health and metrics surface**
   - At minimum a `/health`
   - Ideally later `/metrics`

4. **Protect the dashboard**
   - Basic auth or proxy-level auth

5. **Add log rotation and environment validation**
   - Fail fast if required secrets are missing

6. **Add a kill-switch script and runbook**
   - Document the exact commands

7. **Only after that, evaluate multi-agent**
   - This needs a DB/locking redesign

---

## ✅ Bottom Line

For a simple POC on VPS, I would use:

- 1 container
- SQLite on a mounted volume
- Reverse proxy
- Basic auth for dashboard
- Sealed secrets
- Health checks
- Structured logs
- Remote stop script
- Firewall + fail2ban
- Tight outbound-only networking

The current repo is **close**, but **not production-safe yet**.

The biggest issues are:

- Secrets in `.env`
- `.env` being copied into the image via `Dockerfile`
- Dashboard not authenticated
- No explicit remote kill-switch
- No observability layer beyond logs
