from trader.app.app import NAME, App
from trader.common import path


def test_app():
    app = App()
    assert NAME == app.name()

def test_path():
    print(path.GetProjectDir())

def test_log():
    app = App()
    app.log().debug("I am test logger by debug")
    app.log().info("I am test logger by info")
    app.log().warn("I am test logger by warn")
    app.log().error("I am test logger by error")
    app.log().critical("I am test logger by critical")

def test_version():
    app = App()
    print(app.version())