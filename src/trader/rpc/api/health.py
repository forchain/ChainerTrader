from fastapi import APIRouter

router = APIRouter()


@router.get("")
def health_check():
    """Health check endpoint - always public"""
    return {
        "status": "healthy",
        "service": "ChainerTrader",
        "message": "Service is running"
    }


@router.get("/ready")
def readiness_check():
    """Readiness check endpoint - always public"""
    return {
        "status": "ready",
        "service": "ChainerTrader",
        "message": "Service is ready to accept requests"
    }
