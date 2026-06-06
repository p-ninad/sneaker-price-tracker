from __future__ import annotations

from types import SimpleNamespace


def test_format_currency_uses_rupee_symbol():
    from app.dashboard import format_currency

    assert format_currency(1250, "INR") == "₹ 1,250"
    assert format_currency(None, "INR") == "N/A"


def test_build_price_chart_svg_renders_polyline():
    from app.dashboard import build_price_chart_svg

    svg = build_price_chart_svg([100.0, 90.0, 95.0])

    assert "<svg" in svg
    assert "polyline" in svg
    assert "circle" in svg


def test_build_trend_view_uses_latest_snapshots(monkeypatch):
    import app.dashboard as dashboard

    product = SimpleNamespace(
        id=42,
        title="Air Zoom",
        product_url="https://example.com/product",
        currency="INR",
        platform=SimpleNamespace(display_name="Myntra"),
    )
    snapshots = [
        SimpleNamespace(discounted_price=120.0, listed_price=150.0),
        SimpleNamespace(discounted_price=100.0, listed_price=150.0),
        SimpleNamespace(discounted_price=90.0, listed_price=150.0),
    ]

    monkeypatch.setattr(dashboard.ProductRepository, "get_by_id", lambda session, product_id: product)
    monkeypatch.setattr(
        dashboard.PriceSnapshotRepository,
        "get_last_n",
        lambda session, product_id, n=12: list(reversed(snapshots)),
    )

    view = dashboard.build_trend_view(SimpleNamespace(), 42)

    assert view is not None
    assert view.product_id == 42
    assert view.snapshot_count == 3
    assert view.current_price == 90.0
    assert view.previous_price == 100.0
    assert view.change_amount == -10.0
