from pathlib import Path

from trader.common.common import dynamic_load


def parseStrategy(stype):
    current_dir = Path(__file__).parent
    folder_path = current_dir / stype

    if folder_path.is_dir():
        mod = f"trader.strategy.{stype}.{stype}"
    else:
        mod = f"trader.strategy.{stype}"

    return dynamic_load(mod, get_strategy_class_name(stype))


def parse_strategys(stypes: [str]):
    ret = []
    for st in stypes:
        cl = parseStrategy(st)
        if cl is None:
            continue
        ret.append(cl)
    if len(ret) <= 0:
        return None
    return ret


def get_strategy_class_name(file_name: str) -> str:
    return file_name + "Strategy"
