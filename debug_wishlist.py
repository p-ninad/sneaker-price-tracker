#!/usr/bin/env python3
"""Debug script to inspect wishlist entries and test URL parsing."""

import sys
import sqlite3
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from app.utils.url_parser import extract_product_id_from_url, extract_platform_from_url

def main():
    db_path = Path(__file__).parent / "data" / "price_tracker.db"
    
    if not db_path.exists():
        print(f"❌ Database not found at {db_path}")
        return
    
    print("=" * 80)
    print("WISHLIST ENTRIES DEBUG")
    print("=" * 80)
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get all active wishlist entries
    cursor.execute("""
        SELECT id, source_url, platform, title, brand, model_name, is_active
        FROM wishlist_entries
        ORDER BY created_at DESC
    """)
    
    entries = cursor.fetchall()
    print(f"\n📊 Total entries: {len(entries)}\n")
    
    for i, entry in enumerate(entries, 1):
        url = entry["source_url"]
        extracted_id = extract_product_id_from_url(url)
        extracted_platform = extract_platform_from_url(url)
        
        print(f"Entry {i}:")
        print(f"  Active: {'✅' if entry['is_active'] else '❌'}")
        print(f"  Title: {entry['title']}")
        print(f"  Brand: {entry['brand']} | Model: {entry['model_name']}")
        print(f"  DB Platform: {entry['platform']}")
        print(f"  URL: {url}")
        print(f"  🔍 Extracted Platform: {extracted_platform}")
        print(f"  🔍 Extracted Product ID: {extracted_id}")
        
        # Check if New Balance
        if "new balance" in entry['title'].lower():
            print(f"  ⚠️  NEW BALANCE PRODUCT - Check these values for correctness")
        
        print()
    
    conn.close()

if __name__ == "__main__":
    main()
