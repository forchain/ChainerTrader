import logging
from datetime import datetime

from pymongo import MongoClient

from trader.common.logger import Logger


class DatabaseManager:
    def __init__(self,cfg,log:Logger):
        self.log = log.log()
        self.cfg = cfg
        self.log.info(f"Init DatabaseManager")

        '''
        _COMMAND_LOGGER = logging.getLogger("pymongo.command")
        _CONNECTION_LOGGER = logging.getLogger("pymongo.connection")
        _SERVER_SELECTION_LOGGER = logging.getLogger("pymongo.serverSelection")
        _CLIENT_LOGGER = logging.getLogger("pymongo.client")
        _SDAM_LOGGER = logging.getLogger("pymongo.topology")
        '''
        log.apply(logging.getLogger("pymongo.command"))

    def start(self):
        self.client = MongoClient(self.cfg.db_uri)
        # 选择数据库
        self.db = self.client["binance"]


    def stop(self):
        self.client.close()