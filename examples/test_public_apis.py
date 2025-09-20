#!/usr/bin/env python3
"""
Test script to verify public API functionality
"""
import requests
import time
import subprocess
import sys
import os

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
    
    # Test protected endpoint (should fail)
    try:
        response = requests.get(f"{base_url}/api/info")
        print(f"GET /api/info (protected): {response.status_code}")
        if response.status_code == 401:
            print("  ✓ Correctly protected - requires authentication")
        else:
            print(f"  ✗ Should be protected but returned: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"  Error: {e}")

def start_server_with_protected_paths():
    """Start server with protected paths configured"""
    print("Starting server with protected paths...")
    
    # Set environment variables
    os.environ["TRADER_AUTH_USERNAME"] = "admin"
    os.environ["TRADER_AUTH_PASSWORD"] = "password123"
    os.environ["TRADER_PROTECTED_PATHS"] = "/admin"
    
    # Start server
    cmd = [sys.executable, "-m", "trader", "--api", "127.0.0.1:8000"]
    process = subprocess.Popen(cmd)
    
    # Wait for server to start
    print("Waiting for server to start...")
    time.sleep(5)
    
    return process

def main():
    print("ChainerTrader Protected Paths Test")
    print("=" * 50)
    
    # Start server
    process = start_server_with_protected_paths()
    
    try:
        # Test public APIs
        test_public_apis()
        
        print("\n✓ Protected paths test completed")
        print("You can test manually:")
        print("  curl http://localhost:8000/api/health  # Public - should work")
        print("  curl http://localhost:8000/api/info    # Public - should work")
        print("  curl http://localhost:8000/admin       # Protected - should return 401")
        print("  curl http://localhost:8000/admin/tasks # Protected - should return 401")
        print("  curl -u admin:password123 http://localhost:8000/admin  # Should work with auth")
        print("  curl -u admin:password123 http://localhost:8000/admin/tasks  # Should work with auth")
        
        # Keep server running
        print("\nPress Ctrl+C to stop the server...")
        process.wait()
        
    except KeyboardInterrupt:
        print("\nStopping server...")
        process.terminate()
        process.wait()

if __name__ == "__main__":
    main()
