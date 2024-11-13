from datetime import datetime

import uvicorn
import os

from fastapi import FastAPI

from trader.app.app import App
from trader.utils import path


class RPC(FastAPI):
    def __init__(self,app):
        super().__init__()
        self.app=app

    def name(self):
        return "fastapi"

rpc = RPC(App())

def start():
    app_dir = os.path.join(path.GetTraderDir(), 'rpc')
    uvicorn.run(app="rpc:rpc", host="127.0.0.1", port=8000, reload=True,app_dir=app_dir)


@rpc.get("/version")
def read_app_info():
    return {"appInfo": rpc.app.version()}

@rpc.get("/")
def read_root():
    return {"Hello": "I am "+rpc.name()}