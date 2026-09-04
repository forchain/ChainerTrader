import os

import pytest
from dotenv import load_dotenv

from trader.utils.top import get_symbol_top, write_symbols_top100_config


def test_get_symbol_top100():
    load_dotenv()
    # get env value
    apiKey = os.getenv("coinMarketCapAPIKey")
    if not apiKey:
        pytest.skip("coinMarketCapAPIKey not set")
    symbols = get_symbol_top(apiKey)
    assert symbols
    assert len(symbols) > 0

    index = 0
    for si in symbols:
        print(f"{index} -> {si}")
        index += 1


def test_write_config_top100():
    load_dotenv()
    # get env value
    apiKey = os.getenv("coinMarketCapAPIKey")
    if not apiKey:
        pytest.skip("coinMarketCapAPIKey not set")
    assert write_symbols_top100_config(apiKey)
