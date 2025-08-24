import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi_auto_router import AutoRouter

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

    # Initialize and load routers
    routers_dir = os.path.abspath(os.path.dirname(__file__))
    routers_dir = os.path.join(routers_dir, "api")

    auto_router = AutoRouter(app=rpc, routers_dir=routers_dir, api_prefix="/api")  # relative to current file
    auto_router.load_routers()

    uvicorn.run(
        rpc,
        host=host,
        port=port,
        reload=False,
        app_dir=app_dir,
        log_level=cfg.get_log_level(),
    )


@rpc.get("/")
def read_root():
    return {"Hello": "I am " + rpc.state.app.name()}
