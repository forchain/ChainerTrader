# ChainerTrader 
Implement TradvingView Algorithms of Youtube Channel Shi Hun

## Development
```bash
git clone https://github.com/ChainerLabs/Trader.git
cd trader 
make install
```
Read the [CONTRIBUTING.md](CONTRIBUTING.md) file.

## Install it from PyPI

```bash
pip install trader
```

## Usage

```bash
$ python -m trader -h
#or
$ trader -h
```

## Web API

ChainerTrader provides a web interface for monitoring and controlling trading operations.

### Starting the Web Server

```bash
# Start with default settings
python -m trader --api

# Start with custom host and port
python -m trader --api 0.0.0.0:8080

# Start with authentication
python -m trader --api --auth-username admin --auth-password your_secure_password
```

### Authentication

The web interface supports HTTP Basic Authentication with flexible path-based protection. By default, all endpoints are public. You can protect specific path prefixes by configuring them.

**Environment Variables:**
```bash
export TRADER_AUTH_USERNAME="admin"
export TRADER_AUTH_PASSWORD="your_secure_password"
export TRADER_PROTECTED_PATHS="/admin,/api/admin"  # Paths that require authentication
```

**Command Line:**
```bash
# With authentication for specific paths
python -m trader --api --auth-username admin --auth-password your_secure_password --protected-paths "/admin,/api/admin"

# Protect all admin-related paths
python -m trader --api --auth-username admin --auth-password your_secure_password --protected-paths "/admin"
```

**Configuration File (.env):**
```env
TRADER_AUTH_USERNAME=admin
TRADER_AUTH_PASSWORD=your_secure_password
TRADER_PROTECTED_PATHS=/admin,/api/admin
```

### Path-based Protection

The authentication system uses path prefixes to determine which endpoints require authentication:

- **Default Behavior**: All endpoints are public (no authentication required)
- **Protected Paths**: Only specified path prefixes require authentication
- **Path Matching**: Uses prefix matching (e.g., `/admin` matches `/admin/users`, `/admin/settings`)

**Examples:**
```bash
# Protect admin panel
--protected-paths "/admin"

# Protect multiple path prefixes
--protected-paths "/admin,/api/admin,/secure"

# Protect all API endpoints
--protected-paths "/api"

# No protection (all public)
# Don't set --protected-paths or set it to empty
```

**Common Use Cases:**
- **Public API + Admin Panel**: Protect `/admin` paths, keep `/api` public
- **Fully Protected**: Protect `/api` to require auth for all API calls
- **Selective Protection**: Protect specific sensitive endpoints like `/admin`, `/secure`, `/internal`

### API Endpoints

**Web Interface:**
- `/` - Redirects to admin dashboard
- `/admin` - Main dashboard (requires authentication if configured)
- `/admin/tasks` - Task management interface (requires authentication if configured)
- `/admin/klines` - Kline data visualization (requires authentication if configured)
- `/admin/logs` - System logs (requires authentication if configured)

**Public API Endpoints (no authentication required by default):**
- `/api/config` - Configuration (masked for security)
- `/api/info` - System information
- `/api/tasks` - Task management API
- `/api/health` - Health check
- `/api/health/ready` - Readiness check

**Protected API Endpoints (require authentication if configured):**
- `/admin` - Admin panel (if protected)
- `/api/admin` - Admin API (if protected)
- `/api/admin/users` - User management (if protected)
- `/api/admin/system` - System information (if protected)
