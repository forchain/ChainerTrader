"""Compatibility shim: config model lives in ``trader.core.shared.config``."""

from trader.adapters.inbound.cli.env_config import new_and_env  # noqa: F401
from trader.core.shared.config import *  # noqa: F401,F403
