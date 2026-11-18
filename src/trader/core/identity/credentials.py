"""Credential display rule shared by identity use cases and adapters."""

from __future__ import annotations


def mask_api_key(api_key: str) -> str:
    value = str(api_key or "")
    if len(value) < 8:
        return "***"
    return f"{value[:4]}***{value[-4:]}"
