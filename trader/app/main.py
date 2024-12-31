import argparse,os

from trader.app.app import App, version
from trader.common.config import Config
from trader.rpc.rpc import start


def main():
    parser = argparse.ArgumentParser(
        description="Implement TradvingView Algorithms of Youtube Channel Shi Hun",
        epilog="Chainer Labs",
        fromfile_prefix_chars='@')

    parser.add_argument("-v", "--version",help="Version",action="store_true")
    parser.add_argument('--period', help='Period for the moving average',action='store',type=int, default=14,required=False)
    parser.add_argument('--commission', help='Transaction commission', action='store', type=float, default=0.001,required=False)
    parser.add_argument("--atr", help="Use atr for stop-loss-point", action="store_true")
    parser.add_argument("--api", help="Start the Web API service", action="store_true")
    parser.add_argument("--log_file", help="Write log to file", action="store_true")
    parser.add_argument("--plot", help="Plot data", action="store_true")
    parser.add_argument("--mode", help="trend type: NORMAL UP DOWN",type=str)
    parser.add_argument("--log_level", help="logger display level:CRITICAL,FATAL,ERROR,WARNING,WARNING,INFO,DEBUG", type=str,default="INFO")
    parser.add_argument("--exchange", help="Which remote exchange is connected to:BINANCE",type=str)
    parser.add_argument("--db", help="Enable database for MongoDB", action="store_true")
    parser.add_argument("--db_uri", help="Database URI for MongoDB", type=str, default="mongodb://localhost:27017/")
    parser.add_argument("--db_name", help="Database name for MongoDB", type=str,default="trader")
    parser.add_argument('--window', help='Window for backtesting', action='store', type=int, default=1000)
    parser.add_argument("--tasks", help="Tasks config:TRADER,BACK_TRADER,UPDATE_KLINES,CHECK_KLINES,IMPORT_CSV",type=str)


    args = parser.parse_args()
    db_uri = None
    if args.db:
        db_uri=args.db_uri

    cfg = Config(args.commission,
                 args.atr,
                 args.period,
                 args.log_file,
                 args.plot,
                 args.mode,
                 args.log_level,
                 args.exchange,
                 db_uri,
                 args.db_name,
                 args.window,
                 args.tasks)
    if args.version:
        print(version())
        return
    if args.api:
        start(cfg)
        return

    app = App(cfg)
    if app.start():
        app.stop()