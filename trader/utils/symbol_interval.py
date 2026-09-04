from datetime import timedelta
from enum import Enum

'''
Kline intervals
m -> minutes; h -> hours; d -> days; w -> weeks; M -> months

间隔	间隔 值
seconds -> 秒	1s
minutes -> 分钟	1m， 3m， 5m， 15m， 30m
hours -> 小时	1h， 2h， 4h， 6h， 8h， 12h
days -> 天	1d， 3d
weeks -> 周	1w
months -> 月	1M
'''

class Interval(Enum):
    INTERVAL_1s  ="1s"
    INTERVAL_1m  ="1m"
    INTERVAL_3m  ="3m"
    INTERVAL_5m  ="5m"
    INTERVAL_15m ="15m"
    INTERVAL_30m ="30m"
    INTERVAL_1h  ="1h"
    INTERVAL_2h  ="2h"
    INTERVAL_4h  ="4h"
    INTERVAL_6h  ="6h"
    INTERVAL_8h  ="8h"
    INTERVAL_12h ="12h"
    INTERVAL_1d  ="1d"
    INTERVAL_3d  ="3d"
    INTERVAL_1w  ="1w"
    INTERVAL_1M  ="1M"

# return seconds
def get_time_duration(interval:Interval)->int:
    if interval == Interval.INTERVAL_1s:
        return 1
    elif interval == Interval.INTERVAL_1m:
        return int(timedelta(minutes=1).total_seconds())
    elif interval == Interval.INTERVAL_3m:
        return int(timedelta(minutes=3).total_seconds())
    elif interval == Interval.INTERVAL_5m:
        return int(timedelta(minutes=5).total_seconds())
    elif interval == Interval.INTERVAL_15m:
        return int(timedelta(minutes=15).total_seconds())
    elif interval == Interval.INTERVAL_30m:
        return int(timedelta(minutes=30).total_seconds())
    elif interval == Interval.INTERVAL_1h:
        return int(timedelta(hours=1).total_seconds())
    elif interval == Interval.INTERVAL_2h:
        return int(timedelta(hours=2).total_seconds())
    elif interval == Interval.INTERVAL_4h:
        return int(timedelta(hours=4).total_seconds())
    elif interval == Interval.INTERVAL_6h:
        return int(timedelta(hours=6).total_seconds())
    elif interval == Interval.INTERVAL_8h:
        return int(timedelta(hours=8).total_seconds())
    elif interval == Interval.INTERVAL_12h:
        return int(timedelta(hours=12).total_seconds())
    elif interval == Interval.INTERVAL_1d:
        return int(timedelta(days=1).total_seconds())
    elif interval == Interval.INTERVAL_3d:
        return int(timedelta(days=3).total_seconds())
    elif interval == Interval.INTERVAL_1w:
        return int(timedelta(weeks=1).total_seconds())
    elif interval == Interval.INTERVAL_1M:
        return int(timedelta(days=30).total_seconds())

def add_time_duration(cur:int,interval:Interval,num:int)->int:
    return cur+get_time_duration(interval) * num

class SymbolInterval:
    def __init__(self,symbol:str,interval:Interval):
        self.symbol=symbol
        self.interval=interval

    def name(self):
        return self.symbol+"-"+self.interval.value