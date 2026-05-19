from __future__ import annotations

import re
import secrets
import string

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError, VerificationError


class PasswordPolicyError(ValueError):
    pass


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
WEAK_PASSWORDS = {
    "password",
    "password123",
    "1234567890",
    "qwerty123",
    "admin123",
    "letmein123",
}

_HASHER = PasswordHasher()


def validate_username(username: str) -> None:
    if not USERNAME_PATTERN.fullmatch(str(username or "")):
        raise PasswordPolicyError("username must be 3-32 characters and contain only letters, numbers, underscores, or hyphens")


def validate_password(username: str, password: str) -> None:
    value = str(password or "")
    lowered = value.lower()
    if len(value) < 10:
        raise PasswordPolicyError("password must be at least 10 characters")
    if username and lowered == str(username).lower():
        raise PasswordPolicyError("password must not equal username")
    if lowered in WEAK_PASSWORDS:
        raise PasswordPolicyError("password is too common")
    if not any(char.isalpha() for char in value):
        raise PasswordPolicyError("password must contain at least one letter")
    if not any(char.isdigit() for char in value):
        raise PasswordPolicyError("password must contain at least one number")


def generate_temporary_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(max(length, 16)))
        try:
            validate_password("", password)
        except PasswordPolicyError:
            continue
        return password


def hash_password(password: str) -> str:
    return _HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _HASHER.verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False
