"""Exchange account domain exceptions translated by inbound adapters."""

from __future__ import annotations


class UserExchangeCredentialError(RuntimeError):
    """Raised when user-owned exchange credentials cannot be resolved or used."""


class ExchangeConnectivityError(RuntimeError):
    """Raised when an exchange credential cannot establish connectivity."""
