import logging
from datetime import datetime
from tty import IFLAG

from pymongo import MongoClient, ASCENDING, DESCENDING
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
        #log.apply(logging.getLogger("pymongo.command"))

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
        max_record = col.find_one(sort=[(PRIMARY_KEY, DESCENDING)])
        if max_record is None:
            return None
        kl = parse_kline(max_record)
        self.log.debug(f"get latest kline({max_record['_id']}):{kl.to_json()}")
        return kl

    def get_latest_klines(self,col:Collection,limit:int)->[Kline]:
        results = col.find().sort(PRIMARY_KEY, DESCENDING).limit(limit)
        if results is None:
            return None

        kls=[]
        for ret in results:
            kls.append(parse_kline(ret))
        if len(kls) > 1:
            kls.reverse()

        return kls

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

    def get_first_kline(self,col:Collection)->Kline|None:
        max_record = col.find_one(sort=[(PRIMARY_KEY, ASCENDING)])
        if max_record is None:
            return None
        kl = parse_kline(max_record)
        self.log.debug(f"get first kline({max_record['_id']}):{kl.to_json()}")
        return kl

    def get_kline(self,col:Collection,open_time:int)->Kline|None:
        result = col.find_one({PRIMARY_KEY: open_time})
        if result is None:
            return None
        kl = parse_kline(result)
        self.log.debug(f"get kline({result['_id']}):{kl.to_json()}")
        return kl

    def get_all_klines(self, col: Collection) -> [Kline]:
        results = col.find().sort(PRIMARY_KEY, ASCENDING)
        if results is None:
            return None

        kls = []
        for ret in results:
            kls.append(parse_kline(ret))
        return kls

    def get_klines(self, col: Collection,start_time:int=0,end_time:int=0) -> [Kline]:
        if start_time == 0 and end_time == 0:
            return self.get_all_klines(col)
        elif start_time > end_time and end_time > 0:
            return self.get_all_klines(col)
        elif start_time != 0 and end_time == 0:
            results = col.find({PRIMARY_KEY: {"$gte": start_time}}).sort(PRIMARY_KEY, ASCENDING)
        elif start_time == 0 and end_time != 0:
            results = col.find({PRIMARY_KEY: {"$lte": end_time}}).sort(PRIMARY_KEY, ASCENDING)
        else:
            results = col.find({PRIMARY_KEY: {"$gte": start_time,"$lte": end_time}}).sort(PRIMARY_KEY, ASCENDING)

        if results is None:
            return None

        kls = []
        for ret in results:
            kls.append(parse_kline(ret))
        return kls