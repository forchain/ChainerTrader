
'''
间隔	间隔 值
seconds -> 秒	1s
minutes -> 分钟	1m， 3m， 5m， 15m， 30m
hours -> 小时	1h， 2h， 4h， 6h， 8h， 12h
days -> 天	1d， 3d
weeks -> 周	1w
months -> 月	1M
'''

class SymbolInterval:
    def __init__(self,symbol:str,interval:str):
        self.symbol=symbol
        self.interval=interval

    def name(self):
        return self.symbol+"-"+self.interval