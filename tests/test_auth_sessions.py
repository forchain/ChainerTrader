from datetime import UTC, datetime, timedelta

from trader.auth.sessions import create_session_token, hash_session_token, is_expired


def test_create_session_token_returns_random_values():
    first = create_session_token()
    second = create_session_token()

    assert first != second
    assert len(first) >= 32
    assert len(second) >= 32


def test_hash_session_token_is_stable_and_not_plaintext():
    token = create_session_token()

    digest = hash_session_token(token)

    assert digest == hash_session_token(token)
    assert digest != token


def test_is_expired_detects_past_expiry():
    assert is_expired(datetime.now(UTC) - timedelta(seconds=1)) is True
    assert is_expired(datetime.now(UTC) + timedelta(seconds=60)) is False
