import os

from trader.common import path
from trader.utils.symbol_interval import Interval, SymbolInterval


class SymbolsInterval:
    def __init__(self, symbols: str, interval: Interval):
        symbol_list = []
        file_path = path.get_file_path(symbols)
        if os.path.isfile(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as file:
                    symbol_list = [line.strip() for line in file]
            except FileNotFoundError:
                return
        else:
            symbol_list = symbols.split(",")

        self.symbol_intervals = []
        for sy in symbol_list:
            si = SymbolInterval(sy, interval)
            if si.is_empty():
                continue
            self.symbol_intervals.append(si)

    def get(self, index: int):
        if index >= len(self.symbol_intervals):
            return None
        return self.symbol_intervals[index]

    def __len__(self):
        return len(self.symbol_intervals)
