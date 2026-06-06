from datetime import datetime, timedelta

from app.auth.passwords import hash_password, needs_rehash, verify_password
from app.auth.tokens import generate_session_token, hash_token
from app.database.repository import AuthSessionRepository, UserRepository


def test_password_hash_round_trip():
    password_hash = hash_password("correct horse battery staple", iterations=1000)

    assert verify_password("correct horse battery staple", password_hash) is True
    assert verify_password("wrong password", password_hash) is False
    assert needs_rehash(password_hash, target_iterations=500) is False
    assert needs_rehash(password_hash, target_iterations=5000) is True


def test_user_repository_create_and_lookup(test_session):
    user = UserRepository.create(
        test_session,
        username="Admin",
        password_hash=hash_password("secret", iterations=1000),
        role="ADMIN",
        display_name="Admin User",
    )

    assert user.username == "admin"
    assert user.role == "admin"
    assert UserRepository.get_by_username(test_session, "ADMIN").id == user.id
    assert UserRepository.list_admins(test_session)[0].id == user.id


def test_user_repository_telegram_identity_and_login(test_session):
    user = UserRepository.create(
        test_session,
        username="alice",
        password_hash=hash_password("secret", iterations=1000),
    )

    UserRepository.set_telegram_identity(
        test_session,
        user,
        telegram_user_id="123456",
        telegram_chat_id="654321",
    )
    UserRepository.record_login(test_session, user)

    refreshed = UserRepository.get_by_telegram_user_id(test_session, "123456")
    assert refreshed is not None
    assert refreshed.id == user.id
    assert refreshed.telegram_chat_id == "654321"
    assert refreshed.last_login_at is not None


def test_user_repository_telegram_search_and_wishlist_scoping(test_session):
    telegram_user = UserRepository.get_or_create_telegram_user(
        test_session,
        telegram_user_id="123",
        telegram_chat_id="456",
        display_name="Telegram User",
    )
    other_telegram_user = UserRepository.get_or_create_telegram_user(
        test_session,
        telegram_user_id="789",
        telegram_chat_id="012",
        display_name="Another User",
    )

    from app.services.wishlist import WishlistService

    entry = WishlistService.add_from_url(
        test_session,
        url="https://www.myntra.com/p/1",
        brand="Nike",
        model_name="Air Max",
        title="Nike Air Max",
        user_id=telegram_user.id,
    )
    assert entry.user_id == telegram_user.id

    by_name = UserRepository.search_telegram_users(test_session, "telegram")
    assert [user.id for user in by_name] == [telegram_user.id]

    by_id = UserRepository.search_telegram_users(test_session, "123")
    assert [user.id for user in by_id] == [telegram_user.id]

    assert WishlistService.get_all_for_user(test_session, telegram_user.id)[0].id == entry.id
    assert WishlistService.get_all_for_user(test_session, other_telegram_user.id) == []


def test_auth_session_repository_persists_hashed_token(test_session):
    user = UserRepository.create(
        test_session,
        username="bob",
        password_hash=hash_password("secret", iterations=1000),
    )

    token = generate_session_token()
    expires_at = datetime.utcnow() + timedelta(hours=1)
    auth_session = AuthSessionRepository.create(
        test_session,
        user_id=user.id,
        session_token=token,
        expires_at=expires_at,
        ip_address="127.0.0.1",
        user_agent="pytest",
    )

    assert auth_session.session_token_hash == hash_token(token)
    assert AuthSessionRepository.get_by_token(test_session, token).id == auth_session.id

    AuthSessionRepository.revoke(test_session, auth_session)
    assert AuthSessionRepository.get_by_token(test_session, token) is None


def test_expired_session_is_not_returned(test_session):
    user = UserRepository.create(
        test_session,
        username="carol",
        password_hash=hash_password("secret", iterations=1000),
    )

    token = generate_session_token()
    expired_at = datetime.utcnow() - timedelta(minutes=5)
    AuthSessionRepository.create(
        test_session,
        user_id=user.id,
        session_token=token,
        expires_at=expired_at,
    )

    assert AuthSessionRepository.get_by_token(test_session, token) is None
