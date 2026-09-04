from __future__ import annotations

import argparse

from trader.tools.optimization_workbench_server import serve_workbench


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the optimization validation workbench over HTTP.")
    parser.add_argument("--run-id", required=True, help="Optimization run id under reports/optimizations/")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8765, help="Bind port (0 for random)")
    args = parser.parse_args()

    server, url = serve_workbench(args.run_id, host=args.host, port=args.port)
    print(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
