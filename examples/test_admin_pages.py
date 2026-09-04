#!/usr/bin/env python3
"""
Test script to verify all admin pages are accessible with authentication
"""
import os
import subprocess
import sys
import time
import requests
from requests.auth import HTTPBasicAuth

def start_server_with_admin_protection():
    """Start server with admin pages protected"""
    print("Starting ChainerTrader with admin pages protection...")
    
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

def test_admin_pages():
    """Test all admin pages with and without authentication"""
    base_url = "http://127.0.0.1:8000"
    auth = HTTPBasicAuth("admin", "password123")
    
    print("Testing Admin Pages")
    print("=" * 50)
    
    # Test pages
    pages = [
        ("/", "Root redirect"),
        ("/admin", "Admin dashboard"),
        ("/admin/tasks", "Admin tasks page"),
        ("/admin/klines", "Admin klines page"),
        ("/admin/logs", "Admin logs page"),
    ]
    
    print("\n1. Testing without authentication (should redirect or require auth):")
    print("-" * 60)
    
    for path, description in pages:
        try:
            response = requests.get(f"{base_url}{path}")
            if path == "/":
                if response.status_code in [200, 302]:  # Redirect is OK
                    print(f"✓ {path:<15} - {description} (redirected)")
                else:
                    print(f"✗ {path:<15} - {description} (unexpected: {response.status_code})")
            else:
                if response.status_code == 401:
                    print(f"✓ {path:<15} - {description} (correctly protected)")
                else:
                    print(f"✗ {path:<15} - {description} (should be protected: {response.status_code})")
        except requests.exceptions.RequestException as e:
            print(f"✗ {path:<15} - {description} (error: {e})")
    
    print("\n2. Testing with authentication (should work):")
    print("-" * 60)
    
    for path, description in pages:
        try:
            response = requests.get(f"{base_url}{path}", auth=auth)
            if response.status_code == 200:
                print(f"✓ {path:<15} - {description} (accessible)")
            else:
                print(f"✗ {path:<15} - {description} (failed: {response.status_code})")
        except requests.exceptions.RequestException as e:
            print(f"✗ {path:<15} - {description} (error: {e})")
    
    print("\n3. Testing navigation links:")
    print("-" * 60)
    
    # Test that the admin dashboard loads and contains proper navigation
    try:
        response = requests.get(f"{base_url}/admin", auth=auth)
        if response.status_code == 200:
            content = response.text
            # Check for navigation links
            nav_checks = [
                ('href="/admin"', "Home link"),
                ('href="/admin/tasks"', "Tasks link"),
                ('href="/admin/klines"', "Klines link"),
                ('href="/admin/logs"', "Logs link"),
            ]
            
            for link, description in nav_checks:
                if link in content:
                    print(f"✓ {description} found in navigation")
                else:
                    print(f"✗ {description} missing from navigation")
        else:
            print(f"✗ Could not load admin dashboard: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"✗ Error testing navigation: {e}")

def main():
    print("ChainerTrader Admin Pages Test")
    print("=" * 50)
    
    # Start server
    process = start_server_with_admin_protection()
    
    try:
        # Test admin pages
        test_admin_pages()
        
        print("\n✓ Admin pages test completed")
        print("\nYou can test manually:")
        print("  # Without auth (should be protected)")
        print("  curl http://localhost:8000/admin")
        print("  curl http://localhost:8000/admin/tasks")
        print()
        print("  # With auth (should work)")
        print("  curl -u admin:password123 http://localhost:8000/admin")
        print("  curl -u admin:password123 http://localhost:8000/admin/tasks")
        print()
        print("  # Root redirect")
        print("  curl -L http://localhost:8000/  # Should redirect to /admin")
        
        # Keep server running
        print("\nPress Ctrl+C to stop the server...")
        process.wait()
        
    except KeyboardInterrupt:
        print("\nStopping server...")
        process.terminate()
        process.wait()

if __name__ == "__main__":
    main()


