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

## Run trader with `ShihunMACD` strategy and load trader data from local file

```bash
$ trader --tasks='[{"task_type": "BACK_TRADER","symbol":"ETHUSDT","interval":"1h","strategy":"ShihunMACD","csv":"ETHUSDT-1h-202301-202401.csv"}]'
```

## Run trader with tasks config file

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

## Development