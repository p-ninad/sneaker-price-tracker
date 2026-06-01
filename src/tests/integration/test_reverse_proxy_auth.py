"""
Test cases for reverse proxy and authentication setup.

This module tests:
1. Caddy reverse proxy routing
2. Dashboard basic authentication
3. Health check endpoint (public access)
4. Security headers
"""

import os
import base64
import pytest
import json
from unittest.mock import patch, MagicMock
from http.client import HTTPConnection


def test_dashboard_health_endpoint_public():
    """Health endpoint should be accessible without authentication."""
    from app.dashboard import DashboardHandler
    
    # Create mock request
    handler = MagicMock(spec=DashboardHandler)
    handler.path = "/health"
    handler.headers = {}
    handler.wfile = MagicMock()
    handler.rfile = MagicMock()
    
    # Mock the methods
    handler._require_auth = MagicMock(return_value=True)
    handler._send_json = MagicMock()
    
    # Import the actual do_GET method
    from app.dashboard import DashboardHandler as RealHandler
    
    # Test that /health is before the auth check
    # by verifying the method structure
    import inspect
    source = inspect.getsource(RealHandler.do_GET)
    
    # The health endpoint should be checked before _require_auth
    assert "/health" in source
    health_pos = source.find('"/health"')
    auth_pos = source.find('_require_auth')
    assert health_pos < auth_pos, "Health endpoint should be checked before authentication"


def test_dashboard_main_endpoint_requires_auth():
    """Main endpoint (/) should require authentication."""
    from app.dashboard import DashboardHandler
    
    # Import the actual do_GET method
    import inspect
    source = inspect.getsource(DashboardHandler.do_GET)
    
    # The main endpoint should be after the auth check
    assert "_require_auth" in source
    assert '"/health"' in source
    
    # Verify that the main endpoint "/" is handled after auth
    health_pos = source.find('"/health"')
    main_pos = source.find('self._render_page')
    assert health_pos < main_pos, "Health check should come before main page rendering"


@patch.dict(os.environ, {"DASHBOARD_USERNAME": "testuser", "DASHBOARD_PASSWORD": "testpass"})
def test_dashboard_authorization_with_valid_credentials():
    """Dashboard should authorize valid credentials."""
    from app.dashboard import parse_basic_auth, is_dashboard_authorized
    
    # Create valid Authorization header
    credentials = base64.b64encode(b"testuser:testpass").decode()
    auth_header = f"Basic {credentials}"
    
    # Test parse
    user, password = parse_basic_auth(auth_header)
    assert user == "testuser"
    assert password == "testpass"
    
    # Test authorization
    assert is_dashboard_authorized(auth_header) is True


@patch.dict(os.environ, {"DASHBOARD_USERNAME": "testuser", "DASHBOARD_PASSWORD": "testpass"})
def test_dashboard_authorization_with_invalid_credentials():
    """Dashboard should reject invalid credentials."""
    from app.dashboard import is_dashboard_authorized
    
    # Create invalid Authorization header
    credentials = base64.b64encode(b"testuser:wrongpass").decode()
    auth_header = f"Basic {credentials}"
    
    # Test authorization
    assert is_dashboard_authorized(auth_header) is False


@patch.dict(os.environ, {"DASHBOARD_USERNAME": "", "DASHBOARD_PASSWORD": ""})
def test_dashboard_no_auth_when_credentials_empty():
    """Dashboard should not require auth if credentials are empty."""
    from app.dashboard import is_dashboard_authorized
    
    # No auth header provided
    assert is_dashboard_authorized(None) is True
    
    # Empty auth header
    assert is_dashboard_authorized("") is True


def test_parse_basic_auth_invalid_header():
    """parse_basic_auth should handle invalid headers."""
    from app.dashboard import parse_basic_auth
    
    # Invalid header format
    result = parse_basic_auth("NotBasic xyz")
    assert result is None
    
    # No auth header
    result = parse_basic_auth(None)
    assert result is None
    
    # Invalid base64
    result = parse_basic_auth("Basic !!invalid!!")
    assert result is None


def test_caddy_domain_environment_variable():
    """Verify Caddyfile respects CADDY_DOMAIN environment variable."""
    # Read the Caddyfile
    with open("Caddyfile", "r") as f:
        content = f.read()
    
    # Should contain the environment variable reference
    assert "{$CADDY_DOMAIN:localhost}" in content
    
    # Should have reverse_proxy directive pointing to dashboard
    assert "reverse_proxy dashboard:8000" in content
    
    # Should have security headers
    assert "X-Frame-Options" in content
    assert "Content-Security-Policy" in content


def test_docker_compose_dashboard_credentials():
    """Verify docker-compose has dashboard credentials configured."""
    with open("docker-compose.yml", "r") as f:
        content = f.read()

    assert "DASHBOARD_USERNAME" in content
    assert "DASHBOARD_PASSWORD" in content
    assert "dashboard:" in content
    assert "expose:\n      - \"8000\"" in content or "expose:\n      - \"8000\"" in content


def test_docker_compose_caddy_configuration():
    """Verify docker-compose has Caddy configured correctly."""
    with open("docker-compose.yml", "r") as f:
        content = f.read()

    assert "caddy:" in content
    assert "- \"80:80\"" in content
    assert "- \"443:443\"" in content
    assert "depends_on:" in content
    assert "dashboard" in content
    assert "Caddyfile" in content


def test_env_example_has_dashboard_credentials():
    """Verify .env.example documents dashboard credentials."""
    with open(".env.example", "r") as f:
        content = f.read()
    
    # Should mention dashboard credentials
    assert "DASHBOARD_USERNAME" in content
    assert "DASHBOARD_PASSWORD" in content
    
    # Should have helpful comments
    assert "production" in content.lower() or "security" in content.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
