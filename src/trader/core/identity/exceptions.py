"""Identity domain exceptions translated by inbound adapters."""


class AuthenticationError(Exception):
    """Raised when credentials, sessions, or account state are rejected."""


class PasswordPolicyError(ValueError):
    """Raised when a username or password violates the account policy."""


class CredentialEncryptionError(ValueError):
    """Raised when a user credential cannot be encrypted or decrypted."""
