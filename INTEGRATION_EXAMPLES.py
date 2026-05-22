"""Integration Example: How to Use TrackingService with Collectors

This shows the complete flow from collector → tracking → alerts.
"""

from app.database.db import get_session
from app.database.repository import ProductRepository, PlatformRepository
from app.services.tracking import TrackingService
from app.collectors.myntra import MyntraCollector


def example_collector_to_tracking_flow():
    """Example: Process collector products through tracking service."""
    
    # Initialize
    session = get_session()
    tracking_service = TrackingService()
    collector = MyntraCollector()
    
    try:
        # Get or create platform
        platform = PlatformRepository.get_by_name(session, "myntra")
        if not platform:
            platform = PlatformRepository.create(
                session,
                name="myntra",
                display_name="Myntra",
                base_url="https://myntra.com",
            )
        
        # Step 1: Discover products (from collector)
        # response = await collector.discover_products(query="New Balance RC42")
        # products_data = response.products
        
        # For this example, simulate product data:
        from app.collectors.base import ProductData
        products_data = [
            ProductData(
                platform_product_id="12345",
                product_url="https://myntra.com/shoes/12345",
                title="New Balance RC42 Men Lifestyle",
                brand="New Balance",
                model_name="RC42",
                listed_price=7999.0,
                discounted_price=6999.0,
                currency="INR",
                discount_percentage=12.5,
                in_stock=True,
                sizes_available='["6", "7", "8", "9", "10"]',
                image_url="https://example.com/img.jpg",
                sku="NB-RC42-M",
            )
        ]
        
        # Step 2: Store or update products
        created_products = []
        for product_data in products_data:
            product = ProductRepository.create_or_update(
                session,
                platform_id=platform.id,
                product_url=product_data.product_url,
                platform_product_id=product_data.platform_product_id,
                brand=product_data.brand,
                model_name=product_data.model_name,
                title=product_data.title,
                listed_price=product_data.listed_price,
                discounted_price=product_data.discounted_price,
                in_stock=product_data.in_stock,
                sizes_available=product_data.sizes_available,
                image_url=product_data.image_url,
                sku=product_data.sku,
            )
            created_products.append(product)
        
        # Step 3: Analyze changes and create alerts
        all_alerts = []
        for product in created_products:
            # Analyze this update
            analysis = tracking_service.analyze_product_update(
                session,
                product=product,
                new_listed_price=product.listed_price,
                new_discounted_price=product.discounted_price,
                new_discount_percentage=product.discount_percentage,
                new_in_stock=product.in_stock,
                new_sizes_available=product.sizes_available,
            )
            
            print(f"\n📊 Analysis for {product.brand} {product.model_name}")
            print(f"   Changes detected: {[c.value for c in analysis.change_types]}")
            print(f"   Should notify: {analysis.should_notify()}")
            
            # Create alerts
            if analysis.has_changes():
                alerts = tracking_service.create_alerts_from_analysis(session, analysis)
                all_alerts.extend(alerts)
                
                for alert in alerts:
                    print(f"   ✉️  Alert: {alert.alert_type} - {alert.message[:50]}...")
            
            # Record historical snapshots
            tracking_service.record_price_snapshot(
                session,
                product,
                listed_price=product.listed_price,
                discounted_price=product.discounted_price,
                discount_percentage=product.discount_percentage,
            )
            
            tracking_service.record_stock_snapshot(
                session,
                product,
                in_stock=product.in_stock,
                sizes_available=product.sizes_available,
            )
        
        print(f"\n✅ Processing complete: {len(created_products)} products, {len(all_alerts)} alerts")
        
        # Step 4: Retrieve alerts for notification
        from app.database.repository import AlertRepository
        unnotified = AlertRepository.get_unnotified(session, limit=10)
        print(f"   Unnotified alerts: {len(unnotified)}")
        
        for alert in unnotified:
            print(f"   - {alert.alert_type}: {alert.message[:60]}...")
            # Next: Send via Telegram
            # await notifier.send_alert(alert)
            # AlertRepository.mark_notified(session, alert)
        
        return True
        
    finally:
        session.close()


def example_price_change_detection():
    """Example: Detect price changes for existing product."""
    
    session = get_session()
    tracking_service = TrackingService()
    
    try:
        # Get an existing product
        product = session.query(ProductRepository.__class__.__bases__[0]).first()
        if not product:
            print("❌ No products in database")
            return False
        
        # Simulate price drop
        print(f"\n💰 Tracking price for {product.brand} {product.model_name}")
        print(f"   Current price: ₹{product.discounted_price}")
        
        # Analyze (hypothetical new prices)
        new_price = product.discounted_price * 0.85  # 15% drop
        
        analysis = tracking_service.analyze_product_update(
            session,
            product,
            new_listed_price=product.listed_price,
            new_discounted_price=new_price,
            new_discount_percentage=(product.listed_price - new_price) / product.listed_price * 100,
            new_in_stock=product.in_stock,
            new_sizes_available=product.sizes_available,
        )
        
        if analysis.price_change:
            pc = analysis.price_change
            print(f"   Price change: ₹{pc.old_price:.0f} → ₹{pc.new_price:.0f}")
            print(f"   Percentage: {pc.change_percentage:.1f}%")
            print(f"   Significant drop: {pc.is_significant()}")
        
        return True
        
    finally:
        session.close()


def example_trend_analysis():
    """Example: Get price trend for a product."""
    
    session = get_session()
    tracking_service = TrackingService()
    
    try:
        # Get a product with history
        product = session.query(ProductRepository.__class__.__bases__[0]).first()
        if not product:
            print("❌ No products in database")
            return False
        
        # Get 30-day trend
        trend = tracking_service.get_price_trend(session, product.id, days=30)
        
        if trend:
            print(f"\n📈 30-Day Price Trend for {product.brand} {product.model_name}")
            print(f"   Snapshots: {trend['snapshots']}")
            print(f"   Min price: ₹{trend['min_price']:.0f}")
            print(f"   Max price: ₹{trend['max_price']:.0f}")
            print(f"   Current: ₹{trend['current_price']:.0f}")
            print(f"   Change: ₹{trend['price_change']:.0f} ({trend['price_change_percent']:.1f}%)")
        else:
            print(f"   Not enough snapshots for trend (need 2+)")
        
        return True
        
    finally:
        session.close()


if __name__ == "__main__":
    print("🎯 TrackingService Integration Examples\n")
    print("=" * 60)
    
    # Run examples
    example_collector_to_tracking_flow()
    # example_price_change_detection()
    # example_trend_analysis()
