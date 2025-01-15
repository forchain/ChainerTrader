import json
from datetime import datetime

PRIMARY_KEY="open_time"

class Kline:
    def __init__(self,open_time:int,
                      open:float,
                      high:float,
                      low:float,
                      close:float,
                      close_time:int,
                      volume:float,
                      vol_quote:float,
                      trades:int,
                      vol_taker_base:float,
                      vol_taker_quote:float,
                      ignore:float=0):
        self.open_time=open_time
        self.open=open
        self.high=high
        self.low=low
        self.close=close
        self.close_time=close_time
        self.volume=volume
        self.vol_quote=vol_quote
        self.trades=trades
        self.vol_taker_base=vol_taker_base
        self.vol_taker_quote=vol_taker_quote
        self.ignore=ignore

    def to_dict(self):
        return {
            "open_datetime": f"{self.open_datetime()}",
            PRIMARY_KEY:self.open_time,
            "open":self.open,
            "high":self.high,
            "low":self.low,
            "close":self.close,
            "close_datetime": f"{self.close_datetime()}",
            "close_time":self.close_time,
            "volume":self.volume,
            "vol_quote":self.vol_quote,
            "trades":self.trades,
            "vol_taker_base":self.vol_taker_base,
            "vol_taker_quote":self.vol_taker_quote,
            "ignore":self.ignore
        }

    def to_json(self):
        return json.dumps(self.to_dict(), indent=4)

    def open_datetime(self):
        return datetime.fromtimestamp(self.open_time)

    def close_datetime(self):
        return datetime.fromtimestamp(self.close_time)

    def key(self):
        return self.open_time

def parse_kline(data)->Kline:
    return Kline(
        open_time=data[PRIMARY_KEY],
        open=data['open'],
        high=data['high'],
        low=data['low'],
        close=data['close'],
        close_time=data['close_time'],
        volume=data['volume'],
        vol_quote=data['vol_quote'],
        trades=data['trades'],
        vol_taker_base=data['vol_taker_base'],
        vol_taker_quote=data['vol_taker_quote'],
        ignore=data['ignore'],
    )