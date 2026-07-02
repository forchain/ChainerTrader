from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from trader.auth.credentials import encrypt_secret, mask_api_key
from trader.auth.passwords import hash_password


ROOT = Path(__file__).resolve().parents[2]
RUN_ROOT = ROOT / "tmp" / "acceptance" / "multi_user_runtime_isolation"
REPORT_ROOT = ROOT / "docs" / "acceptance" / "blackbox-orchestrator" / "2026-05-20-multi-user-runtime-isolation"
SAFE_LIVE_TASK = [
    {
        "task_type": "TRADER",
        "symbol": "BTC-USDT",
        "interval": "1m",
        "strategy": "macd_triple_divergence",
        "free": 10000,
        "manual_start_position": 0,
        "live_execution_mode": "manual_notify"
  }
]
SAFE_DEBUG_TASK = [
    {
        "task_type": "DEBUG",
        "limit": 120,
    }
]
REAL_ORDER_LIVE_TASK = [
    {
        "task_type": "TRADER",
        "symbol": "BTC-USDT",
        "interval": "1m",
        "strategy": "smoke_test",
        "free": 1000,
        "manual_start_position": 0,
        "live_execution_mode": "auto_trade",
        "live_trade_max_notional": 11.0,
        "strategy_params": {
            "chainer_mode": "BOTH",
            "smoke_sequence": "long_short",
            "smoke_trigger_steps": "1,2,3,4",
        },
    }
]
BACKTEST_TASK = [
    {
        "task_type": "BACK_TRADER",
        "symbol": "ETH-USDT",
        "interval": "1h",
        "strategy": "macd_triple_divergence",
        "csv": "data/ETHUSDT-1h-202301-202401.csv",
        "start_time": "2023-10-01 00:00:00",
        "end_time": "2024-01-31 23:59:59",
    }
]


@dataclass(frozen=True)
class UserSession:
    username: str
    password: str
    user_id: int
    session: requests.Session


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _run(cmd: list[str], *, env: dict[str, str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, env=env, text=True, capture_output=True, timeout=timeout, check=False)


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required env var: {name}")
    return value


def _acceptance_env(port: int, db_path: Path, log_path: Path, *, mode: str) -> dict[str, str]:
    env = os.environ.copy()
    service_key = env.get("TRADER_SECRET_KEY") or "acceptance-local-service-key-2026-05-20"
    env.update(
        {
            "TRADER_DB": f"sqlite://{db_path}",
            "TRADER_API": f"127.0.0.1:{port}",
            "TRADER_SECRET_KEY": service_key,
            "TRADER_LOG_LEVEL": "DEBUG",
            "TRADER_LOG_FILE": str(log_path),
            "TRADER_AUTH_USERNAME": env.get("TRADER_AUTH_USERNAME") or "accept_admin",
            "TRADER_AUTH_PASSWORD": env.get("TRADER_AUTH_PASSWORD") or "AcceptAdmin2026",
            "TRADER_MIN_LIVE_TRADE_NOTIONAL": "1",
        }
    )
    if mode == "safe":
        env["TRADER_EXCHANGE"] = ""
    return env


def _migrate(env: dict[str, str]) -> None:
    result = _run([sys.executable, "-m", "trader.tools.db", "migrate"], env=env, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"migration failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")


def _optional_env(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _create_users_and_credentials(db_path: Path, service_key: str, *, require_credentials: bool) -> dict[str, int]:
    users = {
        "accept_user_a": {
            "password": "AcceptUserA2026",
            "api_key": _required_env("BINANCE_API_KEY_1") if require_credentials else _optional_env("BINANCE_API_KEY_1"),
            "api_secret": _required_env("BINANCE_API_SECRET_1") if require_credentials else _optional_env("BINANCE_API_SECRET_1"),
        },
        "accept_user_b": {
            "password": "AcceptUserB2026",
            "api_key": _required_env("BINANCE_API_KEY_2") if require_credentials else _optional_env("BINANCE_API_KEY_2"),
            "api_secret": _required_env("BINANCE_API_SECRET_2") if require_credentials else _optional_env("BINANCE_API_SECRET_2"),
        },
    }
    user_ids: dict[str, int] = {}
    with sqlite3.connect(db_path) as connection:
        for username, payload in users.items():
            row = connection.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            if row is None:
                cursor = connection.execute(
                    """
                    INSERT INTO users (username, password_hash, role, status, must_change_password, created_at, updated_at)
                    VALUES (?, ?, 'user', 'active', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (username, hash_password(payload["password"])),
                )
                user_id = int(cursor.lastrowid)
            else:
                user_id = int(row[0])
                connection.execute(
                    """
                    UPDATE users
                    SET password_hash = ?, status = 'active', must_change_password = 0, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (hash_password(payload["password"]), user_id),
                )
            if payload["api_key"] and payload["api_secret"]:
                connection.execute(
                    """
                    INSERT INTO exchange_credentials
                        (user_id, exchange, label, encrypted_api_key, encrypted_api_secret, masked_api_key, created_at, updated_at)
                    VALUES (?, 'BINANCE', 'default', ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_id, exchange, label)
                    DO UPDATE SET
                        encrypted_api_key = excluded.encrypted_api_key,
                        encrypted_api_secret = excluded.encrypted_api_secret,
                        masked_api_key = excluded.masked_api_key,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        user_id,
                        encrypt_secret(service_key, payload["api_key"]),
                        encrypt_secret(service_key, payload["api_secret"]),
                        mask_api_key(payload["api_key"]),
                    ),
                )
            user_ids[username] = user_id
        connection.commit()
    return user_ids


def _start_server(env: dict[str, str], stdout_path: Path) -> subprocess.Popen:
    stdout = stdout_path.open("w", encoding="utf-8")
    return subprocess.Popen(
        [sys.executable, "-m", "trader", "--api", env["TRADER_API"]],
        cwd=ROOT,
        env=env,
        stdout=stdout,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )


def _wait_for_server(base_url: str, process: subprocess.Popen, timeout: int = 45) -> None:
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"server exited early with code {process.returncode}")
        try:
            response = requests.get(f"{base_url}/name", timeout=2)
            if response.status_code == 200:
                return
            last_error = f"HTTP {response.status_code}"
        except requests.RequestException as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise RuntimeError(f"server did not become ready: {last_error}")


def _login(base_url: str, username: str, password: str, user_id: int) -> UserSession:
    session = requests.Session()
    response = session.post(
        f"{base_url}/login",
        data={"username": username, "password": password},
        allow_redirects=False,
        timeout=10,
    )
    if response.status_code != 303:
        raise RuntimeError(f"login failed for {username}: HTTP {response.status_code} {response.text[:200]}")
    return UserSession(username=username, password=password, user_id=user_id, session=session)


def _lookup_user_id(db_path: Path, username: str) -> int:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if row is None:
        raise RuntimeError(f"user not found: {username}")
    return int(row[0])


def _post_task(base_url: str, user: UserSession, task: list[dict[str, Any]]) -> dict[str, Any]:
    response = user.session.post(f"{base_url}/api/tasks", data=json.dumps(task), timeout=20)
    if response.status_code >= 400:
        return {"http_status": response.status_code, "body": response.text}
    payload = response.json()
    payload["http_status"] = response.status_code
    return payload


def _get_json(base_url: str, user: UserSession, path: str) -> Any:
    response = user.session.get(f"{base_url}{path}", timeout=20)
    response.raise_for_status()
    return response.json()


def _wait_for_task(base_url: str, user: UserSession, task_id: int, *, expected_states: set[str], timeout: int = 30) -> dict[str, Any]:
    deadline = time.time() + timeout
    latest: dict[str, Any] = {}
    while time.time() < deadline:
        tasks = _get_json(base_url, user, "/api/tasks")
        latest = {"tasks": tasks}
        for task in tasks:
            if int(task.get("task_id", -1)) == int(task_id):
                latest = task
                if task.get("state") in expected_states:
                    return latest
        time.sleep(1)
    raise RuntimeError(f"task {task_id} did not reach {sorted(expected_states)}; latest={_json(latest)}")


def _wait_for_task_not_running(base_url: str, user: UserSession, task_id: int, *, timeout: int = 60) -> dict[str, Any]:
    deadline = time.time() + timeout
    latest: dict[str, Any] = {}
    while time.time() < deadline:
        tasks = _get_json(base_url, user, "/api/tasks")
        latest = {"tasks": tasks}
        for task in tasks:
            if int(task.get("task_id", -1)) == int(task_id):
                latest = task
                if task.get("state") != "RUNNING":
                    return latest
        time.sleep(1)
    raise RuntimeError(f"task {task_id} stayed RUNNING after close; latest={_json(latest)}")


def _task_id_from_create(payload: dict[str, Any]) -> int:
    tasks = payload.get("tasks") or []
    if not tasks:
        raise RuntimeError(f"task creation did not return task ids: {_json(payload)}")
    return int(tasks[0]["id"])


def _close_task(base_url: str, user: UserSession, task_id: int) -> dict[str, Any]:
    response = user.session.post(f"{base_url}/api/task", params={"id": task_id}, timeout=10)
    try:
        return {"http_status": response.status_code, "body": response.json()}
    except ValueError:
        return {"http_status": response.status_code, "body": response.text}


def _find_task(tasks: list[dict[str, Any]], task_id: int) -> dict[str, Any] | None:
    for task in tasks:
        if int(task.get("task_id", -1)) == int(task_id):
            return task
    return None


def _assert_task_hidden(tasks: list[dict[str, Any]], task_id: int, message: str) -> None:
    if _find_task(tasks, task_id) is not None:
        raise RuntimeError(message)


def _collect_credential_evidence(db_path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT u.id, u.username, u.role, c.exchange, c.label, c.masked_api_key
            FROM users u
            JOIN exchange_credentials c ON c.user_id = u.id
            WHERE u.role = 'admin' OR u.username IN ('accept_user_a', 'accept_user_b')
            ORDER BY u.role, u.username
            """
        ).fetchall()
    return [
        {"user_id": row[0], "username": row[1], "role": row[2], "exchange": row[3], "label": row[4], "masked_api_key": row[5]}
        for row in rows
    ]


def _tail(path: Path, *, lines: int = 80) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]


def _live_strategy_ids(strategies: list[dict[str, Any]]) -> set[int]:
    return {int(item["strategy_id"]) for item in strategies if "strategy_id" in item}


def _assert_two_user_credentials_are_distinct(credentials: list[dict[str, Any]]) -> None:
    user_credentials = {
        row["username"]: row["masked_api_key"]
        for row in credentials
        if row.get("username") in {"accept_user_a", "accept_user_b"}
    }
    if set(user_credentials) != {"accept_user_a", "accept_user_b"}:
        raise RuntimeError(f"missing user credential evidence: {_json(credentials)}")
    if user_credentials["accept_user_a"] == user_credentials["accept_user_b"]:
        raise RuntimeError("acceptance users must use different Binance API keys")


def run_acceptance(mode: str, observation_seconds: int) -> dict[str, Any]:
    load_dotenv(ROOT / ".env")
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = RUN_ROOT / f"runtime-{int(time.time())}.db"
    log_path = RUN_ROOT / "server.log"
    stdout_path = RUN_ROOT / "server.stdout.log"
    evidence_path = RUN_ROOT / "evidence.json"
    log_path.write_text("", encoding="utf-8")
    stdout_path.write_text("", encoding="utf-8")
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = _acceptance_env(port, db_path, log_path, mode=mode)
    env["TRADER_TASKS"] = json.dumps(SAFE_DEBUG_TASK if mode == "safe" else [])
    if mode == "real-order" and os.getenv("CHAINERTRADER_ACCEPT_REAL_ORDERS") != "1":
        raise RuntimeError("real-order mode requires CHAINERTRADER_ACCEPT_REAL_ORDERS=1")

    _migrate(env)
    user_ids = _create_users_and_credentials(db_path, env["TRADER_SECRET_KEY"], require_credentials=mode in {"live-safe", "mixed-safe", "real-order"})
    process = _start_server(env, stdout_path)
    evidence: dict[str, Any] = {
        "mode": mode,
        "base_url": base_url,
        "pid": process.pid,
        "db_path": str(db_path),
        "log_path": str(log_path),
        "stdout_path": str(stdout_path),
        "checks": {},
    }
    try:
        _wait_for_server(base_url, process)
        admin_user_id = _lookup_user_id(db_path, env["TRADER_AUTH_USERNAME"])
        admin = _login(base_url, env["TRADER_AUTH_USERNAME"], env["TRADER_AUTH_PASSWORD"], admin_user_id)
        user_a = _login(base_url, "accept_user_a", "AcceptUserA2026", user_ids["accept_user_a"])
        user_b = _login(base_url, "accept_user_b", "AcceptUserB2026", user_ids["accept_user_b"])
        admin_tasks = _get_json(base_url, admin, "/api/tasks")
        evidence["checks"]["credentials"] = _collect_credential_evidence(db_path)
        evidence["checks"]["startup_admin_tasks"] = admin_tasks
        if mode in {"live-safe", "mixed-safe", "real-order"}:
            _assert_two_user_credentials_are_distinct(evidence["checks"]["credentials"])
        if mode == "safe" and not any(int(task.get("user_id", -1)) == admin_user_id for task in admin_tasks):
            raise RuntimeError("startup task was not visible under the bootstrap administrator")

        live_task = REAL_ORDER_LIVE_TASK if mode == "real-order" else SAFE_LIVE_TASK if mode == "live-safe" else SAFE_DEBUG_TASK
        if mode == "mixed-safe":
            live_task = SAFE_LIVE_TASK
            created_live = _post_task(base_url, user_a, live_task)
            created_backtest = _post_task(base_url, user_b, BACKTEST_TASK)
            live_task_id = _task_id_from_create(created_live)
            backtest_task_id = _task_id_from_create(created_backtest)
            live_status = _wait_for_task(base_url, user_a, live_task_id, expected_states={"RUNNING"})
            backtest_seen = _wait_for_task(base_url, user_b, backtest_task_id, expected_states={"RUNNING", "DONE"}, timeout=45)
            mixed_live = _get_json(base_url, user_a, "/api/live/strategies")
            mixed_tasks_a = _get_json(base_url, user_a, "/api/tasks")
            mixed_tasks_b = _get_json(base_url, user_b, "/api/tasks")
            evidence["checks"]["mixed_live_backtest"] = {
                "created_live": created_live,
                "created_backtest": created_backtest,
                "live_status": live_status,
                "backtest_seen": backtest_seen,
                "live_a": mixed_live,
                "tasks_a": mixed_tasks_a,
                "tasks_b": mixed_tasks_b,
            }
            if live_task_id not in _live_strategy_ids(mixed_live):
                raise RuntimeError("user A live strategy is not visible as running during mixed acceptance")
            _assert_task_hidden(mixed_tasks_a, backtest_task_id, "user A can see user B backtest task")
            _assert_task_hidden(mixed_tasks_b, live_task_id, "user B can see user A live task")
            evidence["status"] = "passed"
            evidence["checks"]["server_log_tail"] = _tail(log_path)
            return evidence

        created_a = _post_task(base_url, user_a, live_task)
        created_b = _post_task(base_url, user_b, live_task)
        task_a = _task_id_from_create(created_a)
        task_b = _task_id_from_create(created_b)
        status_a = _wait_for_task(base_url, user_a, task_a, expected_states={"RUNNING"})
        status_b = _wait_for_task(base_url, user_b, task_b, expected_states={"RUNNING"})
        live_a = _get_json(base_url, user_a, "/api/live/strategies")
        live_b = _get_json(base_url, user_b, "/api/live/strategies")
        duplicate_a = _post_task(base_url, user_a, SAFE_LIVE_TASK)
        tasks_a = _get_json(base_url, user_a, "/api/tasks")
        tasks_b = _get_json(base_url, user_b, "/api/tasks")
        evidence["checks"]["two_live_tasks"] = {
            "created_a": created_a,
            "created_b": created_b,
            "status_a": status_a,
            "status_b": status_b,
            "live_a": live_a,
            "live_b": live_b,
            "duplicate_a": duplicate_a,
            "tasks_a": tasks_a,
            "tasks_b": tasks_b,
        }
        if mode in {"live-safe", "real-order"}:
            if task_a not in _live_strategy_ids(live_a):
                raise RuntimeError("user A live strategy is not visible as running")
            if task_b not in _live_strategy_ids(live_b):
                raise RuntimeError("user B live strategy is not visible as running")
        if duplicate_a.get("http_status") != 409:
            raise RuntimeError(f"expected duplicate task rejection for user A, got {_json(duplicate_a)}")
        _assert_task_hidden(tasks_a, task_b, "user A can see user B task")
        _assert_task_hidden(tasks_b, task_a, "user B can see user A task")
        time.sleep(max(0, int(observation_seconds)))
        evidence["checks"]["close_live_tasks"] = {
            "close_a": _close_task(base_url, user_a, task_a),
            "close_b": _close_task(base_url, user_b, task_b),
        }
        evidence["checks"]["close_live_tasks"]["settled_a"] = _wait_for_task_not_running(base_url, user_a, task_a)
        evidence["checks"]["close_live_tasks"]["settled_b"] = _wait_for_task_not_running(base_url, user_b, task_b)

        if mode in {"safe", "live-safe"}:
            evidence["checks"]["server_log_tail"] = _tail(log_path)
            evidence["status"] = "passed"
            return evidence

        created_live = _post_task(base_url, user_a, live_task)
        created_backtest = _post_task(base_url, user_b, BACKTEST_TASK)
        live_task_id = _task_id_from_create(created_live)
        backtest_task_id = _task_id_from_create(created_backtest)
        live_status = _wait_for_task(base_url, user_a, live_task_id, expected_states={"RUNNING"})
        backtest_seen = _wait_for_task(base_url, user_b, backtest_task_id, expected_states={"RUNNING", "DONE"}, timeout=45)
        mixed_tasks_a = _get_json(base_url, user_a, "/api/tasks")
        mixed_tasks_b = _get_json(base_url, user_b, "/api/tasks")
        evidence["checks"]["mixed_live_backtest"] = {
            "created_live": created_live,
            "created_backtest": created_backtest,
            "live_status": live_status,
            "backtest_seen": backtest_seen,
            "tasks_a": mixed_tasks_a,
            "tasks_b": mixed_tasks_b,
        }
        if backtest_task_id in {int(item.get("task_id", -1)) for item in mixed_tasks_a}:
            raise RuntimeError("user A can see user B backtest task")
        if live_task_id in {int(item.get("task_id", -1)) for item in mixed_tasks_b}:
            raise RuntimeError("user B can see user A live task")
        evidence["checks"]["close_mixed_tasks"] = {
            "close_live": _close_task(base_url, user_a, live_task_id),
            "settled_live": _wait_for_task_not_running(base_url, user_a, live_task_id),
        }
        evidence["checks"]["server_log_tail"] = _tail(log_path)
        evidence["status"] = "passed"
        return evidence
    except Exception as exc:
        evidence["status"] = "failed"
        evidence["error"] = str(exc)
        try:
            evidence["checks"]["credentials_after_failure"] = _collect_credential_evidence(db_path)
        except Exception as evidence_exc:
            evidence["checks"]["credential_collection_error"] = str(evidence_exc)
        evidence["checks"]["server_log_tail"] = _tail(log_path)
        evidence["checks"]["server_stdout_tail"] = _tail(stdout_path)
        raise
    finally:
        evidence_path.write_text(_json(evidence), encoding="utf-8")
        with (REPORT_ROOT / "execution-report.md").open("a", encoding="utf-8") as handle:
            handle.write(f"\n## Run {time.strftime('%Y-%m-%d %H:%M:%S %z')}\n\n")
            handle.write(f"Evidence artifact: `{evidence_path}`\n\n")
            handle.write(f"Status: `{evidence.get('status', 'unknown')}`\n\n")
            if evidence.get("error"):
                handle.write(f"Error: `{evidence['error']}`\n\n")
        try:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=10)
        except Exception:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run multi-user runtime isolation black-box acceptance.")
    parser.add_argument("--mode", choices=["safe", "live-safe", "mixed-safe", "real-order"], default="safe")
    parser.add_argument("--observation-seconds", type=int, default=10)
    args = parser.parse_args()
    try:
        evidence = run_acceptance(args.mode, args.observation_seconds)
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    print(_json(evidence))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
