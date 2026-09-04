import logging

from trader.app.app import App
from trader.common.config import default

def main():
    cfg = default()
    cfg.log_level='DEBUG'
    app = App()
    app.log().debug("I am test logger by debug")
    app.log().info("I am test logger by info")
    app.log().warning("I am test logger by warn")
    app.log().error("I am test logger by error")
    app.log().critical("I am test logger by critical")



if __name__ == "__main__":
    main()