from dataclasses import dataclass
from logging import Logger

from pymongo import ASCENDING
from pymongo.synchronous.collection import Collection

from trader.database.collection import get_name_for_availability


@dataclass(frozen=True)
class AvailabilityState:
    exchange: str
    symbol: str
    interval: str
    earliest_known_open_time: int
    updated_at: int
    source: str


class AvailabilityCol:
    def __init__(self, db, log: Logger):
        self.db = db
        self.log = log

    def get_collection(self) -> Collection:
        collection_name = get_name_for_availability()
        if collection_name in self.db.list_collection_names():
            return self.db[collection_name]

        self.log.info(f"Create collection {collection_name} and index")
        col = self.db[collection_name]
        col.create_index([("exchange", ASCENDING), ("symbol", ASCENDING), ("interval", ASCENDING)], unique=True)
        return col

    def get_state(self, exchange: str, symbol: str, interval: str) -> AvailabilityState | None:
        col = self.get_collection()
        result = col.find_one({"exchange": exchange, "symbol": symbol, "interval": interval})
        if result is None:
            return None
        return AvailabilityState(
            exchange=result["exchange"],
            symbol=result["symbol"],
            interval=result["interval"],
            earliest_known_open_time=result["earliest_known_open_time"],
            updated_at=result["updated_at"],
            source=result["source"],
        )

    def get_earliest_known_open_time(self, exchange: str, symbol: str, interval: str) -> int | None:
        state = self.get_state(exchange, symbol, interval)
        if state is None:
            return None
        return state.earliest_known_open_time

    def update_earliest_known_open_time(
        self,
        exchange: str,
        symbol: str,
        interval: str,
        earliest_known_open_time: int,
        source: str = "backward_fill",
    ) -> bool:
        col = self.get_collection()
        current = col.find_one({"exchange": exchange, "symbol": symbol, "interval": interval})
        if current is not None and current.get("earliest_known_open_time", earliest_known_open_time) <= earliest_known_open_time:
            return False

        payload = {
            "exchange": exchange,
            "symbol": symbol,
            "interval": interval,
            "earliest_known_open_time": earliest_known_open_time,
            "updated_at": earliest_known_open_time,
            "source": source,
        }
        col.replace_one({"exchange": exchange, "symbol": symbol, "interval": interval}, payload, upsert=True)
        return True
