import argparse,os

from trader.app.app import App
from trader.common.config import Config
from trader.rpc.rpc import start


def main():
    app = App()

    parser = argparse.ArgumentParser(
        description="Implement TradvingView Algorithms of Youtube Channel Shi Hun",
        epilog="Chainer Labs",
        fromfile_prefix_chars='@')

    parser.add_argument("-v", "--version",help="Version",action="store_true")
    parser.add_argument("-s", "--strategy", help="strategy type: ShihunMACD, ShihunRSI, ShihunMACD2, ShihunRSI2, ShihunMACDRISBB",type=str)
    parser.add_argument('--period', help='Period for the moving average',action='store',type=int, default=14,required=False)
    parser.add_argument('--commission', help='Transaction commission', action='store', type=float, default=0.001,required=False)
    parser.add_argument("--atr", help="Use atr for stop-loss-point", action="store_true")
    parser.add_argument("--api", help="Start the Web API service", action="store_true")
    parser.add_argument("--log_file", help="Write log to file", action="store_true")
    parser.add_argument("--plot", help="Plot data", action="store_true")
    parser.add_argument("--mode", help="trend type: NORMAL UP DOWN",type=str)
    parser.add_argument("--log_level", help="logger display level:CRITICAL,FATAL,ERROR,WARNING,WARNING,INFO,DEBUG", type=str,default="INFO")
    parser.add_argument("--exchange", help="Which remote exchange is connected to:BINANCE",type=str)
    parser.add_argument("--symbols", help="symbols for trading pairs", type=str,default="BTCUSDT")
    parser.add_argument("--intervals", help="intervals for trading pairs", type=str,default="1d")
    parser.add_argument("--data_file", help="Local data file", type=str)
    parser.add_argument("--db_uri", help="Database URI for MongoDB", type=str)


    args = parser.parse_args()
    cfg = Config(args.strategy,args.commission,args.atr,args.period,args.log_file,args.plot,args.mode,args.log_level,args.exchange,args.symbols,args.intervals,args.data_file,args.db_uri)
    if args.version:
        print(app.version())
        return
    if args.api:
        start(cfg)
        return

    if app.start(cfg):
        app.stop()