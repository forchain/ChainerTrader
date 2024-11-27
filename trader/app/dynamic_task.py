from trader.app.app import App
from trader.binance.exchange import EXCHANGE_NAME, BinanceExchange

class DynamicTask:
    def __init__(self,app:App):
        self.app=app
        self.log = app.log()
        self.cfg = app.config()
        self.log.info(f"Init DynamicTask")

    def start(self):
        if self.cfg.exchange == EXCHANGE_NAME:
            self.exchange = BinanceExchange(self.cfg,self.log)
            self.exchange.start()
        else:
            self.log.warning(f"Not support exchange:{self.cfg.exchange}")
            return

    def stop(self):
        if self.exchange:
            self.exchange.stop()

