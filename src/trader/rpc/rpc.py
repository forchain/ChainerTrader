import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request

from trader.common import path
from trader.common.config import Config
from trader.rpc.rpc_app import RpcApp


@asynccontextmanager
async def lifespan(rpc: FastAPI):
    app = RpcApp(rpc.state.cfg)
    rpc.state.app = app

    app.start()
    yield
    await app.stop()


rpc = FastAPI(lifespan=lifespan)


def start(cfg: Config):
    app_dir = os.path.join(path.GetTraderDir(), "rpc")

    bind_addr: str = "127.0.0.1:8000"
    if cfg.api:
        bind_addr = cfg.api

    # Parse bind address and port
    if ":" in bind_addr:
        host, port = bind_addr.rsplit(":", 1)
        if not host:  # Handle case like ":8000"
            host = "127.0.0.1"
        port = int(port)
    else:
        host = bind_addr
        port = 8000

    rpc.state.cfg = cfg
    uvicorn.run(
        rpc,
        host=host,
        port=port,
        reload=False,
        app_dir=app_dir,
        log_level=cfg.get_log_level(),
    )


@rpc.get("/version")
def read_app_version():
    return {"version": rpc.state.app.version()}


@rpc.get("/")
def read_root():
    return {"Hello": "I am " + rpc.state.app.name()}


@rpc.get("/info")
def read_app_info():
    return rpc.state.app.info()


@rpc.get("/name")
def read_app_name():
    return {"name": rpc.state.app.name()}


@rpc.get("/config")
def read_app_config():
    return rpc.state.app.cfg.to_dict()


@rpc.post("/tasks")
async def add_tasks(request: Request):
    raw_bytes = await request.body()
    cfg = raw_bytes.decode("utf-8")
    return rpc.state.app.send_add_tasks_msg(cfg)


@rpc.get("/task")
def read_start_app(id: int):
    pass


@rpc.get("/update_klines_task")
def update_kines_task():
    return rpc.state.app.task_manager.add_task()


@rpc.get("/operates/")
def read_start_app(limit: int = 10):
    return rpc.state.app.stat.get_operates()


@rpc.get("/exchange_info")
def read_exchange_info(symbol: str):
    if len(symbol) <= 0:
        return {"error": "must config symbol"}
    return rpc.state.app.exchange.get_exchange_info(symbol)


@rpc.get("/accout")
def read_account():
    return rpc.state.app.exchange.get_account()
