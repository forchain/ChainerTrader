import logging

from trader.utils.logger import Logger

NAME = "trader"

class App:
    def __init__(self):
        self.name=NAME
        self.log=Logger(self.name,logging.DEBUG)