#!/usr/bin/env python3
"""
Smoke script to verify public APIs and session-protected pages.
"""
import os
import subprocess
import sys
import time

import requests


def test_public_apis():
    """Test that public APIs work without authentication"""
    base_url = "http://127.0.0.1:8000"

    print("Testing Public API Endpoints")
    print("=" * 40)

    # Test health endpoint
    try:
        response = requests.get(f"{base_url}/api/health")
        print(f"GET /api/health: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"  Response: {data}")
        else:
            print(f"  Error: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"  Error: {e}")

    # Test readiness endpoint
    try:
        response = requests.get(f"{base_url}/api/health/ready")
        print(f"GET /api/health/ready: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"  Response: {data}")
        else:
            print(f"  Error: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"  Error: {e}")

    # API info remains public.
    try:
        response = requests.get(f"{base_url}/api/info")
        print(f"GET /api/info: {response.status_code}")
        if response.status_code == 200:
            print(f"  Response: {response.json()}")
        else:
            print(f"  Error: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"  Error: {e}")

    # Admin pages are session-protected when bootstrap credentials are configured.
    try:
        response = requests.get(f"{base_url}/admin", allow_redirects=False)
        print(f"GET /admin: {response.status_code}")
        if response.status_code == 303:
            print(f"  Redirected to {response.headers.get('location')}")
        else:
            print(f"  Unexpected: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"  Error: {e}")


def start_server_with_session_auth():
    """Start server with bootstrap administrator credentials."""
    print("Starting server with session authentication...")

    os.environ["TRADER_AUTH_USERNAME"] = "admin"
    os.environ["TRADER_AUTH_PASSWORD"] = "password123A"
    os.environ.setdefault("TRADER_SECRET_KEY", "example-service-secret")

    cmd = [sys.executable, "-m", "trader", "--api", "127.0.0.1:8000"]
    process = subprocess.Popen(cmd)

    print("Waiting for server to start...")
    time.sleep(5)

    return process


def main():
    print("ChainerTrader Public API Test")
    print("=" * 50)

    process = start_server_with_session_auth()

    try:
        # Test public APIs
        test_public_apis()

        print("You can test manually:")
        print("  curl http://localhost:8000/api/health  # Public - should work")
        print("  curl http://localhost:8000/api/info    # Public - should work")
        print("  open http://localhost:8000/login       # Login form")

        # Keep server running
        print("\nPress Ctrl+C to stop the server...")
        process.wait()

    except KeyboardInterrupt:
        print("\nStopping server...")
        process.terminate()
        process.wait()


if __name__ == "__main__":
    main()
