#!/usr/bin/env python3
"""Test script to verify URL patterns and product ID extraction for Myntra products."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from app.utils.url_parser import extract_product_id_from_url, extract_platform_from_url

def test_url_patterns():
    """Test URL patterns against stored wishlist URLs."""
    
    # Actual stored URLs from database
    wishlist_entries = [
        {
            "title": "New Balance 9060",
            "stored_url": "https://www.myntra.com/36427615",
        },
        {
            "title": "New Balance 574 Core",
            "stored_url": "https://www.myntra.com/38760325",
        },
    ]
    
    print("=" * 80)
    print("MYNTRA URL PATTERN TEST")
    print("=" * 80)
    print()
    
    for entry in wishlist_entries:
        url = entry["stored_url"]
        product_id = extract_product_id_from_url(url)
        platform = extract_platform_from_url(url)
        
        print(f"Product: {entry['title']}")
        print(f"  Stored URL:       {url}")
        print(f"  Extracted ID:     {product_id}")
        print(f"  Extracted Platform: {platform}")
        print()
        
        # Show URL patterns that will be tried
        if product_id:
            possible_urls = [
                f"https://www.myntra.com/{product_id}",
                f"https://www.myntra.com/p/{product_id}",
                f"https://www.myntra.com/products/{product_id}",
                f"https://www.myntra.com/shoes/{product_id}",
            ]
            print("  URL patterns to be attempted (in order):")
            for i, attempt_url in enumerate(possible_urls, 1):
                print(f"    {i}. {attempt_url}")
        print()
    
    print("=" * 80)
    print("RECOMMENDATIONS")
    print("=" * 80)
    print("""
The fix includes:
1. ✅ Added direct URL pattern (https://www.myntra.com/{product_id})
2. ✅ Enhanced logging in _fetch_details_via_scraping()
3. ✅ Anti-detection measures (disable automation flags, user agent)
4. ✅ Better error handling with detailed attempt tracking
5. ✅ Improved HTML parsing with selector logging
6. ✅ Enhanced watchlist scan logging to track each entry

Next steps:
1. Run watchlist scan in Docker container to test
2. Check logs to see which URL pattern works
3. If still failing, HTML selectors may need updating based on current Myntra structure
4. Consider using requests library first to test URL accessibility
""")

if __name__ == "__main__":
    test_url_patterns()
