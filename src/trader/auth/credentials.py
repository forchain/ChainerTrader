from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from trader.core.identity.exceptions import CredentialEncryptionError
from trader.core.identity.interfaces import SecretCipher


def service_key_available(service_key: str | None) -> bool:
    return bool(str(service_key or "").strip())


def _fernet(service_key: str | None) -> Fernet:
    if not service_key_available(service_key):
        raise CredentialEncryptionError("TRADER_SECRET_KEY is required for exchange credential encryption")
    digest = hashlib.sha256(str(service_key).encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(service_key: str | None, value: str) -> str:
    return _fernet(service_key).encrypt(str(value).encode("utf-8")).decode("utf-8")


def decrypt_secret(service_key: str | None, encrypted_value: str) -> str:
    try:
        return _fernet(service_key).decrypt(str(encrypted_value).encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise CredentialEncryptionError("exchange credential cannot be decrypted with the configured TRADER_SECRET_KEY") from exc


class FernetSecretCipher(SecretCipher):
    def __init__(self, service_key: str | None):
        self._service_key = service_key

    def encrypt(self, value: str) -> str:
        return encrypt_secret(self._service_key, value)

    def decrypt(self, encrypted_value: str) -> str:
        return decrypt_secret(self._service_key, encrypted_value)
