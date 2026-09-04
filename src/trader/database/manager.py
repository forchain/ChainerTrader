from pymongo import MongoClient

from trader.common.logger import Logger
from trader.database.availability import AvailabilityCol
from trader.database.kline import KlineCol
from trader.database.task import TaskCol


class DatabaseManager:
    def __init__(self, cfg, log: Logger):
        self.log = log.log()
        self.cfg = cfg
        self.log.info("Init DatabaseManager")

        """
        _COMMAND_LOGGER = logging.getLogger("pymongo.command")
        _CONNECTION_LOGGER = logging.getLogger("pymongo.connection")
        _SERVER_SELECTION_LOGGER = logging.getLogger("pymongo.serverSelection")
        _CLIENT_LOGGER = logging.getLogger("pymongo.client")
        _SDAM_LOGGER = logging.getLogger("pymongo.topology")
        """
        # log.apply(logging.getLogger("pymongo.command"))

        self.client = None
        self.task = None
        self.kline = None
        self.availability = None

    def start(self):
        self.client = MongoClient(self.cfg.db)
        db = self.get_database(self.cfg.db_name)
        self.kline = KlineCol(db, self.log)
        self.task = TaskCol(db, self.log)
        self.availability = AvailabilityCol(db, self.log)

    def stop(self):
        self.client.close()
        self.client = None

    def get_database(self, name):
        return self.client[name]
