"""Compatibility shim: administrator bootstrap now lives in ``trader.core.identity.use_cases``."""

from trader.core.identity.use_cases import bootstrap_admin_exchange_credential  # noqa: F401
