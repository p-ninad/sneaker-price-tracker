from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from app import config as app_config
from app.dashboard import DashboardHandler


@pytest.fixture
def dashboard_server(tmp_path, monkeypatch):
    database_path = tmp_path / "dashboard.db"
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("AUTH_BOOTSTRAP_TOKEN", "bootstrap-secret")
    monkeypatch.setenv("AUTH_SESSION_COOKIE_NAME", "price_tracker_session")
    app_config.settings = app_config.Settings()

    from app.database import db as app_db

    app_db._ENGINE = None
    app_db._SESSION_FACTORY = None

    server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield server

    server.shutdown()
    thread.join(timeout=2)


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open(server, path, method="GET", data=None, headers=None):
    url = f"http://127.0.0.1:{server.server_address[1]}{path}"
    request_data = None
    if data is not None:
        request_data = urllib.parse.urlencode(data).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=request_data,
        method=method,
        headers=headers or {},
    )

    opener = urllib.request.build_opener(NoRedirectHandler())
    try:
        with opener.open(request) as response:
            return response.status, response.headers, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read().decode()


def _cookie_from_headers(headers):
    set_cookie = headers.get("Set-Cookie")
    if not set_cookie:
        return None
    return set_cookie.split(";", 1)[0]


def _bootstrap_and_login(server):
    _open(
        server,
        "/bootstrap",
        method="POST",
        data={
            "bootstrap_token": "bootstrap-secret",
            "username": "admin",
            "display_name": "Admin User",
            "password": "secret",
        },
    )

    status, headers, _ = _open(
        server,
        "/login",
        method="POST",
        data={"username": "admin", "password": "secret"},
    )
    assert status == 303
    cookie = _cookie_from_headers(headers)
    assert cookie is not None
    return cookie


def test_login_page_and_bootstrap_flow(dashboard_server):
    status, _, body = _open(dashboard_server, "/login")
    assert status == 200
    assert "Admin Login" in body
    assert "Bootstrap the first admin account" in body

    status, _, body = _open(
        dashboard_server,
        "/bootstrap",
        method="POST",
        data={
            "bootstrap_token": "wrong",
            "username": "admin",
            "display_name": "Admin User",
            "password": "secret",
        },
    )
    assert status == 200
    assert "Invalid bootstrap token." in body

    status, headers, body = _open(
        dashboard_server,
        "/bootstrap",
        method="POST",
        data={
            "bootstrap_token": "bootstrap-secret",
            "username": "admin",
            "display_name": "Admin User",
            "password": "secret",
        },
    )
    assert status == 303
    assert headers.get("Location") == "/login"

    status, _, body = _open(dashboard_server, "/login")
    assert status == 200
    assert "The admin portal is already initialized." in body


def test_admin_login_logout_and_dashboard_access(dashboard_server):
    _open(
        dashboard_server,
        "/bootstrap",
        method="POST",
        data={
            "bootstrap_token": "bootstrap-secret",
            "username": "admin",
            "display_name": "Admin User",
            "password": "secret",
        },
    )

    status, _, body = _open(
        dashboard_server,
        "/login",
        method="POST",
        data={"username": "admin", "password": "wrong"},
    )
    assert status == 200
    assert "Invalid credentials or insufficient privileges" in body

    status, headers, _ = _open(
        dashboard_server,
        "/login",
        method="POST",
        data={"username": "admin", "password": "secret"},
    )
    assert status == 303
    assert headers.get("Location") == "/"

    cookie = _cookie_from_headers(headers)
    assert cookie is not None

    status, _, body = _open(dashboard_server, "/", headers={"Cookie": cookie})
    assert status == 200
    assert "Price Tracker Dashboard" in body
    assert "Signed in as" in body

    status, headers, _ = _open(
        dashboard_server,
        "/logout",
        headers={"Cookie": cookie},
    )
    assert status == 303
    assert headers.get("Location") == "/login"

    status, _, _ = _open(dashboard_server, "/", headers={"Cookie": cookie})
    assert status == 303


def test_dashboard_add_wishlist_item_is_owned_by_signed_in_user(dashboard_server):
    _open(
        dashboard_server,
        "/bootstrap",
        method="POST",
        data={
            "bootstrap_token": "bootstrap-secret",
            "username": "admin",
            "display_name": "Admin User",
            "password": "secret",
        },
    )

    status, headers, _ = _open(
        dashboard_server,
        "/login",
        method="POST",
        data={"username": "admin", "password": "secret"},
    )
    assert status == 303
    cookie = _cookie_from_headers(headers)
    assert cookie is not None

    from app.auth.passwords import hash_password
    from app.database.db import get_session
    from app.database.repository import UserRepository

    session = get_session()
    try:
        telegram_user = UserRepository.create(
            session,
            username="telegram_user",
            password_hash=hash_password("secret", iterations=1000),
            role="user",
            telegram_user_id="333",
            telegram_chat_id="444",
        )
        telegram_user_id = telegram_user.id
    finally:
        session.close()

    _open(
        dashboard_server,
        "/",
        method="POST",
        headers={"Cookie": cookie},
            data={
                "action": "add",
                "user_id": str(telegram_user_id),
                "url": "https://www.myntra.com/p/1",
                "brand": "Nike",
                "model_name": "Air Max",
                "title": "Nike Air Max",
            },
    )

    from app.services.wishlist import WishlistService

    session = get_session()
    try:
        alerts = WishlistService.get_all_for_user(session, telegram_user_id)
        assert len(alerts) == 1
        assert alerts[0].user_id == telegram_user_id
    finally:
        session.close()


def test_regular_user_cannot_login_to_web_portal(dashboard_server):
    _open(
        dashboard_server,
        "/bootstrap",
        method="POST",
        data={
            "bootstrap_token": "bootstrap-secret",
            "username": "admin",
            "display_name": "Admin User",
            "password": "secret",
        },
    )

    # Seed a non-admin user directly through the repository to verify portal rejection.
    from app.auth.passwords import hash_password
    from app.database.db import get_session, init_db
    from app.database.repository import UserRepository

    init_db()
    db_session = get_session()
    try:
        UserRepository.create(
            db_session,
            username="member",
            password_hash=hash_password("secret", iterations=1000),
            role="user",
        )
    finally:
        db_session.close()

    status, _, body = _open(
        dashboard_server,
        "/login",
        method="POST",
        data={"username": "member", "password": "secret"},
    )
    assert status == 200
    assert "Admin access only" in body


def test_dashboard_toggles_telegram_connectivity(dashboard_server):
    cookie = _bootstrap_and_login(dashboard_server)

    status, _, body = _open(dashboard_server, "/", headers={"Cookie": cookie})
    assert status == 200
    assert "Telegram connectivity" in body
    assert "Enabled" in body

    status, _, body = _open(
        dashboard_server,
        "/",
        method="POST",
        headers={"Cookie": cookie},
        data={"action": "telegram_connectivity", "enabled": "false"},
    )

    assert status == 200
    assert "Telegram connectivity disabled." in body
    assert "Disabled" in body

    from app.database.db import get_session
    from app.database.repository import AppSettingRepository

    session = get_session()
    try:
        assert AppSettingRepository.telegram_connectivity_enabled(session) is False
    finally:
        session.close()


def test_dashboard_shows_discovery_monitors_and_results(dashboard_server):
    cookie = _bootstrap_and_login(dashboard_server)

    from app.auth.passwords import hash_password
    from app.database.db import get_session
    from app.database.repository import (
        BrandMonitorRepository,
        BrandMonitorScanRepository,
        BrandMonitorScanResultRepository,
        PlatformRepository,
        ProductRepository,
        UserRepository,
    )
    from app.services.brand_monitor import BrandMonitorService

    session = get_session()
    try:
        telegram_user = UserRepository.create(
            session,
            username="discovery_user",
            password_hash=hash_password("secret", iterations=1000),
            role="user",
            telegram_user_id="933",
            telegram_chat_id="944",
        )
        monitor = BrandMonitorService.add_monitor(
            session,
            user_id=telegram_user.id,
            platform="myntra",
            brand="Adidas Originals",
            query_terms=["sneakers"],
            size_scope=["10"],
        )
        platform = PlatformRepository.create(
            session,
            name="myntra",
            display_name="Myntra",
            base_url="https://www.myntra.com",
        )
        product = ProductRepository.create_or_update(
            session,
            platform_id=platform.id,
            product_url="https://www.myntra.com/p/samba",
            platform_product_id="samba",
            brand="Adidas",
            model_name="Samba",
            title="Adidas Originals Samba Sneakers",
            listed_price=10999.0,
            discounted_price=7999.0,
            discount_percentage=27.0,
            in_stock=True,
            sizes_available='["10"]',
        )
        scan = BrandMonitorScanRepository.create(
            session,
            monitor_id=monitor.id,
            query="Adidas Originals sneakers",
        )
        BrandMonitorScanRepository.mark_complete(
            session,
            scan,
            status="success",
            products_found=1,
            products_matched=1,
            new_products=1,
        )
        BrandMonitorScanResultRepository.create(
            session,
            scan_id=scan.id,
            monitor_id=monitor.id,
            product_id=product.id,
            is_new=True,
            matched_sizes='["10"]',
            current_price=7999.0,
            discount_percentage=27.0,
        )
        user_id = telegram_user.id
    finally:
        session.close()

    status, _, body = _open(
        dashboard_server,
        f"/?user_id={user_id}",
        headers={"Cookie": cookie},
    )

    assert status == 200
    assert "Discovery monitors" in body
    assert "Adidas Originals" in body
    assert "Discovery results" in body
    assert "Adidas Originals Samba Sneakers" in body
    assert "https://www.myntra.com/p/samba" in body
    assert "10" in body
    assert "Yes" in body

    status, _, body = _open(
        dashboard_server,
        "/",
        method="POST",
        headers={"Cookie": cookie},
        data={
            "action": "toggle_monitor",
            "user_id": str(user_id),
            "monitor_id": str(monitor.id),
            "enabled": "false",
        },
    )

    assert status == 200
    assert "Discovery monitor paused." in body

    session = get_session()
    try:
        refreshed = BrandMonitorRepository.get_for_user(session, user_id, monitor.id)
        assert refreshed is not None
        assert refreshed.is_active is False
    finally:
        session.close()


def test_dashboard_manual_scan_results_track_and_ignore(dashboard_server):
    cookie = _bootstrap_and_login(dashboard_server)

    from app.auth.passwords import hash_password
    from app.database.db import get_session
    from app.database.repository import (
        ManualDiscoveryResultRepository,
        ManualDiscoveryScanRepository,
        PlatformRepository,
        ProductIgnoreRepository,
        ProductRepository,
        UserRepository,
    )
    from app.services.manual_discovery import ManualDiscoveryService
    from app.services.wishlist import WishlistService

    session = get_session()
    try:
        telegram_user = UserRepository.create(
            session,
            username="manual_scan_user",
            password_hash=hash_password("secret", iterations=1000),
            role="user",
            telegram_user_id="1233",
            telegram_chat_id="1244",
        )
        platform = PlatformRepository.create(
            session,
            name="myntra",
            display_name="Myntra",
            base_url="https://www.myntra.com",
        )
        product = ProductRepository.create_or_update(
            session,
            platform_id=platform.id,
            product_url="https://www.myntra.com/sneakers/adidas-samba/123456/buy",
            platform_product_id="123456",
            brand="Adidas",
            model_name="Samba",
            title="Adidas Originals Samba Sneakers",
            listed_price=10999.0,
            discounted_price=7999.0,
            discount_percentage=27.0,
            in_stock=True,
            sizes_available='["UK 10"]',
            image_url="https://example.com/samba.jpg",
        )
        scan = ManualDiscoveryScanRepository.create(
            session,
            user_id=telegram_user.id,
            platform="myntra",
            brand_filters=ManualDiscoveryService.serialize_values(["Adidas Originals"]),
            size_filters=ManualDiscoveryService.serialize_values(["UK 10"]),
        )
        result = ManualDiscoveryResultRepository.create(
            session,
            scan_id=scan.id,
            product_id=product.id,
            matched_brand="Adidas Originals",
            matched_sizes='["UK 10"]',
            current_price=7999.0,
            discount_percentage=27.0,
        )
        user_id = telegram_user.id
        scan_id = scan.id
        result_id = result.id
        platform_id = platform.id
    finally:
        session.close()

    status, _, body = _open(
        dashboard_server,
        f"/?user_id={user_id}",
        headers={"Cookie": cookie},
    )
    assert status == 200
    assert "Manual discovery scan" in body

    status, _, body = _open(
        dashboard_server,
        f"/api/manual-scan/results?scan_id={scan_id}&page=1",
        headers={"Cookie": cookie},
    )
    payload = json.loads(body)
    assert status == 200
    assert payload["ok"] is True
    assert payload["total"] == 1
    assert payload["results"][0]["title"] == "Adidas Originals Samba Sneakers"

    status, _, body = _open(
        dashboard_server,
        "/api/manual-scan/track",
        method="POST",
        headers={"Cookie": cookie},
        data={"result_id": str(result_id)},
    )
    assert status == 200
    assert json.loads(body)["ok"] is True

    session = get_session()
    try:
        entries = WishlistService.get_all_for_user(session, user_id)
        assert len(entries) == 1
        assert entries[0].source_url == "https://www.myntra.com/sneakers/adidas-samba/123456/buy"
    finally:
        session.close()

    status, _, body = _open(
        dashboard_server,
        "/api/manual-scan/ignore",
        method="POST",
        headers={"Cookie": cookie},
        data={"result_id": str(result_id)},
    )
    assert status == 200
    assert json.loads(body)["ok"] is True

    session = get_session()
    try:
        assert ProductIgnoreRepository.is_ignored(session, platform_id, "123456") is True
    finally:
        session.close()

    status, _, body = _open(
        dashboard_server,
        f"/api/manual-scan/results?scan_id={scan_id}&page=1",
        headers={"Cookie": cookie},
    )
    payload = json.loads(body)
    assert status == 200
    assert payload["total"] == 0
