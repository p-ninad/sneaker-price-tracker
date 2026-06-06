"""Tests for Myntra discovery fallbacks."""

from __future__ import annotations

import pytest

from app.collectors.base import ProductData
from app.collectors.myntra import MyntraCollector
from app.utils.url_parser import extract_product_id_from_url


def test_extract_product_id_from_myntra_buy_url():
    url = "https://www.myntra.com/sneakers/nike-air-max/27189942/buy"

    assert extract_product_id_from_url(url) == "27189942"


def test_extract_product_urls_from_html_filters_non_product_links():
    collector = MyntraCollector()
    html = """
    <html>
      <body>
        <a href="/sneakers/nike-air-max/27189942/buy">Nike Air Max</a>
        <a href="https://www.myntra.com/sneakers/adidas-ozweego/27112233/buy">Adidas Ozweego</a>
        <a href="/help">Help</a>
      </body>
    </html>
    """

    urls = collector._extract_product_urls_from_html(
        html,
        "https://www.myntra.com/search?rawQuery=sneaker",
    )

    assert urls == [
        "https://www.myntra.com/sneakers/nike-air-max/27189942/buy",
        "https://www.myntra.com/sneakers/adidas-ozweego/27112233/buy",
    ]


@pytest.mark.asyncio
async def test_discover_via_scraping_hydrates_product_urls(monkeypatch):
    collector = MyntraCollector()
    discovered_url = "https://www.myntra.com/sneakers/nike-air-max/27189942/buy"

    async def mock_http_search(query: str, limit: int):
        return [discovered_url]

    async def mock_fetch_details(product_id: str, source_url: str | None = None):
        return ProductData(
            platform_product_id=product_id,
            product_url=source_url or discovered_url,
            title="Nike Air Max",
            brand="Nike",
            model_name="Air Max",
        )

    async def mock_playwright_search(query: str, limit: int):
        return []

    async def mock_fetch_details_via_scraping(*args, **kwargs):
        return None

    monkeypatch.setattr(collector, "_discover_product_urls_via_http", mock_http_search)
    monkeypatch.setattr(collector, "_discover_product_urls_via_playwright", mock_playwright_search)
    monkeypatch.setattr(collector, "_fetch_details_via_http", mock_fetch_details)
    monkeypatch.setattr(collector, "_fetch_details_via_scraping", mock_fetch_details_via_scraping)

    products = await collector._discover_via_scraping("sneaker", 10)

    assert products is not None
    assert len(products) == 1
    assert products[0].platform_product_id == "27189942"
    assert products[0].product_url == discovered_url
