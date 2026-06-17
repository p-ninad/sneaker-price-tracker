"""Local dashboard for managing wishlist entries and admin authentication."""

from __future__ import annotations

import argparse
import html
import json
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from app.auth.passwords import hash_password
from app.auth.web import (
    authenticate_admin,
    build_clear_session_cookie,
    build_session_cookie,
    get_authenticated_user,
    issue_session,
)
from app.ai.conversational import answer_question
import app.config as config
from app.database.db import get_session, init_db
from app.database.models import ScanJob, WishlistEntry
from app.database.repository import (
    AlertRepository,
    AuthSessionRepository,
    PriceSnapshotRepository,
    ProductRepository,
    WatchlistRepository,
    UserRepository,
)
from app.services.wishlist import WishlistService
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TrendView:
    """Precomputed chart data for a product trend."""

    product_id: int
    title: str
    product_url: str
    platform: str
    currency: str
    current_price: float | None
    previous_price: float | None
    change_amount: float | None
    change_percentage: float | None
    snapshot_count: int
    chart_svg: str


def format_currency(value: float | None, currency: str = "INR") -> str:
    if value is None:
        return "N/A"

    symbol = "₹" if currency.upper() == "INR" else currency.upper()
    return f"{symbol} {value:,.0f}"


def build_price_chart_svg(
    prices: list[float],
    *,
    width: int = 320,
    height: int = 120,
    padding: int = 12,
) -> str:
    if len(prices) < 2:
        return "<p class=\"hint\">Not enough history yet for a chart.</p>"

    minimum = min(prices)
    maximum = max(prices)
    span = maximum - minimum or 1
    x_spacing = (width - (padding * 2)) / (len(prices) - 1)
    points = []
    circles = []

    for index, price in enumerate(prices):
        x = padding + index * x_spacing
        y = height - padding - ((price - minimum) / span) * (height - (padding * 2))
        points.append(f"{x:.2f},{y:.2f}")
        circles.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="2.5" fill="#2563eb" />')

    return f"""
<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img" aria-label="Price trend chart">
  <rect x="0" y="0" width="{width}" height="{height}" rx="10" fill="#eff6ff" />
  <polyline
    fill="none"
    stroke="#2563eb"
    stroke-width="3"
    stroke-linecap="round"
    stroke-linejoin="round"
    points="{' '.join(points)}"
  />
  {''.join(circles)}
</svg>
""".strip()


def build_trend_view(session, product_id: int) -> TrendView | None:
    product = ProductRepository.get_by_id(session, product_id)
    if product is None:
        return None

    snapshots = list(reversed(PriceSnapshotRepository.get_last_n(session, product.id, n=12)))
    prices = [
        snapshot.discounted_price if snapshot.discounted_price is not None else snapshot.listed_price
        for snapshot in snapshots
        if snapshot.discounted_price is not None or snapshot.listed_price is not None
    ]
    if not prices:
        return None

    current_price = prices[-1]
    previous_price = prices[-2] if len(prices) > 1 else None
    change_amount = None if previous_price is None else current_price - previous_price
    change_percentage = None
    if previous_price not in (None, 0):
        change_percentage = (change_amount / previous_price) * 100 if change_amount is not None else None

    return TrendView(
        product_id=product.id,
        title=product.title,
        product_url=product.product_url,
        platform=product.platform.display_name if product.platform else str(product.platform_id),
        currency=product.currency or "INR",
        current_price=current_price,
        previous_price=previous_price,
        change_amount=change_amount,
        change_percentage=change_percentage,
        snapshot_count=len(prices),
        chart_svg=build_price_chart_svg(prices),
    )


def build_watchlist_rule_view(session, product_id: int) -> dict[str, object] | None:
    """Return the current watchlist rule state for a product."""
    rule = WatchlistRepository.get_by_product_id(session, product_id)
    if rule is None:
        return None

    return {
        "product_id": rule.product_id,
        "price_alert_threshold": rule.price_alert_threshold,
        "restock_alert": rule.restock_alert,
        "notes": rule.notes or "",
        "is_active": rule.is_active,
    }


def build_dashboard_trends(
    session,
    entries: list[WishlistEntry],
    limit: int = 5,
) -> list[dict[str, object]]:
    """Build a small set of trend cards for the dashboard."""
    cards: list[dict[str, object]] = []
    for entry in entries:
        products = WishlistService.find_exact_matches(session, entry)
        if not products:
            continue

        view = build_trend_view(session, products[0].id)
        if view is None:
            continue

        cards.append(
            {
                "entry": entry,
                "view": view,
                "trend_url": f"/trend?product_id={view.product_id}",
            }
        )

        if len(cards) >= limit:
            break

    return cards


def parse_csv(value: str | None) -> list[str] | None:
    if value is None:
        return None

    parsed = [item.strip() for item in value.split(",") if item.strip()]
    return parsed or None


def build_summary(session, selected_user_id: int | None = None, user_search_query: str | None = None) -> dict:
    selected_user = None
    entries = []
    if selected_user_id is not None:
        selected_user = UserRepository.get_by_id(session, selected_user_id)
        if selected_user is not None:
            entries = WishlistService.get_all_for_user(session, selected_user.id)

    user_search_results = UserRepository.search_telegram_users(session, user_search_query)
    pending_alerts = AlertRepository.get_unnotified(session, limit=100)
    recent_scans = (
        session.query(ScanJob)
        .order_by(ScanJob.started_at.desc())
        .limit(5)
        .all()
    )
    trends = build_dashboard_trends(session, entries) if selected_user is not None else []

    return {
        "entries": entries,
        "pending_alerts": len(pending_alerts),
        "recent_scans": recent_scans,
        "trends": trends,
        "selected_user": selected_user,
        "user_search_query": user_search_query or "",
        "user_search_results": user_search_results,
    }


def render_login_template(flash: str | None = None, bootstrap_available: bool = True) -> str:
    flash_block = f'<div class="flash error">{html.escape(flash)}</div>' if flash else ""
    bootstrap_note = (
        "<p><a href=\"/bootstrap\">Bootstrap the first admin account</a></p>"
        if bootstrap_available
        else "<p>The admin portal is already initialized.</p>"
    )

    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Price Tracker Admin Login</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 2rem; color: #111827; }}
    .card {{ max-width: 420px; margin: 4rem auto; background: #f9fafb; border: 1px solid #d1d5db; border-radius: 12px; padding: 1.5rem; }}
    label {{ display: block; margin-top: 0.75rem; font-weight: 600; }}
    input {{ width: 100%; padding: 0.7rem; margin-top: 0.35rem; box-sizing: border-box; }}
    button {{ margin-top: 1rem; padding: 0.7rem 1rem; border: 0; border-radius: 8px; background: #2563eb; color: #fff; cursor: pointer; }}
    .flash {{ padding: 0.75rem 1rem; border-radius: 8px; margin-bottom: 1rem; }}
    .error {{ background: #fef2f2; border: 1px solid #fca5a5; }}
    .hint {{ color: #6b7280; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Admin Login</h1>
    <p class="hint">Only admin users can access the web portal. Regular users should use Telegram.</p>
    {flash_block}
    <form method="post" action="/login">
      <label>Username<input name="username" autocomplete="username" required></label>
      <label>Password<input type="password" name="password" autocomplete="current-password" required></label>
      <button type="submit">Log in</button>
    </form>
    {bootstrap_note}
  </div>
</body>
</html>
"""


def render_bootstrap_template(flash: str | None = None) -> str:
    flash_block = f'<div class="flash">{html.escape(flash)}</div>' if flash else ""

    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Bootstrap Admin</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 2rem; color: #111827; }}
    .card {{ max-width: 520px; margin: 4rem auto; background: #f9fafb; border: 1px solid #d1d5db; border-radius: 12px; padding: 1.5rem; }}
    label {{ display: block; margin-top: 0.75rem; font-weight: 600; }}
    input {{ width: 100%; padding: 0.7rem; margin-top: 0.35rem; box-sizing: border-box; }}
    button {{ margin-top: 1rem; padding: 0.7rem 1rem; border: 0; border-radius: 8px; background: #16a34a; color: #fff; cursor: pointer; }}
    .flash {{ padding: 0.75rem 1rem; background: #ecfdf5; border: 1px solid #86efac; border-radius: 8px; margin-bottom: 1rem; }}
    .hint {{ color: #6b7280; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Bootstrap the first admin</h1>
    <p class="hint">Use the bootstrap token from your environment to create the initial admin account.</p>
    {flash_block}
    <form method="post" action="/bootstrap">
      <label>Bootstrap token<input name="bootstrap_token" autocomplete="off" required></label>
      <label>Username<input name="username" autocomplete="username" required></label>
      <label>Display name<input name="display_name" autocomplete="name"></label>
      <label>Password<input type="password" name="password" autocomplete="new-password" required></label>
      <button type="submit">Create admin</button>
    </form>
  </div>
</body>
</html>
"""


def render_dashboard_template(
    summary: dict,
    user,
    flash: str | None = None,
) -> str:
    selected_user = summary.get("selected_user")
    user_search_query = summary.get("user_search_query") or ""
    user_search_results = summary.get("user_search_results") or []
    entries = summary["entries"]
    pending_alerts = summary["pending_alerts"]
    recent_scans = summary["recent_scans"]
    trends = summary["trends"]
    trend_lookup = {
        trend["entry"].id: trend["trend_url"]
        for trend in trends
        if trend.get("entry") is not None
    }
    selected_user_label = (
        f"{selected_user.display_name or selected_user.username} "
        f"(@{selected_user.username}, TG {selected_user.telegram_user_id})"
        if selected_user is not None
        else "No user selected"
    )
    selected_user_hint = (
        "<p class='hint'>Select a Telegram user to manage their wishlist items.</p>"
        if selected_user is None
        else ""
    )
    selected_user_id_value = selected_user.id if selected_user is not None else ""

    rows = []
    for entry in entries:
        status = "active" if entry.is_active else "inactive"
        sizes = WishlistService.get_size_scope(entry)
        platforms = WishlistService.get_platforms_to_track(entry)
        rows.append(
            f"""
            <tr>
              <td>{html.escape(selected_user_label)}</td>
              <td>{html.escape(str(entry.id))}</td>
              <td>{html.escape(entry.title)}</td>
              <td>{html.escape(entry.platform)}</td>
              <td>{html.escape(', '.join(sizes))}</td>
              <td>{html.escape(', '.join(platforms))}</td>
              <td>{html.escape(status)}</td>
              <td>{html.escape(entry.notes or '')}</td>
              <td>
                {'<a href="' + html.escape(trend_lookup[entry.id]) + '">Trend</a>' if entry.id in trend_lookup else '<span class="hint">No chart yet</span>'}
              </td>
              <td>
                <form method="post" style="display:inline">
                  <input type="hidden" name="action" value="toggle">
                  <input type="hidden" name="user_id" value="{html.escape(str(entry.user_id or ''))}">
                  <input type="hidden" name="url" value="{html.escape(entry.source_url)}">
                  <input type="hidden" name="enabled" value="{ 'false' if entry.is_active else 'true' }">
                  <button type="submit">{ 'Disable' if entry.is_active else 'Enable' }</button>
                </form>
                <form method="post" style="display:inline">
                  <input type="hidden" name="action" value="delete">
                  <input type="hidden" name="user_id" value="{html.escape(str(entry.user_id or ''))}">
                  <input type="hidden" name="url" value="{html.escape(entry.source_url)}">
                  <button type="submit">Delete</button>
                </form>
              </td>
            </tr>
            """
        )

    scan_rows = []
    for scan in recent_scans:
        scan_rows.append(
            f"<li>{scan.scan_type} | {scan.status} | {scan.products_found} products | {scan.products_updated} updated</li>"
        )

    trend_cards = []
    for trend in trends:
        entry = trend["entry"]
        view = trend["view"]
        assert isinstance(view, TrendView)
        change_class = "neutral"
        change_label = "No comparison yet"
        change_value = ""
        if view.change_amount is not None:
            if view.change_amount < 0:
                change_class = "down"
                change_label = "Price drop"
            elif view.change_amount > 0:
                change_class = "up"
                change_label = "Price rise"
            else:
                change_label = "No change"
            change_value = (
                html.escape(format_currency(view.change_amount, view.currency))
                + (
                    f" ({view.change_percentage:+.1f}%)"
                    if view.change_percentage is not None
                    else ""
                )
            )

        trend_cards.append(
            f"""
            <article class="trend-card">
              <div class="trend-card__header">
                <div>
                  <h3>{html.escape(view.title)}</h3>
                  <p class="hint">{html.escape(entry.platform)} • {html.escape(view.platform)}</p>
                </div>
                <a class="trend-link" href="{html.escape(trend['trend_url'])}">Open chart</a>
              </div>
              <p><strong>Current:</strong> {html.escape(format_currency(view.current_price, view.currency))}</p>
              <p><strong>Change:</strong> <span class="{change_class}">{html.escape(change_label)}</span> {change_value}</p>
              <div class="chart">{view.chart_svg}</div>
              <p class="hint">{view.snapshot_count} price snapshot(s) recorded</p>
            </article>
            """
        )

    flash_block = f'<div class="flash">{html.escape(flash)}</div>' if flash else ""
    display_name = user.display_name or user.username
    user_result_rows = []
    for candidate in user_search_results:
        user_result_rows.append(
            f"""
            <tr>
              <td>{html.escape(candidate.display_name or candidate.username or '')}</td>
              <td>{html.escape(candidate.username)}</td>
              <td>{html.escape(str(candidate.telegram_user_id or ''))}</td>
              <td><a href="/?user_id={candidate.id}">Select</a></td>
            </tr>
            """
        )

    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Price Tracker Dashboard</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 2rem; color: #111827; }}
    h1, h2 {{ margin-bottom: 0.5rem; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }}
    .card {{ background: #f9fafb; border: 1px solid #d1d5db; border-radius: 12px; padding: 1rem; }}
    form {{ margin-top: 1rem; }}
    label {{ display: block; margin-top: 0.75rem; font-weight: 600; }}
    input, textarea {{ width: 100%; padding: 0.6rem; margin-top: 0.35rem; box-sizing: border-box; }}
    button {{ margin-top: 1rem; padding: 0.7rem 1rem; border: 0; border-radius: 8px; background: #2563eb; color: #fff; cursor: pointer; }}
    button.secondary {{ background: #0f766e; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: 0.75rem; text-align: left; vertical-align: top; }}
    th {{ background: #eff6ff; }}
    .flash {{ padding: 0.75rem 1rem; background: #ecfdf5; border: 1px solid #34d399; border-radius: 8px; margin-bottom: 1rem; }}
    ul {{ padding-left: 1rem; }}
    .topbar {{ display: flex; justify-content: space-between; align-items: center; gap: 1rem; }}
    .nav {{ display: flex; gap: 0.75rem; align-items: center; flex-wrap: wrap; }}
    .nav a {{ text-decoration: none; padding: 0.65rem 0.95rem; border-radius: 8px; }}
    .assistant {{ background: #7c3aed; color: #fff; }}
    .logout {{ background: #dc2626; color: #fff; }}
    .secondary {{ background: #0f766e; color: #fff; }}
    .trend-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; margin-top: 1rem; }}
    .trend-card {{ background: #fff; border: 1px solid #dbeafe; border-radius: 12px; padding: 1rem; }}
    .trend-card__header {{ display: flex; justify-content: space-between; gap: 1rem; align-items: start; }}
    .trend-link {{ color: #2563eb; text-decoration: none; font-weight: 600; white-space: nowrap; }}
    .hint {{ color: #6b7280; }}
    .up {{ color: #b91c1c; }}
    .down {{ color: #166534; }}
    .neutral {{ color: #6b7280; }}
    .chart {{ margin-top: 0.75rem; }}
  </style>
</head>
<body>
  <div class="topbar">
    <div>
      <h1>Price Tracker Dashboard</h1>
      <p>Signed in as <strong>{html.escape(display_name)}</strong></p>
    </div>
    <div class="nav">
      <a class="assistant" href="/ask">Ask Assistant</a>
      <a class="logout" href="/logout">Log out</a>
    </div>
  </div>
  <p>Manage wishlist entries and review recent scan activity.</p>
  {flash_block}
  <div class="grid">
    <section class="card">
      <h2>Select user</h2>
      <form method="get">
        <label>Search by display name or Telegram ID<input name="user_query" value="{html.escape(user_search_query)}" placeholder="Search registered Telegram users"></label>
        <button type="submit">Search</button>
      </form>
      <p><strong>Selected:</strong> {html.escape(selected_user_label)}</p>
      {selected_user_hint}
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Username</th>
            <th>Telegram ID</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {''.join(user_result_rows) if user_result_rows else '<tr><td colspan="4">No registered Telegram users found.</td></tr>'}
        </tbody>
      </table>
    </section>

    <section class="card">
      <h2>Operational summary</h2>
      <p><strong>Wishlist entries:</strong> {len(entries)}</p>
      <p><strong>Pending alerts:</strong> {pending_alerts}</p>
      {selected_user_hint}
      <h3>Recent scans</h3>
      <ul>
        {''.join(scan_rows) if scan_rows else '<li>No scan jobs yet.</li>'}
      </ul>
    </section>
  </div>

  <section class="card" style="margin-top: 1.5rem;">
    <h2>Price trends</h2>
    <p class="hint">Historical price snapshots for wishlist matches. Open a chart for the full product view.</p>
    <div class="trend-grid">
      {''.join(trend_cards) if trend_cards else '<p>No matching products with price history yet.</p>'}
    </div>
  </section>

    <section class="card" style="margin-top: 1.5rem;">
    <h2>Wishlist management</h2>
    <p class="hint">Add, update, toggle, and delete entries for the selected Telegram user.</p>
    <form method="post">
      <input type="hidden" name="action" value="add">
      <input type="hidden" name="user_id" value="{html.escape(str(selected_user_id_value))}">
      <label>URL<input name="url" required {"disabled" if selected_user is None else ""}></label>
      <label>Brand<input name="brand" required {"disabled" if selected_user is None else ""}></label>
      <label>Model<input name="model_name" required {"disabled" if selected_user is None else ""}></label>
      <label>Title<input name="title" required {"disabled" if selected_user is None else ""}></label>
      <label>Platforms to track (comma-separated)<input name="platforms" placeholder="myntra,ajio" {"disabled" if selected_user is None else ""}></label>
      <label>Sizes to track (comma-separated)<input name="sizes" placeholder="11.5,12" {"disabled" if selected_user is None else ""}></label>
      <label>Notes<textarea name="notes" rows="4" {"disabled" if selected_user is None else ""}></textarea></label>
      <button type="submit" {"disabled" if selected_user is None else ""}>Add wishlist item</button>
    </form>
    <table>
      <thead>
        <tr>
          <th>User</th>
          <th>ID</th>
          <th>Title</th>
          <th>Source platform</th>
          <th>Sizes</th>
          <th>Platforms</th>
          <th>Status</th>
          <th>Notes</th>
          <th>Trend</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows) if rows else '<tr><td colspan="10">No wishlist entries yet.</td></tr>'}
      </tbody>
    </table>
  </section>
</body>
</html>
"""


def render_trend_detail_template(
    view: TrendView,
    watchlist_rule: dict[str, object] | None = None,
    flash: str | None = None,
) -> str:
    flash_block = f'<div class="flash">{html.escape(flash)}</div>' if flash else ""
    threshold_value = (
        str(watchlist_rule["price_alert_threshold"])
        if watchlist_rule and watchlist_rule.get("price_alert_threshold") is not None
        else ""
    )
    restock_checked = (
        'checked="checked"' if watchlist_rule and watchlist_rule.get("restock_alert") else ""
    )
    notes_value = html.escape(str(watchlist_rule["notes"])) if watchlist_rule else ""
    change_text = "No comparison yet"
    change_class = "neutral"
    if view.change_amount is not None:
        if view.change_amount < 0:
            change_class = "down"
        elif view.change_amount > 0:
            change_class = "up"
        change_text = (
            f"{format_currency(view.change_amount, view.currency)} "
            f"({view.change_percentage:+.1f}%)"
            if view.change_percentage is not None
            else format_currency(view.change_amount, view.currency)
        )

    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Price Trend</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 2rem; color: #111827; }}
    .card {{ max-width: 900px; margin: 0 auto; background: #f9fafb; border: 1px solid #d1d5db; border-radius: 12px; padding: 1.5rem; }}
    .hint {{ color: #6b7280; }}
    .flash {{ padding: 0.75rem 1rem; background: #ecfdf5; border: 1px solid #34d399; border-radius: 8px; margin: 1rem 0; }}
    .back {{ display: inline-block; margin-bottom: 1rem; color: #2563eb; text-decoration: none; }}
    .meta {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.75rem; margin: 1rem 0; }}
    .metric {{ background: #fff; border: 1px solid #dbeafe; border-radius: 10px; padding: 0.85rem; }}
    .metric span {{ display: block; color: #6b7280; font-size: 0.9rem; }}
    .metric strong {{ font-size: 1.1rem; }}
    .chart {{ margin: 1rem 0 1.25rem; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: 0.6rem; text-align: left; }}
    th {{ background: #eff6ff; }}
    .up {{ color: #b91c1c; }}
    .down {{ color: #166534; }}
    .neutral {{ color: #6b7280; }}
  </style>
</head>
<body>
  <a class="back" href="/">← Back to dashboard</a>
  <div class="card">
    <h1>{html.escape(view.title)}</h1>
    <p class="hint">{html.escape(view.platform)} • <a href="{html.escape(view.product_url)}" target="_blank" rel="noreferrer">Open source URL</a></p>
    {flash_block}
    <div class="meta">
      <div class="metric"><span>Current price</span><strong>{html.escape(format_currency(view.current_price, view.currency))}</strong></div>
      <div class="metric"><span>Change</span><strong class="{change_class}">{html.escape(change_text)}</strong></div>
      <div class="metric"><span>Snapshots</span><strong>{view.snapshot_count}</strong></div>
    </div>
    <div class="chart">
      {view.chart_svg}
    </div>
    <p class="hint">This chart uses the last {view.snapshot_count} recorded price snapshots for the product.</p>
    <section class="card" style="margin-top: 1rem; background: #fff;">
      <h2>Watchlist rule</h2>
      <p class="hint">Save a price threshold or restock preference for this product. The alert engine will use these settings when the product changes.</p>
      <form method="post" action="/trend">
        <input type="hidden" name="product_id" value="{view.product_id}">
        <label>Price threshold<input name="price_alert_threshold" type="number" step="0.01" min="0" value="{html.escape(threshold_value)}" placeholder="Optional"></label>
        <label><input type="checkbox" name="restock_alert" value="true" {restock_checked}> Alert on restock</label>
        <label>Notes<textarea name="notes" rows="3">{notes_value}</textarea></label>
        <button type="submit">Save rule</button>
      </form>
      <p class="hint">Rule status: {html.escape("active" if not watchlist_rule or watchlist_rule.get("is_active") else "inactive")}</p>
    </section>
  </div>
</body>
</html>
"""


def render_assistant_template(
    user,
    question: str | None = None,
    answer: str | None = None,
    sources: list[str] | None = None,
    flash: str | None = None,
) -> str:
    flash_block = f'<div class="flash">{html.escape(flash)}</div>' if flash else ""
    sources_line = (
        f"<p class='hint'><strong>Sources:</strong> {html.escape(', '.join(sources or []))}</p>"
        if sources
        else ""
    )
    answer_block = (
        f"<div class='assistant-answer'>{html.escape(answer)}</div>" if answer else ""
    )

    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Admin Assistant</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 2rem; color: #111827; }}
    .card {{ max-width: 900px; margin: 0 auto; background: #f9fafb; border: 1px solid #d1d5db; border-radius: 12px; padding: 1.5rem; }}
    .hint {{ color: #6b7280; }}
    label {{ display: block; margin-top: 0.75rem; font-weight: 600; }}
    textarea {{ width: 100%; min-height: 110px; padding: 0.75rem; margin-top: 0.35rem; box-sizing: border-box; }}
    button {{ margin-top: 1rem; padding: 0.7rem 1rem; border: 0; border-radius: 8px; background: #7c3aed; color: #fff; cursor: pointer; }}
    .flash {{ padding: 0.75rem 1rem; background: #ecfdf5; border: 1px solid #34d399; border-radius: 8px; margin-bottom: 1rem; }}
    .assistant-answer {{ white-space: pre-wrap; background: #fff; border: 1px solid #ddd6fe; padding: 1rem; border-radius: 10px; margin-top: 1rem; }}
    .back {{ display: inline-block; margin-bottom: 1rem; color: #2563eb; text-decoration: none; }}
  </style>
</head>
<body>
  <a class="back" href="/">← Back to dashboard</a>
  <div class="card">
    <h1>Admin Assistant</h1>
    <p class="hint">Ask about wishlist counts, scan activity, pending alerts, or a specific product. The assistant only uses current tracker data.</p>
    {flash_block}
    <form method="post" action="/ask">
      <label>Question<textarea name="question" required>{html.escape(question or '')}</textarea></label>
      <button type="submit">Ask</button>
    </form>
    {answer_block}
    {sources_line}
  </div>
</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "PriceTrackerDashboard/2.0"

    def _secure_cookie(self) -> bool:
        forwarded_proto = self.headers.get("X-Forwarded-Proto", "").lower()
        return config.settings.is_production or forwarded_proto == "https"

    def _init_db(self) -> None:
        init_db()

    def _open_session(self):
        self._init_db()
        return get_session()

    def _send_html(self, body: str, status: int = 200, headers: dict[str, str] | None = None):
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        if headers:
            for key, value in headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(encoded)

    def _send_redirect(self, location: str, headers: dict[str, str] | None = None):
        self.send_response(303)
        self.send_header("Location", location)
        if headers:
            for key, value in headers.items():
                self.send_header(key, value)
        self.end_headers()

    def _send_json(self, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_form(self) -> dict[str, list[str]]:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode()
        return parse_qs(body, keep_blank_values=True)

    def _render_login(self, flash: str | None = None) -> None:
        session = self._open_session()
        try:
            bootstrap_available = len(UserRepository.list_admins(session)) == 0
        finally:
            session.close()

        self._send_html(render_login_template(flash, bootstrap_available=bootstrap_available))

    def _render_bootstrap(self, flash: str | None = None) -> None:
        self._send_html(render_bootstrap_template(flash))

    def _render_dashboard(
        self,
        flash: str | None = None,
        selected_user_id: int | None = None,
        user_search_query: str | None = None,
    ) -> None:
        session = self._open_session()
        try:
            auth_result = get_authenticated_user(session, self.headers.get("Cookie"))
            if auth_result is None:
                self._send_redirect("/login")
                return

            user, _auth_session = auth_result
            summary = build_summary(session, selected_user_id=selected_user_id, user_search_query=user_search_query)
            html_body = render_dashboard_template(summary, user, flash)
        finally:
            session.close()

        self._send_html(html_body)

    def _render_trend(self, product_id: int, flash: str | None = None) -> None:
        session = self._open_session()
        try:
            auth_result = get_authenticated_user(session, self.headers.get("Cookie"))
            if auth_result is None:
                self._send_redirect("/login")
                return

            view = build_trend_view(session, product_id)
            if view is None:
                self._send_html(
                    "<h1>Trend unavailable</h1><p>The product was not found or has no price history.</p>",
                    status=404,
                )
                return

            watchlist_rule = build_watchlist_rule_view(session, product_id)
            self._send_html(render_trend_detail_template(view, watchlist_rule, flash))
        finally:
            session.close()

    def _render_assistant(self, question: str | None = None, flash: str | None = None) -> None:
        session = self._open_session()
        try:
            auth_result = get_authenticated_user(session, self.headers.get("Cookie"))
            if auth_result is None:
                self._send_redirect("/login")
                return

            user, _auth_session = auth_result
            answer = None
            sources: list[str] | None = None
            if question:
                response = answer_question(session, question)
                answer = response.answer
                sources = response.sources
                flash = "Answered using current tracker data."
            self._send_html(render_assistant_template(user, question, answer, sources, flash))
        finally:
            session.close()

    def _require_admin(self) -> bool:
        session = self._open_session()
        try:
            _auth_result = get_authenticated_user(session, self.headers.get("Cookie"))
            if _auth_result is None:
                self._send_redirect("/login")
                return False
            return True
        finally:
            session.close()

    def do_GET(self):
        parsed_path = urlparse(self.path)
        query = parse_qs(parsed_path.query)

        if self.path == "/health":
            self._send_json({"status": "ok"})
            return

        if parsed_path.path == "/login":
            self._render_login()
            return

        if parsed_path.path == "/bootstrap":
            self._render_bootstrap()
            return

        if parsed_path.path == "/logout":
            session = self._open_session()
            try:
                auth_result = get_authenticated_user(session, self.headers.get("Cookie"))
                if auth_result is not None:
                    _user, auth_session = auth_result
                    AuthSessionRepository.revoke(session, auth_session)
            finally:
                session.close()

            secure_cookie = build_clear_session_cookie(secure=self._secure_cookie())
            self._send_redirect("/login", headers={"Set-Cookie": secure_cookie})
            return

        if parsed_path.path == "/":
            selected_user_id_value = query.get("user_id", [""])[0]
            user_search_query = query.get("user_query", [""])[0] or None
            selected_user_id = None
            if selected_user_id_value:
                try:
                    selected_user_id = int(selected_user_id_value)
                except ValueError:
                    self.send_error(400, "Invalid user_id")
                    return

            self._render_dashboard(
                selected_user_id=selected_user_id,
                user_search_query=user_search_query,
            )
            return

        if parsed_path.path == "/ask":
            self._render_assistant()
            return

        if parsed_path.path == "/trend":
            product_id_value = query.get("product_id", [""])[0]
            try:
                product_id = int(product_id_value)
            except ValueError:
                self.send_error(400, "Invalid product_id")
                return

            self._render_trend(product_id)
            return

        self.send_error(404)

    def do_POST(self):
        if self.path == "/login":
            data = self._read_form()
            username = data.get("username", [""])[0]
            password = data.get("password", [""])[0]

            session = self._open_session()
            try:
                user = authenticate_admin(session, username, password)
                if user is None:
                    self._render_login(
                        "Invalid credentials or insufficient privileges. Admin access only."
                    )
                    return

                token, _auth_session = issue_session(
                    session,
                    user,
                    ip_address=self.client_address[0] if self.client_address else None,
                    user_agent=self.headers.get("User-Agent"),
                )
            finally:
                session.close()

            secure_cookie = build_session_cookie(token, secure=self._secure_cookie())
            self._send_redirect("/", headers={"Set-Cookie": secure_cookie})
            return

        if self.path == "/bootstrap":
            data = self._read_form()
            bootstrap_token = data.get("bootstrap_token", [""])[0]
            username = data.get("username", [""])[0]
            display_name = data.get("display_name", [""])[0] or None
            password = data.get("password", [""])[0]

            if not config.settings.auth_bootstrap_token:
                self._render_bootstrap(
                    "AUTH_BOOTSTRAP_TOKEN is not configured. Set it before bootstrapping."
                )
                return

            if bootstrap_token != config.settings.auth_bootstrap_token:
                self._render_bootstrap("Invalid bootstrap token.")
                return

            session = self._open_session()
            try:
                if UserRepository.list_admins(session):
                    self._render_bootstrap(
                        "An admin already exists. Bootstrap is only for first-time setup."
                    )
                    return

                if UserRepository.get_by_username(session, username) is not None:
                    self._render_bootstrap("That username is already taken.")
                    return

                user = UserRepository.create(
                    session,
                    username=username,
                    password_hash=hash_password(
                        password, iterations=config.settings.auth_password_iterations
                    ),
                    role="admin",
                    display_name=display_name,
                )
                UserRepository.record_login(session, user)
            finally:
                session.close()

            self._send_redirect("/login")
            return

        if self.path == "/trend":
            if not self._require_admin():
                return

            data = self._read_form()
            product_id_value = data.get("product_id", [""])[0]
            try:
                product_id = int(product_id_value)
            except ValueError:
                self.send_error(400, "Invalid product_id")
                return

            session = self._open_session()
            flash_message = None
            try:
                auth_result = get_authenticated_user(session, self.headers.get("Cookie"))
                if auth_result is None:
                    self._send_redirect("/login")
                    return

                product = ProductRepository.get_by_id(session, product_id)
                if product is None:
                    self._send_html(
                        "<h1>Watchlist rule unavailable</h1><p>The product was not found.</p>",
                        status=404,
                    )
                    return

                threshold_raw = data.get("price_alert_threshold", [""])[0].strip()
                price_threshold = float(threshold_raw) if threshold_raw else None
                restock_alert = data.get("restock_alert", ["false"])[0].lower() == "true"
                notes = data.get("notes", [""])[0] or None

                WatchlistRepository.upsert(
                    session,
                    product_id=product.id,
                    price_alert_threshold=price_threshold,
                    restock_alert=restock_alert,
                    notes=notes,
                    is_active=True,
                )
            except ValueError as exc:
                flash_message = f"Invalid rule value: {exc}"
            finally:
                session.close()

            self._render_trend(
                product_id,
                flash=flash_message or "Watchlist rule saved.",
            )
            return

        if self.path == "/ask":
            if not self._require_admin():
                return

            data = self._read_form()
            question = data.get("question", [""])[0]
            self._render_assistant(question=question)
            return

        if not self._require_admin():
            return

        data = self._read_form()
        action = data.get("action", [""])[0]

        selected_user_id: int | None = None
        session = self._open_session()
        try:
            auth_result = get_authenticated_user(session, self.headers.get("Cookie"))
            if auth_result is None:
                self._send_redirect("/login")
                return

            _user, _auth_session = auth_result
            selected_user_id_raw = data.get("user_id", [""])[0]
            if selected_user_id_raw:
                try:
                    selected_user_id = int(selected_user_id_raw)
                except ValueError:
                    flash = "Invalid user selection."

            if action == "add":
                if selected_user_id is None:
                    flash = "Select a registered Telegram user before adding an item."
                else:
                    selected_user = UserRepository.get_by_id(session, selected_user_id)
                    if selected_user is None:
                        flash = "Selected Telegram user not found."
                    else:
                        WishlistService.add_from_url(
                            session,
                            url=data.get("url", [""])[0],
                            brand=data.get("brand", [""])[0],
                            model_name=data.get("model_name", [""])[0],
                            title=data.get("title", [""])[0],
                            platforms_to_track=parse_csv(data.get("platforms", [None])[0]),
                            size_scope=parse_csv(data.get("sizes", [None])[0]),
                            notes=data.get("notes", [""])[0] or None,
                            user_id=selected_user.id,
                        )
                        flash = (
                            f"Wishlist item added for {selected_user.display_name or selected_user.username}."
                        )
            elif action == "toggle":
                if selected_user_id is None:
                    flash = "Invalid user selection."
                else:
                    enabled = data.get("enabled", ["false"])[0].lower() == "true"
                    updated = WishlistService.set_active(
                        session,
                        data.get("url", [""])[0],
                        selected_user_id,
                        enabled,
                    )
                    flash = (
                        "Wishlist item enabled."
                        if updated and enabled
                        else "Wishlist item disabled." if updated else "Wishlist item not found."
                    )
            elif action == "delete":
                if selected_user_id is None:
                    flash = "Invalid user selection."
                else:
                    deleted = WishlistService.delete(
                        session,
                        data.get("url", [""])[0],
                        selected_user_id,
                    )
                    flash = "Wishlist item deleted." if deleted else "Wishlist item not found."
            else:
                flash = "Unknown action."
        except Exception as exc:
            logger.exception("dashboard_action_failed", error=str(exc))
            flash = f"Failed to process request: {exc}"
        finally:
            session.close()

        self._render_dashboard(flash=flash, selected_user_id=selected_user_id)

    def log_message(self, format, *args):
        logger.info(format % args)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    init_db()
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    logger.info("dashboard_started", host=args.host, port=args.port)
    server.serve_forever()


if __name__ == "__main__":
    main()
