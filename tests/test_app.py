import logging
import os


from trader.app.app import App
from trader.common import path
from trader.common.common import NAME
from trader.common.config import Config, NewConfigFromEnv, default



def test_app():
    app = App()
    assert NAME == app.name()

def test_path():
    print(path.GetProjectDir())

def test_data_path():
    assert os.path.exists(path.get_file_path("ETHUSDT-1h-202301-202401.csv"))

def test_log():
    cfg = default()
    cfg.log_level='DEBUG'
    app = App()
    app.log().debug("I am test logger by debug")
    app.log().info("I am test logger by info")
    app.log().warning("I am test logger by warn")
    app.log().error("I am test logger by error")
    app.log().critical("I am test logger by critical")

def test_version():
    app = App()
    print(app.version())

def test_config():
    cfg = Config()
    cfg.exportEnv()
    ncfg=NewConfigFromEnv()
    print(ncfg.to_dict())