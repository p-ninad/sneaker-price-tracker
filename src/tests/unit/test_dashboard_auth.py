import base64
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from app.dashboard import DashboardHandler


@pytest.fixture
def dashboard_server(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "s3cr3t")

    server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield server

    server.shutdown()
    thread.join(timeout=2)


def _fetch(server, path, headers=None):
    url = f"http://127.0.0.1:{server.server_address[1]}{path}"
    request = urllib.request.Request(url, headers=headers or {})

    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def test_dashboard_requires_basic_auth_when_configured(dashboard_server):
    # Health endpoint is public (needed for reverse proxy health checks)
    status, body = _fetch(dashboard_server, "/health")
    assert status == 200
    assert json.loads(body) == {"status": "ok"}

    # Main dashboard requires auth
    status, body = _fetch(dashboard_server, "/")
    assert status == 401
    assert body == "Unauthorized"


def test_dashboard_accepts_valid_basic_auth(dashboard_server):
    auth_header = {
        "Authorization": "Basic "
        + base64.b64encode(b"admin:s3cr3t").decode("ascii")
    }

    status, body = _fetch(dashboard_server, "/health", headers=auth_header)

    assert status == 200
    assert json.loads(body) == {"status": "ok"}
