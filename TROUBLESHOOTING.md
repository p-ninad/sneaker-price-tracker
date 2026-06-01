# Troubleshooting Guide

## Common Issues and Solutions

### Issue: "source product not found" Errors in Watchlist Scan

**Symptoms:**
- Watchlist scan runs but reports errors like:
  ```
  Watchlist scan summary
  Entries scanned: 2
  Products updated: 0
  Alerts created: 0

  ❗ Errors:
  * New Balance 9060 on myntra: source product not found
  * New Balance 574 Core on myntra: source product not found
  ```
- No products are being updated
- No price alerts are being triggered

**Root Cause:**

The watchlist scan uses a two-stage approach to fetch product details:

1. **Primary**: Try to fetch from Myntra API (`/gateway/v2/products/{product_id}`)
   - This endpoint often doesn't work without authentication or specific headers
   - Fails silently, then falls back to scraping

2. **Fallback**: Use Playwright to scrape the product page
   - This method was previously **not implemented** (returned `None`)
   - With no working fallback, the scan fails to fetch product details

**Result**: Both methods fail → `fetch_product_details()` returns `None` → "source product not found" error

### Fix Applied (v1.1)

**What was changed:**
- Implemented Playwright-based scraping fallback in [src/app/collectors/myntra.py](src/app/collectors/myntra.py#L219)
- Now the collector will:
  1. Try REST API (fast, but might not work)
  2. If API fails, use Playwright to scrape the product page (slow, but reliable)
  3. Parse HTML with BeautifulSoup to extract product details

**New Behavior:**
- Scraping tries multiple URL patterns to find the product:
  - `https://www.myntra.com/p/{product_id}`
  - `https://www.myntra.com/products/{product_id}`
  - `https://www.myntra.com/shoes/{product_id}`

- Extracts product information from HTML:
  - Title
  - Brand and model (from title normalization)
  - Prices (listed and discounted)
  - Stock status
  - Product image

### Verification

Run the watchlist scan to test:

```bash
# Option 1: Docker (production)
docker compose exec price-tracker python -m app.scheduler.trigger

# Option 2: Local development
PYTHONPATH=src python -m app.scheduler.trigger
```

Check that:
- ✅ Entries are scanned (`Entries scanned: X`)
- ✅ Products are updated (`Products updated: X`)
- ✅ No "source product not found" errors
- ✅ Price alerts are created if prices dropped

---

## Other Common Issues

### Issue: Catalog Scan Works But Watchlist Scan Doesn't

**Possible Causes:**

1. **Watchlist entries use different URL format than cached products**
   - Catalog scan discovers products first and caches them
   - Watchlist scan relies on URLs matching the cached format
   - **Solution**: Re-add watchlist entries with correct URLs

2. **Product URLs are incomplete or formatted incorrectly**
   - Example of good URL: `https://www.myntra.com/shoes/new-balance-9060/p/mpwgf8fgg9af`
   - Example of bad URL: `https://www.myntra.com/` (missing product path)
   - **Solution**: Use full product URLs from the browser address bar

3. **Myntra changed their URL structure**
   - Myntra occasionally updates their website
   - Old cached URLs might not work with new site structure
   - **Solution**: Re-discover products using catalog scan, then re-add to watchlist

### Issue: Dashboard Shows "Connection Refused" or Timeout

**Possible Causes:**

1. **Caddy reverse proxy not running**
   - Check: `docker compose ps`
   - If not running: `docker compose up -d`

2. **Dashboard service crashed**
   - Check: `docker compose logs dashboard`
   - Restart: `docker compose restart dashboard`

3. **Wrong dashboard credentials**
   - Check `.env` file for `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD`
   - Verify credentials match what you're using to log in

### Issue: Telegram Alerts Not Sending

**Possible Causes:**

1. **Missing or invalid bot token**
   - Check: `TELEGRAM_BOT_TOKEN` in `.env`
   - Verify: Token is not truncated or corrupted
   - Solution: Generate new token from BotFather

2. **Wrong chat ID**
   - Check: `TELEGRAM_CHAT_ID` in `.env`
   - Verify: Chat ID is correct (run `/start` with bot to see chat ID)
   - Solution: Update chat ID in `.env`

3. **Network connectivity**
   - Check: `curl https://api.telegram.org/`
   - If blocked: Check firewall rules on VPS
   - Solution: VPS might block API calls, check with hosting provider

### Issue: Database Locked Errors in Logs

**Symptoms:**
```
database is locked
UNIQUE constraint failed: ...
```

**Possible Causes:**

1. **Multiple app containers writing to same SQLite database**
   - SQLite is single-writer, not suitable for multi-process
   - Current setup has only one container, so this shouldn't happen

2. **Long-running transaction blocks other operations**
   - Catalog scan takes too long
   - Watchlist scan starts while catalog scan is running

**Solution:**
- Increase scan intervals in `.env`:
  ```bash
  CATALOG_SCAN_INTERVAL_HOURS=8  # Run less frequently
  WATCHLIST_SCAN_INTERVAL_HOURS=2  # Longer interval
  ```

---

## Debugging Steps

### 1. Check Logs

```bash
# View live logs
docker compose logs -f price-tracker

# View specific service logs
docker compose logs -f dashboard
docker compose logs -f caddy

# View only errors
docker compose logs price-tracker | grep ERROR
```

### 2. Verify Configuration

```bash
# Check environment variables
docker compose exec price-tracker env | grep -E "DATABASE|DASHBOARD|TELEGRAM"

# Check if files are mounted correctly
docker compose exec price-tracker ls -la /app/data/
```

### 3. Test Individual Components

```bash
# Test Telegram integration
docker compose exec price-tracker python -c "
from app.notifier.telegram_notifier import TelegramNotifier
from app.config import settings
notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
import asyncio
asyncio.run(notifier.send_message('Test message'))
"

# Test database connectivity
docker compose exec price-tracker python -c "
from app.database.session import get_session
session = get_session()
print(f'Connected: {session.execute(\"SELECT 1\").scalar()}')
"

# Test collector
docker compose exec price-tracker python -c "
from app.collectors.registry import get_collector_registry
from app.config import settings
import asyncio

async def test():
    registry = get_collector_registry()
    collector = registry.get('myntra')
    if collector:
        # Test with a real product (adjust ID as needed)
        result = await collector.fetch_product_details('mpwgf8fgg9af')
        print(f'Product found: {result is not None}')
        if result:
            print(f'Title: {result.title}')

asyncio.run(test())
"
```

### 4. Manual Watchlist Scan

Run just the watchlist portion without full scheduler:

```bash
docker compose exec price-tracker python -c "
import asyncio
from app.scheduler.jobs import ScanScheduler
from app.collectors.registry import get_collector_registry

async def test_watchlist():
    registry = get_collector_registry()
    scheduler = ScanScheduler(registry)
    await scheduler._async_watchlist_scan()

asyncio.run(test_watchlist())
"
```

---

## Frequently Asked Questions

**Q: Why is the first scan slow?**
A: Playwright launches a browser instance on first use. Subsequent scans are faster because the browser is reused.

**Q: Can I disable Playwright to speed up scans?**
A: Not recommended. Playwright is the fallback when APIs fail. Without it, you'll get "source product not found" errors.

**Q: Why does watchlist scan take longer than catalog scan?**
A: Watchlist scan uses Playwright (web scraping) for each product, while catalog scan uses API/GraphQL when available.

**Q: Can I run multiple app instances?**
A: No. SQLite doesn't support multiple writers. Use the single-container deployment model.

**Q: How do I migrate to a different database?**
A: This requires code changes. Currently hardcoded for SQLite. Planned for future versions.

---

## Reporting Issues

When reporting issues, include:

1. **Error message** from logs
2. **Product details** (brand, model, URL)
3. **Environment**: Local dev, Docker, VPS
4. **Docker version**: `docker --version`
5. **Steps to reproduce**

Example:
```
Error: "New Balance 9060 on myntra: source product not found"
URL: https://www.myntra.com/shoes/new-balance-9060/p/mpwgf8fgg9af
Environment: Docker Compose on VPS
Occurred after: Fresh watchlist add
```

---

## Related Documentation

- [VPS_DEPLOYMENT_PLAN.md](VPS_DEPLOYMENT_PLAN.md) - Production deployment
- [REVERSE_PROXY_AUTH.md](REVERSE_PROXY_AUTH.md) - Reverse proxy and auth setup
- [README.md](README.md) - General setup and usage
- [src/app/collectors/](src/app/collectors/) - Collector implementations
