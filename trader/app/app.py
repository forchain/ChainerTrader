import logging

from trader.utils.logger import Logger

NAME = "trader"

class App:
    def __init__(self):
        self.logger=Logger(NAME,logging.DEBUG)

    def name(self):
        return NAME

    def log(self):
        return self.logger.log()

    def start(self):
        self.log().info(f"Start {self.name()} App")

    def stop(self):
        self.log().info(f"Stop {self.name()} App")