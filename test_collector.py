#!/usr/bin/env python3
"""Test Myntra collector with actual product IDs from the database."""

import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

async def main():
    from app.collectors.myntra import MyntraCollector
    from app.utils.url_parser import extract_product_id_from_url
    
    # Product IDs extracted from stored URLs
    products = [
        {
            "id": "36427615",
            "title": "New Balance 9060",
            "stored_url": "https://www.myntra.com/36427615",
        },
        {
            "id": "38760325", 
            "title": "New Balance 574 Core",
            "stored_url": "https://www.myntra.com/38760325",
        },
    ]
    
    print("=" * 80)
    print("MYNTRA COLLECTOR TEST")
    print("=" * 80)
    print()
    
    collector = MyntraCollector()
    
    for product in products:
        print(f"Testing: {product['title']}")
        print(f"  Stored URL: {product['stored_url']}")
        print(f"  Product ID: {product['id']}")
        
        # Test fetch_product_details
        result = await collector.fetch_product_details(product['id'])
        
        if result:
            print(f"  ✅ SUCCESS")
            print(f"     Title: {result.title}")
            print(f"     Brand: {result.brand}")
            print(f"     Model: {result.model_name}")
            print(f"     Price: {result.discounted_price} INR")
            print(f"     URL: {result.product_url}")
        else:
            print(f"  ❌ FAILED - No product data returned")
        
        print()

if __name__ == "__main__":
    asyncio.run(main())
