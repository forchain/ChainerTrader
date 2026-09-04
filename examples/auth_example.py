#!/usr/bin/env python3
"""
Example of how to use ChainerTrader with HTTP Basic Authentication
"""
import os
import subprocess
import sys
import time
import requests
from requests.auth import HTTPBasicAuth

def start_server_with_auth():
    """Start the server with authentication enabled for protected paths"""
    print("Starting ChainerTrader with HTTP Basic Authentication for protected paths...")
    
    # Set environment variables for authentication
    os.environ["TRADER_AUTH_USERNAME"] = "admin"
    os.environ["TRADER_AUTH_PASSWORD"] = "secure_password_123"
    os.environ["TRADER_PROTECTED_PATHS"] = "/admin,/api/admin"
    
    # Start the server
    cmd = [sys.executable, "-m", "trader", "--api", "127.0.0.1:8000"]
    process = subprocess.Popen(cmd)
    
    # Wait for server to start
    print("Waiting for server to start...")
    time.sleep(3)
    
    return process

def test_authenticated_requests():
    """Test making authenticated requests to protected endpoints"""
    base_url = "http://127.0.0.1:8000"
    auth = HTTPBasicAuth("admin", "secure_password_123")
    
    print("\nTesting authenticated requests to protected endpoints...")
    
    # Test protected admin endpoints
    protected_endpoints = ["/admin", "/admin/tasks", "/admin/klines", "/admin/logs", "/api/admin", "/api/admin/users", "/api/admin/system"]
    
    for endpoint in protected_endpoints:
        try:
            response = requests.get(f"{base_url}{endpoint}", auth=auth)
            print(f"{endpoint}: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"  Response: {data}")
        except requests.exceptions.RequestException as e:
            print(f"Error accessing {endpoint}: {e}")

def test_unauthenticated_requests():
    """Test that unauthenticated requests work for public endpoints but fail for protected ones"""
    base_url = "http://127.0.0.1:8000"
    
    print("\nTesting unauthenticated requests...")
    
    # Test public endpoints (should work without auth)
    public_endpoints = ["/api/health", "/api/health/ready", "/api/info", "/api/config", "/api/tasks"]
    print("\nTesting public API endpoints (should work without auth)...")
    
    for endpoint in public_endpoints:
        try:
            response = requests.get(f"{base_url}{endpoint}")
            print(f"{endpoint} (no auth): {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"  Response: {data}")
        except requests.exceptions.RequestException as e:
            print(f"Error accessing {endpoint}: {e}")
    
    # Test protected endpoints (should be rejected)
    protected_endpoints = ["/admin", "/admin/tasks", "/admin/klines", "/admin/logs", "/api/admin", "/api/admin/users", "/api/admin/system"]
    print("\nTesting protected endpoints (should require auth)...")
    
    for endpoint in protected_endpoints:
        try:
            response = requests.get(f"{base_url}{endpoint}")
            print(f"{endpoint} (no auth): {response.status_code}")
            if response.status_code == 401:
                print("  ✓ Correctly protected - requires authentication")
            else:
                print(f"  ✗ Should be protected but returned: {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"Error accessing {endpoint}: {e}")

def main():
    print("ChainerTrader HTTP Basic Authentication Example")
    print("=" * 50)
    
    # Start server
    process = start_server_with_auth()
    
    try:
        # Test authenticated requests
        test_authenticated_requests()
        
        # Test unauthenticated requests
        test_unauthenticated_requests()
        
        print("\n✓ Authentication test completed")
        print("You can now access the web interface at http://127.0.0.1:8000")
        print("Username: admin")
        print("Password: secure_password_123")
        
        # Keep server running
        print("\nPress Ctrl+C to stop the server...")
        process.wait()
        
    except KeyboardInterrupt:
        print("\nStopping server...")
        process.terminate()
        process.wait()

if __name__ == "__main__":
    main()
