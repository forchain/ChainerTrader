from pathlib import Path

import trader.adapters.outbound.backtrader as backtrader_strategies
from trader.common.common import dynamic_load
from trader.utils.strings import capitalize_first

_STRATEGY_PACKAGE = "trader.adapters.outbound.backtrader"
_STRATEGY_DIR = Path(backtrader_strategies.__file__).parent


def parse_strategy(stype):
    # 如果 stype 包含., 则.之前的部分为模块，.之后的部分为类名
    groups = stype.split(".")
    if len(groups) > 1:
        module_name = f"{_STRATEGY_PACKAGE}.{groups[0]}"
        class_name = get_strategy_class_name(groups[1])
        return dynamic_load(module_name, class_name)

    folder_path = _STRATEGY_DIR / stype

    if folder_path.is_dir():
        mod = f"{_STRATEGY_PACKAGE}.{stype}.{stype}"
    else:
        mod = f"{_STRATEGY_PACKAGE}.{stype}"

    return dynamic_load(mod, get_strategy_class_name(stype))


def parse_strategies(stypes: [str]):
    ret = []
    for st in stypes:
        cl = parse_strategy(st)
        if cl is None:
            continue
        ret.append(cl)
    if len(ret) <= 0:
        return None
    return ret


def get_strategy_class_name(file_name: str) -> str:
    parts = file_name.split("_")
    class_name = "".join(capitalize_first(word) for word in parts if word)
    if class_name:
        class_name = class_name[0].upper() + class_name[1:]
    return class_name + "Strategy"
