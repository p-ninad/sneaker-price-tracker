"""Web authentication helpers for the dashboard."""

from __future__ import annotations

from datetime import datetime, timedelta
from http.cookies import SimpleCookie

from app.auth.tokens import generate_session_token
import app.config as config
from app.database.models import AuthSession, User
from app.database.repository import AuthSessionRepository, UserRepository


def parse_cookie_header(cookie_header: str | None) -> SimpleCookie:
    """Parse a Cookie header into a SimpleCookie object."""
    cookie = SimpleCookie()
    if cookie_header:
        cookie.load(cookie_header)
    return cookie


def get_cookie_value(cookie_header: str | None, name: str) -> str | None:
    """Return a cookie value from a Cookie header."""
    cookie = parse_cookie_header(cookie_header)
    morsel = cookie.get(name)
    if morsel is None:
        return None
    value = morsel.value.strip()
    return value or None


def build_session_cookie(token: str, *, secure: bool) -> str:
    """Build a Set-Cookie header value for the auth session."""
    cookie = SimpleCookie()
    cookie[config.settings.auth_session_cookie_name] = token
    cookie[config.settings.auth_session_cookie_name]["path"] = "/"
    cookie[config.settings.auth_session_cookie_name]["httponly"] = True
    cookie[config.settings.auth_session_cookie_name]["samesite"] = "Lax"
    cookie[config.settings.auth_session_cookie_name]["max-age"] = str(
        int(config.settings.auth_session_ttl_hours * 3600)
    )
    if secure:
        cookie[config.settings.auth_session_cookie_name]["secure"] = True

    return cookie.output(header="").strip()


def build_clear_session_cookie(*, secure: bool) -> str:
    """Build a Set-Cookie header that clears the auth session."""
    cookie = SimpleCookie()
    cookie[config.settings.auth_session_cookie_name] = ""
    cookie[config.settings.auth_session_cookie_name]["path"] = "/"
    cookie[config.settings.auth_session_cookie_name]["httponly"] = True
    cookie[config.settings.auth_session_cookie_name]["samesite"] = "Lax"
    cookie[config.settings.auth_session_cookie_name]["max-age"] = "0"
    cookie[config.settings.auth_session_cookie_name]["expires"] = "Thu, 01 Jan 1970 00:00:00 GMT"
    if secure:
        cookie[config.settings.auth_session_cookie_name]["secure"] = True

    return cookie.output(header="").strip()


def issue_session(
    session,
    user: User,
    *,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, AuthSession]:
    """Create and persist a new session token for a user."""
    token = generate_session_token()
    expires_at = datetime.utcnow() + timedelta(hours=config.settings.auth_session_ttl_hours)
    auth_session = AuthSessionRepository.create(
        session,
        user_id=user.id,
        session_token=token,
        expires_at=expires_at,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return token, auth_session


def get_authenticated_user(session, cookie_header: str | None) -> tuple[User, AuthSession] | None:
    """Resolve the current authenticated user from a cookie header."""
    session_token = get_cookie_value(cookie_header, config.settings.auth_session_cookie_name)
    if not session_token:
        return None

    auth_session = AuthSessionRepository.get_by_token(session, session_token)
    if auth_session is None:
        return None

    user = auth_session.user
    if user is None or not user.is_active or user.role != "admin":
        return None

    AuthSessionRepository.touch(session, auth_session)
    return user, auth_session


def authenticate_admin(session, username: str, password: str) -> User | None:
    """Return an active admin user when credentials are valid."""
    user = UserRepository.get_by_username(session, username)
    if user is None or user.role != "admin":
        return None

    from app.auth.passwords import verify_password

    if not verify_password(password, user.password_hash):
        return None

    UserRepository.record_login(session, user)
    return user
