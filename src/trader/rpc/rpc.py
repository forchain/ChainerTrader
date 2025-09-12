import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi_auto_router import AutoRouter
from fastapi.responses import HTMLResponse
from fastapi import Request

from trader.app.app import version
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


def get_directory(sub: str) -> str:
    baseDir = os.path.abspath(os.path.dirname(__file__))
    filePath = os.path.join(baseDir, sub)
    return os.path.realpath(filePath)


rpc = FastAPI(lifespan=lifespan, title="ChainerTrader", description="ChainerTrader", version=version())

rpc.mount("/static", StaticFiles(directory=get_directory("static")), name="static")

templates = Jinja2Templates(directory=get_directory("templates"))


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


@rpc.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@rpc.get("/tasks", response_class=HTMLResponse)
async def tasks_page(request: Request):
    return templates.TemplateResponse("tasks.html", {"request": request})


@rpc.get("/klines", response_class=HTMLResponse)
async def about_page(request: Request):
    return templates.TemplateResponse("klines.html", {"request": request})


@rpc.get("/logs", response_class=HTMLResponse)
async def contact_page(request: Request):
    return templates.TemplateResponse("logs.html", {"request": request})
