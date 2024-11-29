from trader.app.app import App
from trader.app.database_manager import DatabaseManager
from trader.binance.exchange import EXCHANGE_NAME, BinanceExchange
from trader.utils.symbol_interval import SymbolInterval


class DynamicTask:
    def __init__(self,app:App):
        self.app=app
        self.log = app.log()
        self.cfg = app.config()
        self.symbol_interval:SymbolInterval=self.cfg.get_symbol_interval_list()[0]
        self.log.info(f"Init DynamicTask: {self.symbol_interval.name()}")

    def start(self):
        self.log.info(f"Start DynamicTask: {self.symbol_interval.name()}")
        self.collection = self.db_mgr().get_collection("trader", self.symbol_interval.name())
        latest_kline = self.db_mgr().get_latest_kline(self.collection)


    def stop(self):
        pass

    def db_mgr(self)->DatabaseManager:
        return self.app.db_manager