from __future__ import annotations

from fastapi import HTTPException, status

from trader.core.exchange.exceptions import ExchangeConnectivityError, UserExchangeCredentialError
from trader.core.identity.exceptions import AuthenticationError, PasswordPolicyError
from trader.core.optimization.exceptions import OptimizationConfigError, RankingError
from trader.core.task.exceptions import FundReservationError, TaskNotFound, TaskOwnership

DOMAIN_EXCEPTION_STATUS_MAP: dict[type[Exception], int] = {
    AuthenticationError: status.HTTP_401_UNAUTHORIZED,
    PasswordPolicyError: status.HTTP_422_UNPROCESSABLE_ENTITY,
    TaskNotFound: status.HTTP_404_NOT_FOUND,
    TaskOwnership: status.HTTP_403_FORBIDDEN,
    UserExchangeCredentialError: status.HTTP_400_BAD_REQUEST,
    ExchangeConnectivityError: status.HTTP_400_BAD_REQUEST,
    FundReservationError: status.HTTP_400_BAD_REQUEST,
    OptimizationConfigError: status.HTTP_400_BAD_REQUEST,
    RankingError: status.HTTP_400_BAD_REQUEST,
}


def translate_domain_exception(exc: Exception) -> HTTPException:
    """Translate domain exceptions into FastAPI HTTPException via a single status mapping table."""
    if isinstance(exc, HTTPException):
        return exc
    for exc_type, status_code in DOMAIN_EXCEPTION_STATUS_MAP.items():
        if isinstance(exc, exc_type):
            return HTTPException(status_code=status_code, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
