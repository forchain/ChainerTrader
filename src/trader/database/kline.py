from logging import Logger

from pymongo import ASCENDING, DESCENDING
from pymongo.synchronous.collection import Collection

from trader.database.collection import get_name_for_klines
from trader.utils.kline import PRIMARY_KEY, Kline, parse_kline


class KlineCol:
    def __init__(self, db, log: Logger):
        self.db = db
        self.log = log

    def get_collection(self, name: str) -> Collection:
        collection_name = get_name_for_klines(name)
        if collection_name in self.db.list_collection_names():
            return self.db[collection_name]
        else:
            self.log.info(f"Create collection {collection_name} and index")
            col = self.db[collection_name]
            col.create_index([(PRIMARY_KEY, ASCENDING)], unique=True)
            return col

    def get_latest_kline(self, name: str) -> Kline | None:
        col = self.get_collection(name)
        max_record = col.find_one(sort=[(PRIMARY_KEY, DESCENDING)])
        if max_record is None:
            return None
        kl = parse_kline(max_record)
        self.log.debug(f"get latest kline({max_record['_id']}):{kl.to_json()}")
        return kl

    def get_latest_klines(self, name: str, limit: int) -> list[Kline] | None:
        col = self.get_collection(name)
        results = col.find().sort(PRIMARY_KEY, DESCENDING).limit(limit)
        if results is None:
            return None

        kls = []
        for ret in results:
            kls.append(parse_kline(ret))
        if len(kls) > 1:
            kls.reverse()

        return kls

    def add_klines(self, name: str, klines: list[Kline]) -> int:
        if len(klines) <= 0:
            return 0
        col = self.get_collection(name)
        insert_data = []
        duplicate = True
        total = 0
        for kl in klines:
            kld = kl.to_dict()
            if duplicate:
                try:
                    col.insert_one(kld)
                except Exception:
                    duplicate = True
                else:
                    duplicate = False
                    total += 1
                finally:
                    continue

            insert_data.append(kld)

        if len(insert_data) > 0:
            col.insert_many(insert_data)
            total += len(insert_data)
        self.log.debug(f"add klines, total:{total}")
        return total

    def get_first_kline(self, name: str) -> Kline | None:
        col = self.get_collection(name)
        max_record = col.find_one(sort=[(PRIMARY_KEY, ASCENDING)])
        if max_record is None:
            return None
        kl = parse_kline(max_record)
        self.log.debug(f"get first kline({max_record['_id']}):{kl.to_json()}")
        return kl

    def get_kline(self, name: str, open_time: int) -> Kline | None:
        col = self.get_collection(name)
        result = col.find_one({PRIMARY_KEY: open_time})
        if result is None:
            return None
        kl = parse_kline(result)
        self.log.debug(f"get kline({result['_id']}):{kl.to_json()}")
        return kl

    def get_all_klines(self, name: str) -> list[Kline] | None:
        col = self.get_collection(name)
        results = col.find().sort(PRIMARY_KEY, ASCENDING)
        if results is None:
            return None

        kls = []
        for ret in results:
            kls.append(parse_kline(ret))
        return kls

    def get_klines(self, name: str, start_time: int = 0, end_time: int = 0) -> list[Kline] | None:
        if start_time == 0 and end_time == 0:
            return self.get_all_klines(name)
        elif start_time > end_time and end_time > 0:
            return self.get_all_klines(name)
        elif start_time != 0 and end_time == 0:
            col = self.get_collection(name)
            results = col.find({PRIMARY_KEY: {"$gte": start_time}}).sort(PRIMARY_KEY, ASCENDING)
        elif start_time == 0 and end_time != 0:
            col = self.get_collection(name)
            results = col.find({PRIMARY_KEY: {"$lte": end_time}}).sort(PRIMARY_KEY, ASCENDING)
        else:
            col = self.get_collection(name)
            results = col.find({PRIMARY_KEY: {"$gte": start_time, "$lte": end_time}}).sort(PRIMARY_KEY, ASCENDING)

        if results is None:
            return None

        kls = []
        for ret in results:
            kls.append(parse_kline(ret))
        return kls

    def delete_klines_in_range(self, name: str, start_time: int, end_time: int) -> int:
        col = self.get_collection(name)
        result = col.delete_many({PRIMARY_KEY: {"$gte": start_time, "$lte": end_time}})
        deleted_count = result.deleted_count
        self.log.info(f"delete klines in range [{start_time}, {end_time}], deleted: {deleted_count}")
        return deleted_count
