"""Local dashboard for managing wishlist entries."""

import argparse
import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from app.database.db import get_session, init_db
from app.database.models import ScanJob
from app.database.repository import AlertRepository
from app.services.wishlist import WishlistService
from app.utils.logger import get_logger

logger = get_logger(__name__)


def parse_csv(value: str | None) -> list[str] | None:
    if value is None:
        return None

    parsed = [item.strip() for item in value.split(",") if item.strip()]
    return parsed or None


def build_summary(session) -> dict:
    entries = WishlistService.get_all(session)
    pending_alerts = AlertRepository.get_unnotified(session, limit=100)
    recent_scans = (
        session.query(ScanJob)
        .order_by(ScanJob.started_at.desc())
        .limit(5)
        .all()
    )

    return {
        "entries": entries,
        "pending_alerts": len(pending_alerts),
        "recent_scans": recent_scans,
    }


def render_template(summary: dict, flash: str | None = None) -> str:
    entries = summary["entries"]
    pending_alerts = summary["pending_alerts"]
    recent_scans = summary["recent_scans"]

    rows = []
    for entry in entries:
        status = "active" if entry.is_active else "inactive"
        sizes = WishlistService.get_size_scope(entry)
        platforms = WishlistService.get_platforms_to_track(entry)
        rows.append(
            f"""
            <tr>
              <td>{html.escape(str(entry.id))}</td>
              <td>{html.escape(entry.title)}</td>
              <td>{html.escape(entry.platform)}</td>
              <td>{html.escape(', '.join(sizes))}</td>
              <td>{html.escape(', '.join(platforms))}</td>
              <td>{html.escape(status)}</td>
              <td>{html.escape(entry.notes or '')}</td>
              <td>
                <form method="post" style="display:inline">
                  <input type="hidden" name="action" value="toggle">
                  <input type="hidden" name="url" value="{html.escape(entry.source_url)}">
                  <input type="hidden" name="enabled" value="{ 'false' if entry.is_active else 'true' }">
                  <button type="submit">{ 'Disable' if entry.is_active else 'Enable' }</button>
                </form>
                <form method="post" style="display:inline">
                  <input type="hidden" name="action" value="delete">
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

    flash_block = f'<div class="flash">{html.escape(flash)}</div>' if flash else ""

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
    table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: 0.75rem; text-align: left; vertical-align: top; }}
    th {{ background: #eff6ff; }}
    .flash {{ padding: 0.75rem 1rem; background: #ecfdf5; border: 1px solid #34d399; border-radius: 8px; margin-bottom: 1rem; }}
    ul {{ padding-left: 1rem; }}
  </style>
</head>
<body>
  <h1>Price Tracker Dashboard</h1>
  <p>Manage wishlist entries and review recent scan activity.</p>
  {flash_block}
  <div class="grid">
    <section class="card">
      <h2>Add wishlist item</h2>
      <form method="post">
        <input type="hidden" name="action" value="add">
        <label>URL<input name="url" required></label>
        <label>Brand<input name="brand" required></label>
        <label>Model<input name="model_name" required></label>
        <label>Title<input name="title" required></label>
        <label>Platforms to track (comma-separated)<input name="platforms" placeholder="myntra,ajio"></label>
        <label>Sizes to track (comma-separated)<input name="sizes" placeholder="11.5,12"></label>
        <label>Notes<textarea name="notes" rows="4"></textarea></label>
        <button type="submit">Add wishlist item</button>
      </form>
    </section>

    <section class="card">
      <h2>Operational summary</h2>
      <p><strong>Wishlist entries:</strong> {len(entries)}</p>
      <p><strong>Pending alerts:</strong> {pending_alerts}</p>
      <h3>Recent scans</h3>
      <ul>
        {''.join(scan_rows) if scan_rows else '<li>No scan jobs yet.</li>'}
      </ul>
    </section>
  </div>

  <section class="card" style="margin-top: 1.5rem;">
    <h2>Wishlist management</h2>
    <table>
      <thead>
        <tr>
          <th>ID</th>
          <th>Title</th>
          <th>Source platform</th>
          <th>Sizes</th>
          <th>Platforms</th>
          <th>Status</th>
          <th>Notes</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows) if rows else '<tr><td colspan="8">No wishlist entries yet.</td></tr>'}
      </tbody>
    </table>
  </section>
</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "PriceTrackerDashboard/1.0"

    def do_GET(self):
        if self.path == "/":
            self._render_page()
            return

        if self.path == "/health":
            self._send_json({"status": "ok"})
            return

        self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode()
        data = parse_qs(body, keep_blank_values=True)
        action = data.get("action", [""])[0]

        session = get_session()
        try:
            if action == "add":
                WishlistService.add_from_url(
                    session,
                    url=data.get("url", [""])[0],
                    brand=data.get("brand", [""])[0],
                    model_name=data.get("model_name", [""])[0],
                    title=data.get("title", [""])[0],
                    platforms_to_track=parse_csv(data.get("platforms", [None])[0]),
                    size_scope=parse_csv(data.get("sizes", [None])[0]),
                    notes=data.get("notes", [""])[0] or None,
                )
                flash = "Wishlist item added."
            elif action == "toggle":
                enabled = data.get("enabled", ["false"])[0].lower() == "true"
                updated = WishlistService.set_active(session, data.get("url", [""])[0], enabled)
                flash = f"Wishlist item {'enabled' if updated and enabled else 'disabled' if updated else 'not found'}."
            elif action == "delete":
                deleted = WishlistService.delete(session, data.get("url", [""])[0])
                flash = "Wishlist item deleted." if deleted else "Wishlist item not found."
            else:
                flash = "Unknown action."
        except Exception as exc:
            logger.exception("dashboard_action_failed", error=str(exc))
            flash = f"Failed to process request: {exc}"
        finally:
            session.close()

        self._render_page(flash=flash)

    def _render_page(self, flash: str | None = None):
        session = get_session()
        try:
            summary = build_summary(session)
            html_body = render_template(summary, flash)
        finally:
            session.close()

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html_body.encode("utf-8"))

    def _send_json(self, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
