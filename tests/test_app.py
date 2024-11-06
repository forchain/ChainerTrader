import logging

from trader.app import NAME
from trader.utils import path
from trader.utils.logger import Logger


def test_app():
    assert NAME == "trader"

def test_path():
    print(path.GetProjectDir())

def test_log():
    log = Logger(NAME,logging.DEBUG)
    log.log().debug("I am test logger by debug")
    log.log().info("I am test logger by info")
    log.log().warn("I am test logger by warn")
    log.log().error("I am test logger by error")
    log.log().critical("I am test logger by critical")