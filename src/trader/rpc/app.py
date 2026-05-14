import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi_auto_router import AutoRouter

from trader.app.app import version
from trader.common import path
from trader.common.common import NAME
from trader.common.config import Config
from trader.live.monitor import GLOBAL_LIVE_EVENT_BUS
from trader.rpc.auth import BasicAuthMiddleware
from trader.rpc.models import get_accounts_info, get_klines_info, get_logs_info, get_taskinfo
from trader.rpc.rpc_app import RpcApp


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = getattr(app.state, "cfg", None)
    if cfg is None:
        yield
        return

    rpc_app = RpcApp(cfg)
    app.state.app = rpc_app
    app.state.live_event_bus = GLOBAL_LIVE_EVENT_BUS

    rpc_app.start()
    await rpc_app.wait_until_handler_ready()
    rpc_app.raise_main_task_error()
    yield
    await rpc_app.stop()


def get_directory(sub: str) -> str:
    baseDir = os.path.abspath(os.path.dirname(__file__))
    filePath = os.path.join(baseDir, sub)
    return os.path.realpath(filePath)


app = FastAPI(lifespan=lifespan, title="ChainerTrader", description="ChainerTrader", version=version())

app.mount("/static", StaticFiles(directory=get_directory("static")), name="static")

templates = Jinja2Templates(directory=get_directory("templates"))


def _require_rpc_app(request: Request) -> RpcApp:
    rpc_app = getattr(request.app.state, "app", None)
    if rpc_app is None:
        raise HTTPException(status_code=503, detail="RPC application is not initialized")
    return rpc_app


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

    app.state.cfg = cfg

    # Add authentication middleware if enabled
    if cfg.is_auth_enabled():
        app.add_middleware(BasicAuthMiddleware, config=cfg)

    # Initialize and load routers
    routers_dir = os.path.abspath(os.path.dirname(__file__))
    routers_dir = os.path.join(routers_dir, "api")

    auto_router = AutoRouter(app=app, routers_dir=routers_dir, api_prefix="/api")  # relative to current file
    auto_router.load_routers()

    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=False,
        app_dir=app_dir,
        log_level=cfg.get_log_level(),
    )


@app.get("/")
async def read_root():
    return RedirectResponse(url="/admin")


@app.get("/name")
async def read_name():
    return {"name": NAME}


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    rpc_app = _require_rpc_app(request)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "tasks_info": await get_taskinfo(rpc_app),
            "accts_info": get_accounts_info(rpc_app),
            "version": rpc_app.version(),
        },
    )


@app.get("/admin/tasks", response_class=HTMLResponse)
async def admin_tasks_page(request: Request):
    rpc_app = _require_rpc_app(request)
    return templates.TemplateResponse(request, "tasks.html", {"tasks_info": await get_taskinfo(rpc_app)})


@app.get("/admin/klines", response_class=HTMLResponse)
async def admin_klines_page(request: Request):
    rpc_app = _require_rpc_app(request)
    return templates.TemplateResponse(request, "klines.html", {"klines_info": await get_klines_info(rpc_app)})


@app.get("/admin/live", response_class=HTMLResponse)
async def admin_live_page(request: Request):
    _require_rpc_app(request)
    return templates.TemplateResponse(request, "live.html", {})


@app.get("/admin/logs", response_class=HTMLResponse)
async def admin_logs_page(request: Request):
    rpc_app = _require_rpc_app(request)
    return templates.TemplateResponse(request, "logs.html", {"logs_info": get_logs_info(rpc_app)})


@app.get("/.well-known/appspecific/com.chrome.devtools.json")
async def chrome_devtools_well_known():
    return Response(status_code=204)

