#!/usr/bin/env python3
"""
Smoke script to verify admin pages behind the session login flow.
"""
import os
import subprocess
import sys
import time

import requests


def start_server_with_admin_protection():
    """Start server with bootstrap admin credentials."""
    print("Starting ChainerTrader with session authentication...")

    os.environ["TRADER_AUTH_USERNAME"] = "admin"
    os.environ["TRADER_AUTH_PASSWORD"] = "password123A"
    os.environ.setdefault("TRADER_SECRET_KEY", "example-service-secret")

    cmd = [sys.executable, "-m", "trader", "--api", "127.0.0.1:8000"]
    process = subprocess.Popen(cmd)

    print("Waiting for server to start...")
    time.sleep(5)

    return process


def login(session: requests.Session, base_url: str):
    response = session.post(
        f"{base_url}/login",
        data={"username": "admin", "password": "password123A"},
        allow_redirects=False,
    )
    print(f"POST /login: {response.status_code}")
    return response


def test_admin_pages():
    """Test all admin pages with and without a session cookie."""
    base_url = "http://127.0.0.1:8000"
    session = requests.Session()

    print("Testing Admin Pages")
    print("=" * 50)

    pages = [
        ("/", "Root redirect"),
        ("/admin", "Admin dashboard"),
        ("/admin/tasks", "Admin tasks page"),
        ("/admin/klines", "Admin klines page"),
        ("/admin/live", "Live monitor page"),
        ("/admin/logs", "Admin logs page"),
        ("/admin/users", "User management page"),
    ]

    print("\n1. Testing without authentication (should redirect to login):")
    print("-" * 60)

    for path, description in pages:
        try:
            response = requests.get(f"{base_url}{path}", allow_redirects=False)
            if response.status_code in {303, 307}:
                print(f"OK {path:<15} - {description} redirected to {response.headers.get('location')}")
            else:
                print(f"FAIL {path:<15} - {description} unexpected status {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"FAIL {path:<15} - {description} error: {e}")

    print("\n2. Logging in and testing authenticated pages:")
    print("-" * 60)
    login(session, base_url)

    for path, description in pages:
        try:
            response = session.get(f"{base_url}{path}")
            if response.status_code == 200:
                print(f"OK {path:<15} - {description} accessible")
            else:
                print(f"FAIL {path:<15} - {description} status {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"FAIL {path:<15} - {description} error: {e}")

    print("\n3. Testing navigation links:")
    print("-" * 60)

    try:
        response = session.get(f"{base_url}/admin")
        if response.status_code == 200:
            content = response.text
            nav_checks = [
                ('href="/admin"', "Home link"),
                ('href="/admin/tasks"', "Tasks link"),
                ('href="/admin/klines"', "Klines link"),
                ('href="/admin/live"', "Live monitor link"),
                ('href="/admin/logs"', "Logs link"),
                ('href="/admin/users"', "User management link"),
                ('href="/account"', "Account link"),
            ]

            for link, description in nav_checks:
                if link in content:
                    print(f"OK {description} found in navigation")
                else:
                    print(f"FAIL {description} missing from navigation")
        else:
            print(f"FAIL Could not load admin dashboard: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"FAIL Error testing navigation: {e}")


def main():
    print("ChainerTrader Admin Pages Test")
    print("=" * 50)

    # Start server
    process = start_server_with_admin_protection()

    try:
        # Test admin pages
        test_admin_pages()

        print("\nYou can test manually:")
        print("  open http://localhost:8000/login")
        print("  username: admin")
        print("  password: password123A")

        # Keep server running
        print("\nPress Ctrl+C to stop the server...")
        process.wait()

    except KeyboardInterrupt:
        print("\nStopping server...")
        process.terminate()
        process.wait()


if __name__ == "__main__":
    main()
