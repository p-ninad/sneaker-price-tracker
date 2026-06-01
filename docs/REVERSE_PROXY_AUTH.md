# Reverse Proxy and Authentication Setup

This document explains how the reverse proxy (Caddy) and dashboard authentication work in the Price Tracker application.

## Overview

The Price Tracker uses a **Caddy reverse proxy** to protect and route access to the dashboard:

- **Dashboard service**: Runs on `price-tracker-dashboard:8000` (internal, not exposed)
- **Caddy reverse proxy**: Runs on ports `80/443` (publicly exposed)
- **Basic Auth**: All dashboard requests are protected with username/password

```
Internet → Caddy (80/443) → Dashboard (8000)
           [Security Headers]
           [Basic Auth]
```

## Configuration

### Environment Variables

Set these in your `.env` file:

```bash
# Dashboard credentials (REQUIRED FOR PRODUCTION)
DASHBOARD_USERNAME=operator
DASHBOARD_PASSWORD=changeme-in-production

# Optional: domain for HTTPS
CADDY_DOMAIN=localhost
```

### Default Values

If not set:
- `DASHBOARD_USERNAME=admin`
- `DASHBOARD_PASSWORD=changeme`
- `CADDY_DOMAIN=localhost`

### Docker Compose Services

```yaml
dashboard:
  - Internal service on port 8000
  - Only exposed to Caddy via Docker network
  - Enforces HTTP Basic Authentication
  - Requires DASHBOARD_USERNAME and DASHBOARD_PASSWORD

caddy:
  - Reverse proxy on ports 80 and 443
  - Forwards requests to dashboard
  - Adds security headers
  - Manages SSL/TLS certificates (if domain configured)
```

## Security Features

### 1. Basic Authentication

All requests to the dashboard are protected:

```
GET http://dashboard → Caddy asks for credentials → Caddy adds auth header → Dashboard validates
```

To access without authentication, you must:
1. Leave both `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD` empty (local dev only)
2. Even then, you must use the reverse proxy

### 2. Network Isolation

- Dashboard is only accessible through Caddy's Docker network
- Direct access to port 8000 is not exposed by default
- Use `expose:` in compose instead of `ports:` for dashboard

### 3. Security Headers

Caddy automatically adds security headers to all responses:

| Header | Value | Purpose |
|--------|-------|---------|
| `X-Frame-Options` | `SAMEORIGIN` | Prevent clickjacking |
| `X-Content-Type-Options` | `nosniff` | Prevent MIME sniffing |
| `X-XSS-Protection` | `1; mode=block` | Enable XSS protection |
| `Referrer-Policy` | `no-referrer-when-downgrade` | Control referrer info |
| `Content-Security-Policy` | `default-src 'self'` | Restrict resource loading |

### 4. SSL/TLS (HTTPS)

For production VPS deployments:

```bash
# In .env:
CADDY_DOMAIN=tracker.example.com

# Restart services:
docker compose up -d
```

Caddy will automatically:
1. Request an SSL certificate from Let's Encrypt
2. Handle certificate renewal
3. Serve HTTPS on port 443
4. Redirect HTTP to HTTPS

## Usage

### Local Development

```bash
cp .env.example .env

# Edit .env if needed (defaults work for localhost):
# DASHBOARD_USERNAME=operator
# DASHBOARD_PASSWORD=changeme-in-production

docker compose up -d
```

Access dashboard at: `http://localhost`

When prompted:
- Username: `operator`
- Password: `changeme-in-production`

### Production VPS

```bash
# 1. Set strong credentials in .env
DASHBOARD_USERNAME=your-secure-username
DASHBOARD_PASSWORD=your-very-strong-password

# 2. Set domain for HTTPS
CADDY_DOMAIN=tracker.example.com

# 3. Point DNS to VPS
# Add DNS A record: tracker.example.com → your-vps-ip

# 4. Start services
docker compose up -d

# 5. Verify
curl -u your-secure-username:your-very-strong-password https://tracker.example.com/
```

## Common Tasks

### Change Dashboard Credentials

```bash
# Edit .env
DASHBOARD_USERNAME=new-username
DASHBOARD_PASSWORD=new-password

# Restart services
docker compose restart dashboard
```

### Enable HTTPS

```bash
# Edit .env
CADDY_DOMAIN=yourdomain.com

# Restart
docker compose restart caddy

# Wait for certificate to be issued (check logs)
docker compose logs caddy
```

### Access Dashboard via curl

```bash
# Local (HTTP)
curl -u operator:changeme-in-production http://localhost/

# Remote (HTTPS)
curl -u operator:changeme-in-production https://tracker.example.com/

# Get just the health endpoint (no auth)
curl http://localhost/health
```

### Monitor Caddy

```bash
# View Caddy logs
docker compose logs -f caddy

# View Caddy config
docker exec price-tracker-caddy cat /etc/caddy/Caddyfile

# Check certificate status
docker exec price-tracker-caddy caddy list-certs
```

### Disable Authentication (Local Development Only)

If you want to access the dashboard without basic auth:

```bash
# In .env, leave empty:
DASHBOARD_USERNAME=
DASHBOARD_PASSWORD=

# Restart
docker compose restart dashboard

# Dashboard will not require auth (still goes through Caddy reverse proxy)
```

## Troubleshooting

### "Invalid credentials" when accessing dashboard

**Solution**: Verify `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD` are set correctly in `.env`

```bash
# Check what's configured:
grep DASHBOARD_ .env

# Verify using curl:
curl -v -u operator:changeme-in-production http://localhost/
```

### Dashboard timeout via Caddy

**Solution**: Check if dashboard service is running

```bash
docker compose ps

# If dashboard is down:
docker compose logs dashboard
docker compose restart dashboard
```

### Certificate not issued on HTTPS setup

**Solution**: Check Caddy logs and verify DNS

```bash
docker compose logs caddy | grep -i "certificate\|error"

# Verify DNS is pointing to VPS:
nslookup tracker.example.com
```

### Direct access to port 8000 returns "connection refused"

**Good!** This means network isolation is working. Access only goes through Caddy on port 80/443.

If you need to debug:
```bash
# From inside the container:
docker exec price-tracker-dashboard curl http://localhost:8000/health
```

## Caddyfile Customization

Edit `Caddyfile` to customize the reverse proxy behavior.

### Example: Custom error page

```caddy
handle_errors {
  header Content-Type text/plain
  respond "{http.error.status_code} {http.error.status_text}"
}
```

### Example: Rate limiting

```caddy
rate_limit * 100 "10s"
```

### Example: Access logs

```caddy
log {
  output file /var/log/caddy/access.log {
    roll_size 10mb
    roll_keep 3
  }
  format logfmt
}
```

## Security Checklist for Production

- [ ] Change `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD` from defaults
- [ ] Use a strong password (16+ characters with mixed case, numbers, symbols)
- [ ] Set `CADDY_DOMAIN` to your actual domain for HTTPS
- [ ] Verify DNS points to your VPS
- [ ] Test that HTTPS is working and certificate is valid
- [ ] Test that basic auth is required for dashboard access
- [ ] Check firewall allows only ports 80 and 443 inbound
- [ ] Set up log rotation for Caddy (see `/var/log/caddy/`)
- [ ] Regularly check certificate expiration (Caddy handles renewal automatically)
- [ ] Test remote access with actual credentials

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ VPS Internet-Facing (Ports 80, 443)                        │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Caddy Reverse Proxy (Docker Container)               │  │
│  │ ├─ Listen: 0.0.0.0:80, 0.0.0.0:443                  │  │
│  │ ├─ Add Security Headers                              │  │
│  │ ├─ SSL/TLS Termination                               │  │
│  │ └─ Forward to: dashboard:8000                        │  │
│  └──────────────────┬───────────────────────────────────┘  │
│                     │ (Docker Network)                      │
│  ┌──────────────────▼───────────────────────────────────┐  │
│  │ Dashboard Service (Docker Container)                 │  │
│  │ ├─ Listen: 0.0.0.0:8000                             │  │
│  │ ├─ HTTP Basic Auth (DASHBOARD_USERNAME/PASSWORD)    │  │
│  │ ├─ Serve HTML/forms/API                             │  │
│  │ └─ Access SQLite database (mounted volume)          │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Main App Service (Docker Container)                  │  │
│  │ ├─ Run Scheduler                                     │  │
│  │ ├─ Scrape e-commerce sites                          │  │
│  │ ├─ Send Telegram alerts                             │  │
│  │ └─ Update SQLite database                           │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
│  Volumes:                                                    │
│  ├─ ./data (SQLite database, shared between services)     │
│  ├─ caddy_data (Caddy state and certificates)             │
│  └─ caddy_config (Caddy configuration)                     │
└─────────────────────────────────────────────────────────────┘
```

## Next Steps

After setting up the reverse proxy and auth:

1. **Health Checks**: Add monitoring for Caddy and dashboard
2. **Observability**: Enable structured logging with log aggregation
3. **Backup**: Set up automated backups for SQLite database
4. **Failover**: Consider adding a secondary VPS for high availability
5. **Metrics**: Expose Prometheus metrics from the app and Caddy

See `VPS_DEPLOYMENT_PLAN.md` for the complete deployment roadmap.
