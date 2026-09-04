import pytest

from trader.auth.credentials import (
    CredentialEncryptionError,
    decrypt_secret,
    encrypt_secret,
    mask_api_key,
    service_key_available,
)


def test_service_key_available_requires_non_empty_key():
    assert service_key_available(None) is False
    assert service_key_available("") is False
    assert service_key_available("dev-secret") is True


def test_encrypt_secret_does_not_include_plaintext():
    encrypted = encrypt_secret("dev-secret", "binance-api-secret")

    assert "binance-api-secret" not in encrypted
    assert decrypt_secret("dev-secret", encrypted) == "binance-api-secret"


def test_decrypt_secret_rejects_wrong_key():
    encrypted = encrypt_secret("dev-secret", "binance-api-secret")

    with pytest.raises(CredentialEncryptionError):
        decrypt_secret("wrong-secret", encrypted)


def test_encrypt_secret_requires_service_key():
    with pytest.raises(CredentialEncryptionError):
        encrypt_secret("", "binance-api-secret")


def test_mask_api_key_keeps_only_edges():
    assert mask_api_key("abcdef123456") == "abcd***3456"
    assert mask_api_key("short") == "***"
