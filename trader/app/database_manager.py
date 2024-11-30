import logging
from datetime import datetime
from tty import IFLAG

from pymongo import MongoClient, ASCENDING
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
            col.create_index([(PRIMARY_KEY, ASCENDING)], unique=True)
            return col

    def get_latest_kline(self,col:Collection)->Kline|None:
        max_record = col.find_one(sort=[(PRIMARY_KEY, -1)])
        if max_record is None:
            return None
        kl = parse_kline(max_record)
        self.log.debug(f"get latest kline({max_record['_id']}):{kl.to_json()}")
        return kl

    def add_klines(self,col:Collection,klines:[Kline])->int:
        if len(klines) <= 0:
            return 0
        insert_data=[]
        duplicate = True
        total = 0
        for kl in klines:
            kld = kl.to_dict()
            if duplicate:
                try:
                    col.insert_one(kld)
                except Exception as e:
                    duplicate = True
                else:
                    duplicate=False
                    total+=1
                finally:
                    continue

            insert_data.append(kld)

        if len(insert_data) > 0:
            col.insert_many(insert_data)
            total+=len(insert_data)
        self.log.debug(f"add klines, total:{total}")
        return total