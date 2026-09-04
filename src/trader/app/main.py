import argparse

from dotenv import load_dotenv

from trader.app.app import App, version
from trader.common.config import new_and_env
from trader.rpc.rpc import start


def main():
    parser = argparse.ArgumentParser(
        description="Implement TradvingView Algorithms of Youtube Channel Shi Hun",
        epilog="Chainer Labs",
        fromfile_prefix_chars="@",
    )

    parser.add_argument("-v", "--version", help="Version", action="store_true", default=argparse.SUPPRESS)
    parser.add_argument(
        "--period",
        help="Period for the moving average",
        action="store",
        type=int,
        default=argparse.SUPPRESS,
        required=False,
    )
    parser.add_argument(
        "--commission",
        help="Transaction commission",
        action="store",
        type=float,
        default=argparse.SUPPRESS,
        required=False,
    )
    parser.add_argument(
        "--api",
        help="Start the Web API service with optional binding address and port (e.g. 127.0.0.1:8000, :8000, 127.0.0.1)",
        nargs="?",
        type=str,
        const="127.0.0.1:8000",
        default=argparse.SUPPRESS,
    )
    parser.add_argument("--log_file", help="Write log to file", action="store_true", default=argparse.SUPPRESS)
    parser.add_argument("--plot", help="Plot data", action="store_true", default=argparse.SUPPRESS)
    parser.add_argument("--mode", help="trend type: NORMAL UP DOWN", type=str, default=argparse.SUPPRESS)
    parser.add_argument(
        "--log_level",
        help="logger display level:CRITICAL,FATAL,ERROR,WARNING,WARNING,INFO,DEBUG",
        type=str,
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--exchange",
        help="Which remote exchange is connected to.support json:BINANCE or {name:BINANCE,api_key:'',api_secret:''}",
        type=str,
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--db",
        help="Enable database with a Tortoise ORM URL (default: sqlite://data/trader.db)",
        nargs="?",
        const="sqlite://data/trader.db",
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--db_name",
        help="Deprecated legacy MongoDB database name; ignored by SQL database URLs",
        type=str,
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--window",
        help="Window for backtesting",
        action="store",
        type=int,
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--tasks",
        help="Tasks config:TRADER,BACK_TRADER,UPDATE_KLINES,CHECK_KLINES,IMPORT_CSV",
        type=str,
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--cash",
        help="Init cash for backtesting",
        action="store",
        type=float,
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--stat",
        help="The maximum number of entries displayed in statistics for backtesting",
        action="store",
        type=int,
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--notice",
        help="Load notification configuration files, such as email",
        type=str,
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--auth-username",
        help="Username for HTTP Basic Authentication (optional)",
        type=str,
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--auth-password",
        help="Password for HTTP Basic Authentication (optional)",
        type=str,
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--protected-paths",
        help="Comma-separated list of path prefixes that require authentication (e.g., '/admin,/api/admin'). Default: all paths are public",
        type=str,
        default=argparse.SUPPRESS,
    )

    args = parser.parse_args()
    load_dotenv()

    cfg = new_and_env(args)
    if getattr(args, "version", False):
        print(version())
        return

    if cfg.api:
        start(cfg)

    else:
        app = App(cfg)
        if app.start():
            app.stop()
