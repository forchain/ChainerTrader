from __future__ import annotations

from argon2 import PasswordHasher as Argon2
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from trader.core.identity.interfaces import PasswordHasher


class Argon2PasswordHasher(PasswordHasher):
    def __init__(self):
        self._hasher = Argon2()

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password: str, password_hash: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (InvalidHashError, VerificationError, VerifyMismatchError):
            return False


_DEFAULT_HASHER = Argon2PasswordHasher()


def hash_password(password: str) -> str:
    return _DEFAULT_HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _DEFAULT_HASHER.verify(password, password_hash)
