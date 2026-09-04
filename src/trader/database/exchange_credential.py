from __future__ import annotations

from logging import Logger

from trader.database.models import ExchangeCredentialModel


class ExchangeCredentialCol:
    def __init__(self, log: Logger):
        self.log = log

    async def upsert_default(
        self,
        user_id: int,
        *,
        exchange: str,
        encrypted_api_key: str,
        encrypted_api_secret: str,
        masked_api_key: str,
    ) -> ExchangeCredentialModel:
        row, _created = await ExchangeCredentialModel.update_or_create(
            user_id=user_id,
            exchange=exchange,
            label="default",
            defaults={
                "encrypted_api_key": encrypted_api_key,
                "encrypted_api_secret": encrypted_api_secret,
                "masked_api_key": masked_api_key,
            },
        )
        return row

    async def get_default(self, user_id: int, exchange: str) -> ExchangeCredentialModel | None:
        return await ExchangeCredentialModel.filter(user_id=user_id, exchange=exchange, label="default").first()

    async def list_by_user(self, user_id: int) -> list[ExchangeCredentialModel]:
        return await ExchangeCredentialModel.filter(user_id=user_id).order_by("exchange", "label")

    async def delete_for_user(self, credential_id: int, user_id: int) -> bool:
        deleted = await ExchangeCredentialModel.filter(id=credential_id, user_id=user_id).delete()
        return deleted > 0
