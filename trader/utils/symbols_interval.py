from trader.utils.symbol_interval import Interval
import os

class SymbolInterval:
    def __init__(self,symbols:str,interval:Interval):
        symbol_list=[]
        if os.path.isfile(symbols):
            try:
                with open(symbols, 'r', encoding='utf-8') as file:
                    symbol_list = [line.strip() for line in file]
            except FileNotFoundError:
                return
        else:
            symbol_list=symbols.split(',')

        self.symbol_interval:SymbolInterval=[]
        for sy in symbol_list:
             self.symbol_interval.append(SymbolInterval(sy,interval))

    def get(self,index:int):
        if index >= len(self.symbol_interval):
            return None
        return self.symbol_interval[index]

    def __len__(self):
        return len(self.symbol_interval)