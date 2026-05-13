__all__ = ["rpc", "start"]


def __getattr__(name):
    if name in {"rpc", "start"}:
        from trader.rpc.rpc import rpc, start

        return {"rpc": rpc, "start": start}[name]
    raise AttributeError(name)
