import uvicorn
import os

from fastapi import FastAPI

from trader.app.app import App
from trader.common.config import NewConfigFromEnv, Config
from trader.common import path


class RPC(FastAPI):
    def __init__(self):
        super().__init__()
        self.app = App()

        fastapi_server = bool(os.environ.get('fastapi_server'))
        if not fastapi_server:
            return

        self.app.start(NewConfigFromEnv())

    def name(self):
        return "fastapi"

rpc = RPC()

def start(cfg:Config):
    cfg.exportEnv()
    os.environ['fastapi_server'] = str(True)
    app_dir = os.path.join(path.GetTraderDir(), 'rpc')
    uvicorn.run(app="rpc:rpc", host="127.0.0.1", port=8000, reload=False,app_dir=app_dir)


@rpc.get("/version")
def read_app_version():
    return {"version": rpc.app.version()}

@rpc.get("/")
def read_root():
    return {"Hello": "I am "+rpc.name()}

@rpc.get("/info")
def read_app_info():
    return rpc.app.info()

@rpc.get("/name")
def read_app_name():
    return {"name": rpc.app.name()}

@rpc.get("/config")
def read_app_config():
    return rpc.app.cfg.to_dict()