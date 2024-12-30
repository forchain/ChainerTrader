#!/usr/bin/env bash
trader_dev --tasks=./update_klines.json --db_uri="mongodb://localhost:27017/" --exchange=BINANCE --log_level=DEBUG


