from app.database.db import get_session
from app.database.repository import PlatformRepository, ProductRepository, AlertRepository
from app.notifier.telegram import NotificationService
s = get_session()
p = PlatformRepository.get_by_name(s, "myntra") or PlatformRepository.create(s, name="myntra", display_name="Myntra", base_url="https://myntra.com")
prod = ProductRepository.create_or_update(s, platform_id=p.id, product_url="https://myntra.com/test", platform_product_id="TEST-1", brand="Test", model_name="TestModel", title="TestModel", listed_price=1000, discounted_price=800, in_stock=True, sizes_available='["9"]', image_url="", sku="TEST-1")
alert = AlertRepository.create(s, prod.id, "test_alert", "This is a test alert from dev")
s.commit()
service = NotificationService()
import asyncio
asyncio.run(service.process_unnotified_alerts(s, batch_size=10))
s.close()