"""
Integration checks for the reverse proxy and dashboard auth wiring.
"""

import inspect


def test_dashboard_routes_include_login_bootstrap_logout():
    from app.dashboard import DashboardHandler

    source = inspect.getsource(DashboardHandler.do_GET) + inspect.getsource(
        DashboardHandler.do_POST
    )

    assert '"/login"' in source
    assert '"/bootstrap"' in source
    assert '"/logout"' in source


def test_dashboard_health_endpoint_remains_public():
    from app.dashboard import DashboardHandler

    source = inspect.getsource(DashboardHandler.do_GET)

    health_pos = source.find('"/health"')
    login_pos = source.find('"/login"')
    assert health_pos != -1
    assert login_pos != -1
    assert health_pos < login_pos


def test_caddy_domain_environment_variable():
    """Verify Caddyfile respects CADDY_DOMAIN environment variable."""
    with open("Caddyfile", "r", encoding="utf-8") as file_handle:
        content = file_handle.read()

    assert "{$CADDY_DOMAIN:localhost}" in content
    assert "reverse_proxy dashboard:8000" in content
    assert "X-Frame-Options" in content
    assert "Content-Security-Policy" in content


def test_docker_compose_dashboard_configuration():
    """Verify docker-compose still wires the dashboard service."""
    with open("docker-compose.yml", "r", encoding="utf-8") as file_handle:
        content = file_handle.read()

    assert "dashboard:" in content
    assert "expose:\n      - \"8000\"" in content or "expose:\n      - \"8000\"" in content
    assert "caddy:" in content
    assert "- \"80:80\"" in content
    assert "- \"443:443\"" in content


def test_env_example_documents_bootstrap_token():
    """Verify .env.example documents the bootstrap secret."""
    with open(".env.example", "r", encoding="utf-8") as file_handle:
        content = file_handle.read()

    assert "AUTH_BOOTSTRAP_TOKEN" in content
    assert "AUTH_SESSION_COOKIE_NAME" in content
    assert "AUTH_SESSION_TTL_HOURS" in content
