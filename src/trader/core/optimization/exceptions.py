from __future__ import annotations


class OptimizationConfigError(ValueError):
    """Raised when an optimization or selection configuration or template is invalid."""


class RankingError(ValueError):
    """Raised when ranking payloads or audit constraints fail validation."""
