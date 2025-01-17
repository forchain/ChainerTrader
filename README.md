# ChainerTrader 
A high-performance trading bot that can sift through an enormous number of strategies and extract the optimal ones.

## Overview
ChainerTrader is a modular trading bot designed to execute trading strategies on the Binance exchange. It supports real-time trading and backtesting, allowing users to optimize their trading strategies effectively.

## Features
- Connects to Binance for real-time trading.
- Supports MongoDB for data storage.
- Configurable trading parameters via command-line arguments and environment variables.
- Exposes a FastAPI-based web API for programmatic interaction.

## Install it from PyPI

```bash
pip install trader
```

## Usage

```bash
$ python -m trader -h
#or
$ trader -h
```

## Configuration
You can configure the bot using command-line arguments:
- `--commission`: Transaction commission (default: 0.001)
- `--atr`: Use ATR for stop-loss point (default: False)
- `--db_uri`: Database URI for MongoDB (default: "mongodb://localhost:27017/")
- `--tasks`: Tasks config (e.g., TRADER, BACK_TRADER)

## API Documentation
- `GET /version`: Returns the current version of the bot.
- `GET /info`: Returns information about the bot.
- `GET /start`: Starts the trading bot.
- `GET /exchange_info?symbol=<symbol>`: Retrieves exchange information for a given symbol.

## Development

Read the [CONTRIBUTING.md](CONTRIBUTING.md) file.
