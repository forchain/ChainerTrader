from fastapi import APIRouter, HTTPException, Request, status

from trader.auth.context import require_admin

router = APIRouter()


@router.get("")
async def admin_info(request: Request):
    """Administrator information endpoint."""
    await require_admin(request)
    return {
        "message": "Admin panel",
        "status": "authenticated",
        "features": ["User management", "System configuration", "Advanced monitoring"],
    }


@router.get("/users")
async def admin_users(request: Request):
    """List platform users for administrators."""
    await require_admin(request)
    rpc_app = getattr(request.app.state, "app", None)
    db_manager = getattr(rpc_app, "db_manager", None)
    user_repo = getattr(db_manager, "user", None)
    if user_repo is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="user database is not initialized")
    users = await user_repo.list_users()
    rows = [
        {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "status": user.status,
        }
        for user in users
    ]
    return {"users": rows, "total": len(rows)}


@router.get("/system")
async def admin_system(request: Request):
    """Return minimal system status for administrators."""
    await require_admin(request)
    return {"system": {"status": "running"}}
