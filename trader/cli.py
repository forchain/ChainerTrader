import argparse,os

from trader.shihunrsi import shihunRSI
from trader.utils import path
from trader.shihunmacd import shihunMACD

def main():
    parser = argparse.ArgumentParser(
        description="Implement TradvingView Algorithms of Youtube Channel Shi Hun",
        epilog="Chainer Labs",
        fromfile_prefix_chars='@')

    parser.add_argument("-v", "--version",help="Version",action="store_true")
    parser.add_argument( "--shihunmacd", help="Supper MACD from ShiHun", action="store_true")
    parser.add_argument("--shihunrsi", help="Supper RSI from ShiHun", action="store_true")

    args = parser.parse_args()

    if args.version:
        filePath = os.path.join(path.GetTraderDir(), 'VERSION')

        with open(filePath, "r", encoding="utf-8") as file:
            content = file.read()
            print(content)
    elif args.shihunmacd:
            shihunMACD(True)
    elif args.shihunrsi:
            shihunRSI(True)

