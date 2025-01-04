from datetime import date, datetime, time
from backtrader import date2num, num2date

from trader.common.common import parse_datetime


def test_datetime():
    dttxt = "2024-10-11"
    dt = date(int(dttxt[0:4]), int(dttxt[5:7]), int(dttxt[8:10]))
    dtnum = date2num(datetime.combine(dt,time(21,12,12)))
    print(f"dtnum:{dtnum}")

def test_binanceTimestamp():
    btimestampStr = "1672531200000"
    btimestamp = int(btimestampStr)
    timestamp = btimestamp/1000
    dtnum = date2num(datetime.fromtimestamp(timestamp))
    print(f"dtnum:{dtnum}")

def test_binanceTimestamp2():
    now = datetime.now()
    print(f"{now}")
    timestamp = now.timestamp()
    print(f"timestamp:{timestamp}")

    dtnum = date2num(datetime.fromtimestamp(timestamp))
    print(f"dtnum:{dtnum}")

    dt = num2date(dtnum)

    print(f"dt:{dt}")

def test_parse_datetime():
    cfg_dt0 = "2023-09-24 14:30:00"
    dt0 = parse_datetime(cfg_dt0)
    print(f"date time:{dt0}")
    cfg_dt1 = f"{int(dt0.timestamp())}"
    dt1 = parse_datetime(cfg_dt1)
    print(f"date time:{dt1}")
    assert dt0 == dt1


