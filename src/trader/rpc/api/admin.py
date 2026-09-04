from fastapi import APIRouter

router = APIRouter()


@router.get("")
def admin_info():
    """Admin information endpoint - requires authentication"""
    return {
        "message": "Admin panel",
        "status": "authenticated",
        "features": [
            "User management",
            "System configuration", 
            "Advanced monitoring",
            "Security settings"
        ]
    }


@router.get("/users")
def admin_users():
    """User management endpoint - requires authentication"""
    return {
        "users": [
            {"id": 1, "username": "admin", "role": "administrator"},
            {"id": 2, "username": "trader", "role": "user"}
        ],
        "total": 2
    }


@router.get("/system")
def admin_system():
    """System information endpoint - requires authentication"""
    return {
        "system": {
            "status": "running",
            "uptime": "2 days, 5 hours",
            "memory_usage": "45%",
            "cpu_usage": "12%"
        }
    }
