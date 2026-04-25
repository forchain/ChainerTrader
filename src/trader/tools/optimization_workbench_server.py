from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def build_workbench_url(base_url: str, run_id: str) -> str:
    query = urlencode({"run_id": run_id})
    return f"{base_url.rstrip('/')}/src/trader/rpc/static/optimization-workbench/index.html?{query}"


def serve_workbench(run_id: str, host: str = "127.0.0.1", port: int = 8765) -> tuple[ThreadingHTTPServer, str]:
    root = repo_root()
    handler = partial(SimpleHTTPRequestHandler, directory=str(root))
    server = ThreadingHTTPServer((host, port), handler)
    actual_host, actual_port = server.server_address[:2]
    url = build_workbench_url(f"http://{actual_host}:{actual_port}", run_id)
    return server, url
