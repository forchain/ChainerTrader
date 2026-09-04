from trader.app import NAME
from trader.utils import path


def test_app():
    assert NAME == "trader"

def test_path():
    print(path.GetProjectDir())