import argparse,os

from trader.shihunrsi import shihunRSI
from trader.utils import path
from trader.shihunmacd2 import shihunMACD

def main():
    parser = argparse.ArgumentParser(
        description="Implement TradvingView Algorithms of Youtube Channel Shi Hun",
        epilog="Chainer Labs",
        fromfile_prefix_chars='@')

    parser.add_argument("-v", "--version",help="Version",action="store_true")
    parser.add_argument( "--shihunmacd", help="Supper MACD from ShiHun", action="store_true")
    parser.add_argument("--shihunrsi", help="Supper RSI from ShiHun", action="store_true")
    parser.add_argument('--period', help=('Period for the moving average'),action='store',type=int, default=14,required=False)
    parser.add_argument('--commission', help=('Transaction commission'), action='store', type=float, default=0.001,required=False)
    parser.add_argument("--atr", help="Use atr for stop-loss-point", action="store_true")
    args = parser.parse_args()

    if args.version:
        filePath = os.path.join(path.GetTraderDir(), 'VERSION')

        with open(filePath, "r", encoding="utf-8") as file:
            content = file.read()
            print(content)
    elif args.shihunmacd:
            shihunMACD(True,args.commission,args.atr)
    elif args.shihunrsi:
            shihunRSI(True,args.period,args.commission)

