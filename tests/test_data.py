from datetime import date, datetime, time
from backtrader import date2num

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

    timestamp = datetime.now().timestamp()
    print(f"timestamp:{timestamp}")

    dtnum = date2num(datetime.fromtimestamp(timestamp))
    print(f"dtnum:{dtnum}")