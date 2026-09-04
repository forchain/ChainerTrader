import base64

from fastapi import HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from trader.common.config import Config


class BasicAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, config: Config):
        super().__init__(app)
        self.config = config
        self.security = HTTPBasic()

    async def dispatch(self, request: Request, call_next):
        # Skip authentication if not enabled
        if not self.config.is_auth_enabled():
            response = await call_next(request)
            return response

        # Skip authentication for non-protected paths
        if not self.config.is_protected_path(request.url.path):
            response = await call_next(request)
            return response

        # Check if the request has valid basic auth credentials
        try:
            credentials = await self._get_credentials(request)
            if not self._verify_credentials(credentials):
                return self._create_auth_response()
        except HTTPException:
            return self._create_auth_response()

        response = await call_next(request)
        return response

    async def _get_credentials(self, request: Request) -> HTTPBasicCredentials:
        """Extract credentials from Authorization header"""
        authorization = request.headers.get("Authorization")
        if not authorization or not authorization.startswith("Basic "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Basic"},
            )

        try:
            credentials = base64.b64decode(authorization[6:]).decode("utf-8")
            username, password = credentials.split(":", 1)
            return HTTPBasicCredentials(username=username, password=password)
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Basic"},
            )

    def _verify_credentials(self, credentials: HTTPBasicCredentials) -> bool:
        """Verify the provided credentials against configured values"""
        return (
            credentials.username == self.config.auth_username
            and credentials.password == self.config.auth_password
        )

    def _create_auth_response(self) -> Response:
        """Create a 401 response with Basic auth challenge"""
        return Response(
            content="Authentication required",
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Basic realm=ChainerTrader"},
        )
