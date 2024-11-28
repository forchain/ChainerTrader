import logging
from datetime import datetime

from pymongo import MongoClient
from pymongo.synchronous.collection import Collection

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

    def stop(self):
        self.client.close()

    def get_database(self,name):
        return self.client[name]

    def get_collection(self,db_name,collection_name)->Collection:
        db=self.get_database(db_name)
        return db[collection_name]

    def get_latest_kline(self):