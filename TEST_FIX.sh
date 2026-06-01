#!/bin/bash
# Quick start guide for testing the Myntra collector fix
# Run this to test the watchlist scan with enhanced logging

set -e

echo "=========================================="
echo "Myntra Collector Fix - Test Guide"
echo "=========================================="
echo ""
echo "This script provides quick commands to test the fix"
echo ""

# Show current state
echo "Step 1: Check stored wishlist entries"
echo "  Command: python3 debug_wishlist.py"
echo ""

echo "Step 2: Test URL patterns"
echo "  Command: python3 test_url_patterns.py"
echo ""

echo "Step 3: Run watchlist scan in Docker (LIVE TEST)"
echo "  Terminal 1:"
echo "    docker compose logs -f price-tracker"
echo ""
echo "  Terminal 2:"
echo "    docker compose exec price-tracker python -m app.scheduler.trigger"
echo ""

echo "Step 4: Check Telegram for alerts"
echo "  Look for messages with:"
echo "    - Product title (New Balance 9060, New Balance 574 Core)"
echo "    - Current price (INR)"
echo "    - Product URL"
echo "    - Status message"
echo ""

echo "=========================================="
echo "Expected Logs When Working"
echo "=========================================="
echo "Look for these patterns in docker logs:"
echo ""
echo "  ✅ Processing wishlist entry | extracted_product_id=36427615"
echo "  ✅ Scraping Myntra product - attempting URL | url=https://www.myntra.com/36427615"
echo "  ✅ Page load response | status=200"
echo "  ✅ Found product title"
echo "  ✅ Successfully scraped product from Myntra"
echo "  ✅ Successfully fetched product via scraping"
echo ""

echo "=========================================="
echo "Expected Results"
echo "=========================================="
echo "  • Watchlist scan should report: Products updated: 2"
echo "  • Two Telegram alerts should arrive"
echo "  • Logs should show extracted product IDs: 36427615, 38760325"
echo ""

echo "=========================================="
echo "Debugging (If Still Failing)"
echo "=========================================="
echo ""
echo "Check these in logs:"
echo "  1. Is product_id correctly extracted? (36427615)"
echo "  2. Which URL attempt is being made?"
echo "  3. What's the page response status?"
echo "  4. Can the HTML be parsed (title extraction)?"
echo "  5. Are there any exception messages?"
echo ""

echo "Common issues:"
echo "  • 404 errors: URL pattern doesn't match Myntra structure"
echo "  • Timeout errors: Browser can't load page (blocked by Myntra)"
echo "  • Parse failures: HTML selectors don't match current structure"
echo ""

