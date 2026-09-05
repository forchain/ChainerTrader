#!/usr/bin/env python3
"""Thin operational wrapper for open_sync migration synchronization tool."""

import sys

from trader.tools.open_sync import main

if __name__ == "__main__":
    sys.exit(main())
