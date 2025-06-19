from datetime import datetime

from backtrader import num2date


class Pivot:
    def __init__(self,price:float,dt:datetime):
        self.price=price
        self.dt=dt

class PivotManager:

    def __init__(self,period:int,max:int=20):
        self.period=period
        self.max=max

        self.high_pivots:[Pivot]=[]
        self.low_privots:[Pivot]=[]

    def next(self,data):
        if data.close[0] < data.close[-1] and data.close[-1] > data.close[-2]:
            self.high_pivots.append(Pivot(data.close[-1],num2date(data.datetime[-1])))
            if len(self.high_pivots) > self.max:
                self.high_pivots.pop(0)

        elif data.close[0] > data.close[-1] and data.close[-1] < data.close[-2]:
            self.low_privots.append(Pivot(data.close[-1],num2date(data.datetime[-1])))
            if len(self.low_privots) > self.max:
                self.low_privots.pop(0)