from __future__ import annotations

from types import SimpleNamespace


def test_answer_question_returns_local_summary(monkeypatch, test_session):
    import app.ai.conversational as conversational
    from app.auth.passwords import hash_password
    from app.database.repository import AlertRepository, PlatformRepository, ProductRepository, ScanJobRepository
    from app.database.repository import UserRepository
    from app.services.wishlist import WishlistService

    monkeypatch.setattr(conversational.config.settings, "openai_api_key", None, raising=False)

    user = UserRepository.create(
        test_session,
        username="conversation_user",
        password_hash=hash_password("secret", iterations=1000),
        telegram_user_id="901",
        telegram_chat_id="902",
    )

    platform = PlatformRepository.create(test_session, "myntra", "Myntra", "https://www.myntra.com")
    product = ProductRepository.create_or_update(
        test_session,
        platform_id=platform.id,
        product_url="https://www.myntra.com/product/1",
        platform_product_id="m-1",
        brand="Nike",
        model_name="Air Max",
        title="Nike Air Max",
        discounted_price=9000,
    )
    WishlistService.add_from_url(
        test_session,
        url="https://www.myntra.com/product/2",
        brand="Adidas",
        model_name="UltraBoost",
        title="Adidas UltraBoost",
        user_id=user.id,
    )
    catalog_job = ScanJobRepository.create(test_session, platform.id, "catalog")
    ScanJobRepository.mark_complete(test_session, catalog_job, status="success", products_found=1, products_updated=1)
    AlertRepository.create(test_session, product.id, "price_drop", "Price dropped")

    answer = conversational.answer_question(test_session, "How many wishlist entries and pending alerts are there?")

    assert answer.used_openai is False
    assert "Wishlist entries: 1" in answer.answer
    assert "Pending alerts: 1" in answer.answer


def test_answer_question_summarizes_latest_scan(monkeypatch, test_session):
    import app.ai.conversational as conversational
    from app.database.repository import PlatformRepository, ScanJobRepository

    monkeypatch.setattr(conversational.config.settings, "openai_api_key", None, raising=False)

    platform = PlatformRepository.create(test_session, "myntra", "Myntra", "https://www.myntra.com")
    job = ScanJobRepository.create(test_session, platform.id, "watchlist")
    ScanJobRepository.mark_complete(test_session, job, status="success", products_found=3, products_updated=1)

    answer = conversational.answer_question(test_session, "What was the latest scan?")

    assert "Latest scan:" in answer.answer
    assert "watchlist" in answer.answer
    assert "3 products found" in answer.answer
