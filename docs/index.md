# ChainerTrader 
Implement TradvingView Algorithms of Youtube Channel Shi Hun


## Install it from PyPI

```bash
pip install trader
```

## Usage

```bash
$ python -m trader -h
or
$ trader -h
```

## Show trader version 

```bash
$ trader -v
```

## Display command line parameters

```bash
$ trader -h
```

## Modify the transaction fee used for backtesting strategy calculation

```bash
$ trader --commission=0.0015 ... ...
```

## Use atr for stop-loss-point

```bash
$ trader --atr ... ...
```

## Start the Web API service

```bash
$ trader --api ... ...
```
* Then you can access http://127.0.0.1:8000/ through a browser

## Output logs to file

```bash
$ trader --api ... ...
```

## Output logs to file

```bash
$ trader --log_file ... ...
```

## You can set the display level of the log, which includes these levels(CRITICAL,FATAL,ERROR,WARNING,WARNING,INFO,DEBUG). The default level is INFO
```bash
$ trader --log_level=DEBUG ... ...
```


## Run trader with `ShihunMACD` strategy for backtesting and load trader data from local file

```bash
$ trader --tasks='[{"task_type": "BACK_TRADER","symbol":"ETHUSDT","interval":"1h","strategy":"ShihunMACD","csv":"ETHUSDT-1h-202301-202401.csv"}]'
```

## Run trader with tasks config file for backtesting

```tasks.json:
[
    {
        "task_type": "BACK_TRADER",
        "symbol": "ETHUSDT",
        "interval": "1h",
        "strategy": "ShihunMACD",
        "csv": "ETHUSDT-1h-202301-202401.csv"
    }
]
```

```bash
$ trader --tasks=./tasks.json
```

## Import CSV data into the mongo database
```bash
$ trader --tasks='[{"task_type": "IMPORT_CSV","symbol":"ETHUSDT","interval":"1h","csv":"ETHUSDT-1h-202301-202401.csv"}]' --db
```

## Run trader with `ShihunMACD` strategy for backtesting and load trader data from mongo database

```bash
$ trader --tasks='[{"task_type": "BACK_TRADER","symbol":"ETHUSDT","interval":"1h","strategy":"ShihunMACD"}]' --db
```

## Download the klines data from the exchange according to your own configuration and save it to the mongo database
```bash
$ trader --tasks='[{"task_type": "UPDATE_KLINES","symbol":"BTCUSDT","interval":"1d"}]' --db --exchange=BINANCE
```

## Check the integrity of klines data in the mongo database
```bash
$ trader --tasks='[{"task_type": "CHECK_KLINES","symbol":"BTCUSDT","interval":"1d"}]' --db
```

## Connect to the BINANCE exchange and provide real-time backtesting klines data
```bash
$ trader --tasks='[{"task_type": "TRADER","symbol":"BTCUSDT","interval":"1d"}]' --db --exchange=BINANCE
```

## Multi strategy multi task concurrent execution klines data backtesting
```backtrader_strategy.json:
[
  {
    "task_type": "BACK_TRADER",
    "symbol": "ETHUSDT",
    "interval": "1h",
    "csv":"ETHUSDT-1h-202301-202401.csv",
    "strategy":"ShihunMACD"
  },
  {
    "task_type": "BACK_TRADER",
    "symbol": "ETHUSDT",
    "interval": "1h",
    "csv":"ETHUSDT-1h-202301-202401.csv",
    "strategy":"ShihunMACD2"
  },
  {
    "task_type": "BACK_TRADER",
    "symbol": "ETHUSDT",
    "interval": "1h",
    "csv":"ETHUSDT-1h-202301-202401.csv",
    "strategy":"ShihunRSI"
  },
  {
    "task_type": "BACK_TRADER",
    "symbol": "ETHUSDT",
    "interval": "1h",
    "csv":"ETHUSDT-1h-202301-202401.csv",
    "strategy":"ShihunRSI2"
  },
  {
    "task_type": "BACK_TRADER",
    "symbol": "ETHUSDT",
    "interval": "1h",
    "csv":"ETHUSDT-1h-202301-202401.csv",
    "strategy":"ShihunMACDRISBB"
  }
]
```

```bash
$ cd ./trader/scripts
$ trader --tasks=./scripts/backtrader_strategy.json
```

## Run trader with tasks config file for backtesting and config start time or end time

```tasks.json:
[
    {
        "task_type": "BACK_TRADER",
        "symbol": "ETHUSDT",
        "interval": "1h",
        "strategy": "ShihunMACD",
        "csv": "ETHUSDT-1h-202301-202401.csv",
        "start_time": "2023-06-01 14:00:00",
        "end_time": "2023-11-01 14:00:00"
    }
]
```

```bash
$ trader --tasks=./tasks.json
```

## Automatically generate backtesting tasks based on multiple configurations of 'symbols' and 'strategys'
```bash
$ cd ./trader/scripts
$ trader --tasks=./multi_backtrader.json --db --exchange=BINANCE
```

## Development
Read the [CONTRIBUTING.md](CONTRIBUTING.md) file.
