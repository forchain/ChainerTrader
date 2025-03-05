from enum import Enum

from trader.common.common import dynamic_load
from trader.strategy.boll_mean_reg import BollingerMeanRegStrategy
from trader.strategy.dualma import DualMovingAverageStrategy
from trader.strategy.dualthrust import DualThrustStrategy
from trader.strategy.grid import GridStrategy
from trader.strategy.kdj import KDJStrategy
from trader.strategy.macdrsi import MACDRSIStrategy
from trader.strategy.rsrs import RSRSStrategy
from trader.strategy.shihunmacd import ShihunMACDStrategy
from trader.strategy.shihunmacd2 import ShihunMACD2Strategy
from trader.strategy.shihunmacdrsibb import ShihunMacdRsiBollingerBandStrategy
from trader.strategy.shihunrsi import ShihunRSIStrategy
from trader.strategy.shihunrsi2 import ShihunRSI2Strategy
from trader.strategy.turtle import TurtleStrategy

def parseStrategy(stype):
    return dynamic_load(stype, get_strategy_class_name(stype))

def parse_strategys(stypes:[str]):
    ret=[]
    for st in stypes:
        cl=parseStrategy(st)
        if cl is None:
            continue
        ret.append(cl)
    if len(ret) <= 0:
        return None
    return ret

def get_strategy_class_name(file_name:str)->str:
    return file_name+"Strategy"