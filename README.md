# Price Tracker: Indian Sneaker E-Commerce Monitor

A production-quality Python application for tracking sneaker prices, stock availability, and discounts across Indian e-commerce platforms.

## Overview

This system runs continuously on a Linux VPS, monitoring sneaker prices across multiple Indian retail platforms (Myntra, AJIO, VegNonVeg, Superkicks, etc.). It detects price changes, new arrivals, restocks, and sends notifications via Telegram.

### Key Features

- **Multi-Platform Scraping**: Hybrid approach (APIs → GraphQL → HTML scraping)
- **Price History Tracking**: Full historical data for trend analysis
- **Smart Notifications**: Telegram alerts for price drops, new items, restocks
- **AI-Powered Normalization**: Sneaker name deduplication and matching
- **Lightweight**: Designed for small VPS (minimal resource usage)
- **Extensible**: Easy to add new platforms and features
- **Production-Ready**: Error isolation, comprehensive logging, graceful degradation

## Architecture

```
Scheduler (APScheduler)
    ↓
Collectors (Hybrid Scraping)
    ↓
Database (SQLite + SQLAlchemy)
    ↓
Services (Tracking, Normalization)
    ↓
Notifier (Telegram)
```

## Quick Start

### Prerequisites

- Python 3.11+
- Linux/Ubuntu VPS or local machine
- OpenAI API key (optional)
- Telegram bot token (for notifications)

### Local Setup

```bash
# Clone repository
cd price_tracker

# Install dependencies
make install

# Create local secrets file
cp .env.example .env
# Edit .env with your API keys

# Initialize database
make init

# Run application
make run
```

### Secrets Management

- Local development uses a personal `.env` file copied from `.env.example`.
- The repository ignores `.env`, so secrets remain out of Git history.
- Docker and VPS deployments should inject secrets via environment variables or a mounted secret file.
- If you want the app to read a non-default file, set `APP_ENV_FILE=/path/to/your/secrets.env` before starting the process.
- Production startup will fail fast if only one Telegram credential is present (`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` must both be set).

### Docker Deployment

```bash
# Build image
make docker-build

# Start with docker-compose (reverse proxy + auth + one-shot migrations)
make docker-run

# Rerun migrations without restarting the stack
make docker-migrate

# View logs
make docker-logs

# Stop
make docker-stop
```

### Operational Runbook

For a detailed, current-state guide covering local runs, Docker, tests, VPS deployment, and Telegram verification, see `docs/OPERATIONS_RUNBOOK.md`.

### Accessing the Dashboard

After starting with `docker-compose`, the dashboard is available at:
- **Local**: `http://localhost`
- **Via reverse proxy**: The dashboard is only exposed through the Caddy reverse proxy (port 80/443), not directly
- **First-time setup**: Open `http://localhost/bootstrap` and create the first admin account using `AUTH_BOOTSTRAP_TOKEN`
- **Postgres**: The compose stack connects to a persistent PostgreSQL service running on the host. See `docs/EXTERNAL_POSTGRES.md` for service, pgAdmin, and `pg_hba.conf` setup.

#### Authentication

The dashboard now uses a form-based login flow with server-side sessions. Only admin users can log in.

```bash
# Log in through the browser at /login after bootstrapping the first admin
curl -i http://localhost/login
```

### Telegram Bot UX

Regular users interact only through Telegram. The bot accepts structured inputs rather than free-form chat:

- `/start` registers the Telegram identity or refreshes the profile
- `/status` reports bot uptime and alert usage
- `/add` runs a guided prompt flow for one alert at a time
- `/list` shows the user’s current alerts
- `/edit <id> key:value ...` updates alert metadata such as notes, sizes, or platforms
- `/pause <id>` and `/resume <id>` toggle an alert
- `/delete <id>` removes an alert
- `/cancel` aborts an in-progress flow

For `/add`, the bot expects one value per step:

- full `http(s)` URL
- plain-text brand, model, and title
- comma-separated platforms such as `myntra, ajio`
- comma-separated numeric sizes such as `8, 8.5, 9`
- optional notes

Regular users can keep at most 5 active alerts for now.
Admins must select a Telegram-registered user in the dashboard before creating, updating, or deleting wishlist items.
The dashboard user picker searches by display name and Telegram ID, and only users who have already used `/start` are selectable.

#### Runtime model

Run the Telegram bot as its own process with `python -m app.bot.main` or the `telegram-bot` service in `docker-compose.yml`.
It uses polling so the VPS only needs outbound network access to Telegram, and it can restart independently from the web dashboard.

#### Deploy readiness

Before bringing a VPS online, run `make ready` to verify the database can initialize and that each service has the minimum required configuration.
You can scope the check with `make ready SERVICE=dashboard`, `make ready SERVICE=main`, or `make ready SERVICE=telegram-bot`.

#### Admin Assistant

Admins can use the `Ask Assistant` page in the dashboard to ask natural-language questions about the current tracker state.
The assistant answers from live data first and can optionally use `OPENAI_API_KEY` for richer phrasing, but it will not invent data that is not present in the database.

#### Watchlist Rules

Open a product trend page from the dashboard to set a per-product price threshold or disable restock alerts.
Those rules feed the alert engine during watchlist scans, so price-drop and restock notifications can be tuned per product instead of using only global defaults.

#### Configuring HTTPS

To enable HTTPS with automatic certificate generation via Caddy:

1. Point your domain to the VPS
2. Set `CADDY_DOMAIN=your-domain.com` in your `.env`
3. Restart the services

Caddy will automatically request and manage SSL certificates.

## Configuration

Use `.env.example` as the template for local development and fill in the values you need.

For Docker or a VPS, prefer exporting secrets directly in the runtime environment or mounting them from a secure file. The app will load `.env` automatically when it exists, otherwise it falls back to environment variables only.

For Postgres deployments, run PostgreSQL on the host, set the `POSTGRES_*` values used by Compose, and let the `database-migrate` service apply migrations before the app starts. See `docs/EXTERNAL_POSTGRES.md` for the full setup.

Example environment variables:

```env
ENV=production
LOG_LEVEL=INFO
DATABASE_URL=postgresql+psycopg://price_tracker:changeme@127.0.0.1:5432/price_tracker
POSTGRES_DB=price_tracker
POSTGRES_USER=price_tracker
POSTGRES_PASSWORD=changeme
POSTGRES_HOST=host.docker.internal
POSTGRES_PORT=5432
DOCKER_SUBNET=172.30.0.0/24
OPENAI_API_KEY=sk-...
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=987654321
PLAYWRIGHT_HEADLESS=true
MIN_DELAY_BETWEEN_REQUESTS_SECONDS=3
MAX_DELAY_BETWEEN_REQUESTS_SECONDS=10
CATALOG_SCAN_INTERVAL_HOURS=6
WATCHLIST_SCAN_INTERVAL_HOURS=1
HOT_ITEMS_SCAN_INTERVAL_MINUTES=15
ENABLED_PLATFORMS=myntra,ajio,vegnonveg,superkicks
PRICE_DROP_THRESHOLD_PERCENT=10
```

## Project Structure

```
price_tracker/
├── src/
│   ├── app/
│   │   ├── collectors/      # Platform scrapers
│   │   ├── database/        # SQLAlchemy models + DAL
│   │   ├── services/        # Business logic
│   │   ├── ai/              # OpenAI integration
│   │   ├── scheduler/       # APScheduler jobs
│   │   ├── notifier/        # Telegram notifications
│   │   ├── utils/           # Helpers, logging
│   │   ├── config.py        # Configuration
│   │   └── main.py          # Entry point
│   └── tests/               # Test suite
├── data/                    # SQLite database
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── requirements.txt
└── README.md
```

## Development

### Running Tests

```bash
# All tests
make test

# Unit tests only
make test-unit

# Integration tests
make test-integration

# With coverage
pytest src/tests -v --cov=src/app
```

### Code Quality

```bash
# Lint
make lint

# Format
make format

# Check all
make check
```

## Supported Platforms

### MVP (Phase 1)
- [x] Myntra (collector implemented, API methods stubbed)
- [ ] AJIO (coming next)
- [ ] VegNonVeg (coming next)
- [ ] Superkicks (coming next)

### Planned (Phase 2)
- [ ] TataCliq
- [ ] Flipkart
- [ ] LimitedEdt
- [ ] Footlocker India

## Collector Implementation Strategy

Each collector follows this priority:

1. **Hidden APIs** → Inspect network requests, use undocumented endpoints
2. **GraphQL APIs** → Query graph endpoints if available
3. **REST APIs** → Use official or semi-official APIs
4. **HTML Scraping** → Playwright + BeautifulSoup fallback

This hybrid approach ensures:
- **Speed**: APIs are faster than scraping
- **Stability**: APIs change less frequently
- **Anti-bot friendliness**: Less aggressive scraping
- **Resilience**: Fallback strategies when APIs change

## Database Schema

### Core Tables

- **platforms**: E-commerce platforms (Myntra, AJIO, etc.)
- **products**: Sneaker product listings
- **price_history**: Historical price snapshots
- **stock_history**: Stock availability over time
- **alerts**: Price drops, new items, restocks
- **scan_jobs**: Audit log of scraping runs
- **watchlist**: User-watched products

All tables are indexed for query performance and are backed by Alembic migrations for SQLite and Postgres deployments.

## Sneaker Normalization

The system uses a **deterministic-first, AI-assisted fallback** approach:

1. **Rule-based normalization** → Extract brand + model from title
2. **Regex patterns** → Match known sneaker models
3. **AI assistance (optional)** → GPT for ambiguous cases
4. **Duplicate detection** → Find same shoe across platforms

Example:

```
"MEN NEW BALANCE RC42 LIFESTYLE" 
  → Brand: "New Balance", Model: "RC42"

"Adidas UltraBoost 22 - Men's Running"
  → Brand: "Adidas", Model: "UltraBoost 22"
```

## Notification System (✓ IMPLEMENTED)

Telegram bot sends alerts for:

- **Price Drops** → When price falls below threshold (configured)
- **New Products** → When new sneakers are discovered (optional)
- **Restocks** → When out-of-stock items return (optional)
- **Size Availability** → When specific sizes change

### Setup

```bash
# 1. Get bot token from @BotFather on Telegram
# 2. Get your chat ID (see TELEGRAM_NOTIFIER.md)
# 3. Edit .env:
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=987654321

# 4. Test it works
python3 -m pytest src/tests/unit/test_notifier.py
```

### Example Notification

```
🔻 PRICE DROP
Nike Air Jordan 1
Platform: Myntra
Type: price_drop

Price dropped by ₹3,001 (25%)
💰 Current Price: ₹8,999 (25% off)
✅ In Stock

🔗 View on Myntra
```

### Features

- ✅ Async batch sending (~1-2s for 10 alerts)
- ✅ Beautiful HTML formatting
- ✅ Error handling & retry logic
- ✅ Graceful degradation if credentials missing
- ✅ Full logging via structlog

See [TELEGRAM_NOTIFIER.md](TELEGRAM_NOTIFIER.md) for complete setup and usage guide.

## Performance & Optimization

### Database
- WAL mode for SQLite (better concurrency)
- Strategic indexing on frequently queried columns
- Automatic cleanup of old snapshots (coming soon)

### Scraping
- Random delays between requests (3–10 seconds)
- Exponential backoff on failures
- Sequential scraping (no aggressive parallelization)
- Browser fingerprinting (realistic headers, viewport, etc.)

### Memory
- Single process, no Redis/Celery overhead
- Streaming responses for large datasets
- Batch processing for alerts

## Logging & Monitoring

Structured logging with `structlog`:

```json
{
  "event": "price_drop_detected",
  "platform": "myntra",
  "product_id": "12345",
  "old_price": 6999,
  "new_price": 5499,
  "timestamp": "2024-05-21T10:30:00Z"
}
```

All events logged to stdout (captured by Docker/systemd).

## Implementation Status

### ✅ Phase 1: Foundation (COMPLETE)
- [x] Database schema (9 tables with indexes)
- [x] Config management (25+ settings)
- [x] Logging system (structlog)
- [x] Collector abstraction (plugin pattern)
- [x] Myntra collector (API stubs ready)
- [x] Scheduler setup (APScheduler)
- [x] 36 unit tests (100% pass)

### ✅ Phase 2: Tracking Service (COMPLETE)
- [x] TrackingService (change detection, alerts)
- [x] Price analysis (trends, statistics)
- [x] Stock tracking (snapshots, history)
- [x] Smart alerts (threshold-based)
- [x] 17 comprehensive unit tests

### ✅ Phase 3: Notifications (COMPLETE)
- [x] **Telegram integration** (async, batch)
- [x] Beautiful message formatting
- [x] Error handling & logging
- [x] 22 comprehensive tests
- [ ] Alert rules engine (coming)
- [ ] Watchlist management (coming)

### 🟡 Phase 4: Additional Collectors
- [ ] AJIO collector
- [ ] VegNonVeg collector
- [ ] Superkicks collector
- [ ] AI normalization service

### 🟡 Phase 5: Advanced Features
- [x] Conversational queries (ChatGPT)
- [x] Web dashboard
- [x] Postgres migration
- [x] Historical trend charts

### 🟡 Phase 6: Alert Rules
- [x] Watchlist rules management
- [x] Rule-aware alert engine

## Roadmap

### Recently Completed (May 21, 2026)

**Telegram Notifier** ✅
- Async message sending
- Batch processing
- HTML formatting with emojis
- Graceful error handling
- Full test coverage (22 tests)

**Complete Alert Pipeline** ✅
- Collector → TrackingService → Alerts → Telegram
- End-to-end notifications working
- See [TELEGRAM_NOTIFIER.md](TELEGRAM_NOTIFIER.md) for setup

### Next Priority

1. **AJIO Collector** (test real platform integration)
2. **End-to-End Tests** (full pipeline validation)
3. **Additional Collectors** (VegNonVeg, Superkicks)

## Cost Estimation

### VPS Running Costs
- **Small Ubuntu VPS**: $3–5/month (DigitalOcean, Linode)
- **Storage**: <500MB for SQLite + images
- **Bandwidth**: Minimal (mostly JSON responses)

### API Costs
- **OpenAI**: ~$0.10/day (optional, only for normalization)
- **Telegram**: Free (bot API)

**Monthly Cost**: ~$5–10 (minimal)

## Troubleshooting

### Database locked error
```bash
# SQLite may have lingering connections
# Restart the container
make docker-stop
make docker-run
```

### Collector failing silently
- Check logs: `make docker-logs`
- Verify network from VPS: `curl https://myntra.com`
- Check for robots.txt blocking

### OpenAI errors
- Verify API key in `.env`
- Check rate limits
- Monitor token usage

## Contributing

This is a personal project, but development follows best practices:

1. **Write tests** for new features
2. **Follow PEP 8** (enforced by Black/Ruff)
3. **Update docs** when changing architecture
4. **Isolate failures** (one platform shouldn't crash others)

## License

Personal project. Not for commercial use or resale.

## Contact

Questions? Check the inline code comments and docstrings.

---

**Next Step**: Run `make install && make init && make run` to get started!
