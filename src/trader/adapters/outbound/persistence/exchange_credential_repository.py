from __future__ import annotations

from trader.core.exchange.interfaces import ExchangeCredential
from trader.database.models import ExchangeCredentialModel


def _to_domain(row: ExchangeCredentialModel) -> ExchangeCredential:
    return ExchangeCredential(
        id=row.id,
        user_id=row.user_id,
        exchange=row.exchange,
        label=row.label,
        encrypted_api_key=row.encrypted_api_key,
        encrypted_api_secret=row.encrypted_api_secret,
        masked_api_key=row.masked_api_key,
    )


class TortoiseExchangeCredentialRepository:
    async def upsert_default(
        self,
        user_id: int,
        *,
        exchange: str,
        encrypted_api_key: str,
        encrypted_api_secret: str,
        masked_api_key: str,
    ) -> ExchangeCredential:
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
        return _to_domain(row)

    async def get_default(self, user_id: int, exchange: str) -> ExchangeCredential | None:
        row = await ExchangeCredentialModel.filter(user_id=user_id, exchange=exchange, label="default").first()
        return _to_domain(row) if row is not None else None

    async def list_by_user(self, user_id: int) -> list[ExchangeCredential]:
        rows = await ExchangeCredentialModel.filter(user_id=user_id).order_by("exchange", "label")
        return [_to_domain(row) for row in rows]

    async def delete_for_user(self, credential_id: int, user_id: int) -> bool:
        deleted = await ExchangeCredentialModel.filter(id=credential_id, user_id=user_id).delete()
        return deleted > 0
