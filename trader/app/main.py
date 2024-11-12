import argparse,os

from trader.app.app import App


def main():
    app = App()

    parser = argparse.ArgumentParser(
        description="Implement TradvingView Algorithms of Youtube Channel Shi Hun",
        epilog="Chainer Labs",
        fromfile_prefix_chars='@')

    parser.add_argument("-v", "--version",help="Version",action="store_true")
    parser.add_argument("-s", "--strategy", type=str, help="strategy type: ShihunMACD, ShihunRSI, ShihunMACD2, ShihunRSI2, ShihunMACDRISBB, ShihunMACDRSIBBUP")
    parser.add_argument( "--shihunmacd", help="Supper MACD from ShiHun", action="store_true")
    parser.add_argument("--shihunrsi", help="Supper RSI from ShiHun", action="store_true")
    parser.add_argument("--shihunmacdrsibb", help="MACD + RSI + BollingerBand from ShiHun", action="store_true")
    parser.add_argument('--period', help=('Period for the moving average'),action='store',type=int, default=14,required=False)
    parser.add_argument('--commission', help=('Transaction commission'), action='store', type=float, default=0.001,required=False)
    parser.add_argument("--atr", help="Use atr for stop-loss-point", action="store_true")
    parser.add_argument("--trend", help="Only operate in a market environment that follows the trend", action="store_true")
    args = parser.parse_args()

    if args.version:
        print(app.version())
        return
    elif args.strategy is None:
        app.log().error("You must configure --strategy")
        return

    if app.start(args.strategy):
        app.stop()