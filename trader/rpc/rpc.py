import time
from datetime import datetime

import uvicorn
import os

from fastapi import FastAPI

from trader.app.app import App
from trader.common.config import NewConfigFromEnv, Config
from trader.common import path
from multiprocessing import Process, Manager


class RPC(FastAPI):
    def __init__(self):
        super().__init__()
        self.app=None
        self.proc=None
        self.shared_dict=None

    def start(self):
        if self.app:
            return {"result","Already running"}
        self.app = App(NewConfigFromEnv())
        self.app.log().info(f"Start RPC {rpc.name()}")

        manager=Manager()
        self.shared_dict = manager.dict()
        self.shared_dict['app'] = self.app
        self.proc = Process(target=startApp, args=(self.shared_dict,))
        self.proc.start()

        return {"result","success"}

    def stop(self):
        self.app.log().info(f"Stop RPC {self.name()}")
        if self.proc:
            self.proc.join()

    def name(self):
        return "fastapi"

rpc = RPC()

def start(cfg:Config):
    cfg.exportEnv()
    app_dir = os.path.join(path.GetTraderDir(), 'rpc')
    uvicorn.run(app="rpc:rpc", host="127.0.0.1", port=8000, reload=False,app_dir=app_dir,log_level=cfg.get_log_level())

def startApp(shared_dict):
    app = shared_dict['app']
    if app.start():
        app.stop()

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

@rpc.get("/start")
def read_start_app():
    return rpc.start()

@rpc.get("/exchange_info")
def read_exchange_info(symbol:str):
    if len(symbol) <= 0:
        return {"error":"must config symbol"}
    return rpc.app.exchange.get_exchange_info(symbol)

@rpc.get("/update_klines_task")
def update_kines_task():
    return rpc.app.task_manager.add_task()

@rpc.get("/operates/")
def read_start_app(limit:int = 10):
    return rpc.app.stat.get_operates()
