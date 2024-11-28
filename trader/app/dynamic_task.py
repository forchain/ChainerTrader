from trader.app.app import App
from trader.binance.exchange import EXCHANGE_NAME, BinanceExchange

class DynamicTask:
    def __init__(self,app:App):
        self.app=app
        self.log = app.log()
        self.cfg = app.config()
        self.log.info(f"Init DynamicTask")

    def start(self):
        pass

    def stop(self):
        pass

