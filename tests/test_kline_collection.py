from __future__ import annotations

from trader.database.kline import KlineCol
from trader.utils.kline import PRIMARY_KEY, Kline


class DummyLog:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


class FakeInsertManyResult:
    def __init__(self, inserted_ids):
        self.inserted_ids = inserted_ids


class FakeKlineCollection:
    def __init__(self, existing_open_times: set[int]):
        self.existing_open_times = set(existing_open_times)
        self.insert_one_calls = 0
        self.insert_many_calls = []

    def find(self, query, projection=None):
        requested = set(query[PRIMARY_KEY]["$in"])
        return [{PRIMARY_KEY: open_time} for open_time in sorted(requested & self.existing_open_times)]

    def insert_one(self, document):
        self.insert_one_calls += 1
        raise AssertionError("add_klines should not probe duplicates with insert_one")

    def insert_many(self, documents, ordered=True):
        inserted_ids = []
        for document in documents:
            open_time = document[PRIMARY_KEY]
            if open_time in self.existing_open_times:
                raise AssertionError(f"duplicate open_time inserted: {open_time}")
            self.existing_open_times.add(open_time)
            inserted_ids.append(open_time)
        self.insert_many_calls.append((documents, ordered))
        return FakeInsertManyResult(inserted_ids)


class FakeDb:
    def __init__(self, collection):
        self.collection = collection

    def list_collection_names(self):
        return ["klines-BTCUSDT-1d"]

    def __getitem__(self, name):
        assert name == "klines-BTCUSDT-1d"
        return self.collection


def make_kline(open_time: int) -> Kline:
    return Kline(
        open_time=open_time,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        close_time=open_time + 86_399,
        volume=10,
        vol_quote=20,
        trades=3,
        vol_taker_base=4,
        vol_taker_quote=5,
        ignore=0,
    )


def test_add_klines_skips_existing_rows_before_bulk_insert():
    existing_open_times = set(range(100, 586))
    missing_open_times = list(range(586, 600))
    collection = FakeKlineCollection(existing_open_times)
    store = KlineCol(FakeDb(collection), DummyLog())
    klines = [make_kline(open_time) for open_time in [*range(100, 586), *missing_open_times]]

    inserted = store.add_klines("BTCUSDT-1d", klines)

    assert inserted == len(missing_open_times)
    assert collection.insert_one_calls == 0
    assert len(collection.insert_many_calls) == 1
    inserted_docs, ordered = collection.insert_many_calls[0]
    assert ordered is False
    assert [doc[PRIMARY_KEY] for doc in inserted_docs] == missing_open_times
