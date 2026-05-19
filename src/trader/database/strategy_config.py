from __future__ import annotations

from logging import Logger
from typing import Any

from trader.database.models import StrategyConfigModel


class StrategyConfigCol:
    def __init__(self, log: Logger):
        self.log = log

    async def create(
        self,
        user_id: int,
        *,
        name: str,
        strategy_name: str,
        symbol: str,
        interval: str,
        params: dict[str, Any] | None = None,
    ) -> StrategyConfigModel:
        return await StrategyConfigModel.create(
            user_id=user_id,
            name=name,
            strategy_name=strategy_name,
            symbol=symbol,
            interval=interval,
            params=params or {},
        )

    async def list_by_user(self, user_id: int) -> list[StrategyConfigModel]:
        return await StrategyConfigModel.filter(user_id=user_id).order_by("id")

    async def get_for_user(self, config_id: int, user_id: int) -> StrategyConfigModel | None:
        return await StrategyConfigModel.filter(id=config_id, user_id=user_id).first()
