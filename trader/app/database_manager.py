import logging
from datetime import datetime
from tty import IFLAG

from pymongo import MongoClient
from pymongo.synchronous.collection import Collection

from trader.common.logger import Logger
from trader.utils.kline import Kline, PRIMARY_KEY, parse_kline


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

        if collection_name in db.list_collection_names():
            return db[collection_name]
        else:
            self.log.info(f"Create collection {collection_name} and index")
            col = db[collection_name]
            col.create_index([(PRIMARY_KEY, 1)])

    def get_latest_kline(self,col:Collection)->Kline|None:
        max_record = col.find_one(sort=[(PRIMARY_KEY, -1)])
        if max_record is None:
            return None
        kl = parse_kline(max_record)
        self.log.debug(f"get latest kline({max_record['_id']}):{kl}")
        return kl
