#!/usr/bin/env bash
trader --tasks=./configs/tasks/downloads/update_klines.json --db --exchange='{"ty":"BINANCE","driver":"ccxt"}' --log_file
