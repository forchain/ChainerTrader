import pytest

from trader.auth.passwords import (
    PasswordPolicyError,
    generate_temporary_password,
    hash_password,
    validate_password,
    validate_username,
    verify_password,
)


def test_validate_username_accepts_simple_account_names():
    validate_username("trader_01")
    validate_username("ops-admin")


@pytest.mark.parametrize("username", ["ab", "has space", "中文用户", "bad@email", "x" * 33])
def test_validate_username_rejects_invalid_names(username):
    with pytest.raises(PasswordPolicyError):
        validate_username(username)


def test_validate_password_accepts_basic_strong_password():
    validate_password("trader", "marketBot2026")


@pytest.mark.parametrize("password", ["short1", "password123", "trader", "1234567890", "abcdefghij"])
def test_validate_password_rejects_weak_passwords(password):
    with pytest.raises(PasswordPolicyError):
        validate_password("trader", password)


def test_generate_temporary_password_satisfies_policy():
    password = generate_temporary_password()

    validate_password("trader", password)
    assert len(password) >= 16


def test_hash_password_verification_round_trip():
    password_hash = hash_password("marketBot2026")

    assert password_hash != "marketBot2026"
    assert verify_password("marketBot2026", password_hash) is True
    assert verify_password("wrongPassword2026", password_hash) is False
