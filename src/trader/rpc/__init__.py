__all__ = ["app", "start"]


def __getattr__(name):
    if name in {"app", "start"}:
        from trader.rpc.app import app, start

        return {"app": app, "start": start}[name]
    raise AttributeError(name)
