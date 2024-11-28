
class SymbolInterval:
    def __init__(self,symbol:str,interval:str):
        self.symbol=symbol
        self.interval=interval

    def name(self):
        return self.symbol+"-"+self.interval