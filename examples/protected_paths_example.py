#!/usr/bin/env python3
"""
Example demonstrating the new protected paths authentication strategy
"""
import os
import subprocess
import sys
import time
import requests
from requests.auth import HTTPBasicAuth

def start_server_with_protected_paths():
    """Start server with different protected path configurations"""
    print("Starting ChainerTrader with protected paths authentication...")
    
    # Set environment variables
    os.environ["TRADER_AUTH_USERNAME"] = "admin"
    os.environ["TRADER_AUTH_PASSWORD"] = "secure_password"
    os.environ["TRADER_PROTECTED_PATHS"] = "/admin,/api/admin"
    
    # Start server
    cmd = [sys.executable, "-m", "trader", "--api", "127.0.0.1:8000"]
    process = subprocess.Popen(cmd)
    
    # Wait for server to start
    print("Waiting for server to start...")
    time.sleep(5)
    
    return process

def test_authentication_strategy():
    """Test the new authentication strategy"""
    base_url = "http://127.0.0.1:8000"
    auth = HTTPBasicAuth("admin", "secure_password")
    
    print("Testing Protected Paths Authentication Strategy")
    print("=" * 60)
    
    # Test cases
    test_cases = [
        # (endpoint, should_require_auth, description)
        ("/api/health", False, "Health check - should be public"),
        ("/api/info", False, "System info - should be public"),
        ("/api/config", False, "Configuration - should be public"),
        ("/api/tasks", False, "Tasks API - should be public"),
        ("/admin", True, "Admin dashboard - should require auth"),
        ("/admin/tasks", True, "Admin tasks page - should require auth"),
        ("/admin/klines", True, "Admin klines page - should require auth"),
        ("/admin/logs", True, "Admin logs page - should require auth"),
        ("/api/admin", True, "Admin API - should require auth"),
        ("/api/admin/users", True, "Admin users - should require auth"),
        ("/api/admin/system", True, "Admin system - should require auth"),
    ]
    
    print("\n1. Testing Public Endpoints (should work without authentication):")
    print("-" * 60)
    
    for endpoint, should_require_auth, description in test_cases:
        if not should_require_auth:
            try:
                response = requests.get(f"{base_url}{endpoint}")
                status = "✓ PASS" if response.status_code == 200 else "✗ FAIL"
                print(f"{status} {endpoint:<20} - {description}")
                if response.status_code == 200:
                    data = response.json()
                    print(f"    Response: {data}")
            except requests.exceptions.RequestException as e:
                print(f"✗ FAIL {endpoint:<20} - Error: {e}")
    
    print("\n2. Testing Protected Endpoints (should require authentication):")
    print("-" * 60)
    
    for endpoint, should_require_auth, description in test_cases:
        if should_require_auth:
            # Test without auth (should fail)
            try:
                response = requests.get(f"{base_url}{endpoint}")
                if response.status_code == 401:
                    print(f"✓ PASS {endpoint:<20} - {description} (correctly protected)")
                else:
                    print(f"✗ FAIL {endpoint:<20} - Should be protected but returned {response.status_code}")
            except requests.exceptions.RequestException as e:
                print(f"✗ FAIL {endpoint:<20} - Error: {e}")
            
            # Test with auth (should work)
            try:
                response = requests.get(f"{base_url}{endpoint}", auth=auth)
                if response.status_code == 200:
                    print(f"✓ PASS {endpoint:<20} - Works with authentication")
                    data = response.json()
                    print(f"    Response: {data}")
                else:
                    print(f"✗ FAIL {endpoint:<20} - Auth failed: {response.status_code}")
            except requests.exceptions.RequestException as e:
                print(f"✗ FAIL {endpoint:<20} - Auth error: {e}")

def demonstrate_use_cases():
    """Demonstrate different use cases for protected paths"""
    print("\n3. Common Use Cases:")
    print("-" * 60)
    
    use_cases = [
        {
            "name": "Public API + Admin Panel",
            "config": "--protected-paths '/admin'",
            "description": "Keep all /api endpoints public, protect admin panel"
        },
        {
            "name": "Fully Protected API",
            "config": "--protected-paths '/api'",
            "description": "Require authentication for all API calls"
        },
        {
            "name": "Selective Protection",
            "config": "--protected-paths '/admin,/secure,/internal'",
            "description": "Protect specific sensitive endpoints"
        },
        {
            "name": "No Protection",
            "config": "# Don't set --protected-paths",
            "description": "All endpoints are public (default behavior)"
        }
    ]
    
    for i, case in enumerate(use_cases, 1):
        print(f"{i}. {case['name']}")
        print(f"   Config: {case['config']}")
        print(f"   Description: {case['description']}")
        print()

def main():
    print("ChainerTrader Protected Paths Authentication Example")
    print("=" * 70)
    
    # Start server
    process = start_server_with_protected_paths()
    
    try:
        # Test authentication strategy
        test_authentication_strategy()
        
        # Show use cases
        demonstrate_use_cases()
        
        print("\n✓ Protected paths authentication test completed")
        print("\nYou can test manually:")
        print("  # Public endpoints (no auth required)")
        print("  curl http://localhost:8000/api/health")
        print("  curl http://localhost:8000/api/info")
        print()
        print("  # Protected endpoints (auth required)")
        print("  curl http://localhost:8000/admin  # Should return 401")
        print("  curl http://localhost:8000/admin/tasks  # Should return 401")
        print("  curl -u admin:secure_password http://localhost:8000/admin  # Should work")
        print("  curl -u admin:secure_password http://localhost:8000/admin/tasks  # Should work")
        print("  curl -u admin:secure_password http://localhost:8000/api/admin  # Should work")
        
        # Keep server running
        print("\nPress Ctrl+C to stop the server...")
        process.wait()
        
    except KeyboardInterrupt:
        print("\nStopping server...")
        process.terminate()
        process.wait()

if __name__ == "__main__":
    main()
