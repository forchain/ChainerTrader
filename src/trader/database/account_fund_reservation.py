from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from logging import Logger

from tortoise.transactions import in_transaction

from trader.database.models import AccountFundReservationModel

ACTIVE = "active"
RELEASED = "released"


class FundReservationError(RuntimeError):
    pass


@dataclass(frozen=True)
class FundReservation:
    account_key: str
    exchange: str
    credential_id: int | None
    user_id: int | None
    task_id: int
    asset: str
    reserved_amount: float
    spent_amount: float
    status: str

    @property
    def remaining_amount(self) -> float:
        return max(float(self.reserved_amount) - float(self.spent_amount), 0.0)


@dataclass(frozen=True)
class FundReservationResult:
    reservation: FundReservation
    created: bool


def _row_to_reservation(row: AccountFundReservationModel) -> FundReservation:
    return FundReservation(
        account_key=row.account_key,
        exchange=row.exchange,
        credential_id=row.credential_id,
        user_id=row.user_id,
        task_id=row.task_id,
        asset=row.asset,
        reserved_amount=float(row.reserved_amount or 0.0),
        spent_amount=float(row.spent_amount or 0.0),
        status=row.status,
    )


class AccountFundReservationCol:
    def __init__(self, log: Logger):
        self.log = log

    async def reserve(
        self,
        *,
        account_key: str,
        exchange: str,
        credential_id: int | None,
        user_id: int | None,
        task_id: int,
        asset: str,
        amount: float,
        capacity: float,
        reason: str,
        balance: float | None = None,
        max_borrowable: float | None = None,
        borrow_limit: float | None = None,
        operable_capacity: float | None = None,
    ) -> FundReservationResult:
        account_key = str(account_key or "").strip()
        asset = str(asset or "").strip().upper()
        amount = float(amount or 0.0)
        capacity = float(capacity or 0.0)
        if not account_key:
            raise FundReservationError("account_key is required")
        if not asset:
            raise FundReservationError("asset is required")
        if amount <= 0:
            raise FundReservationError("reservation amount must be positive")

        async with in_transaction() as connection:
            existing = (
                await AccountFundReservationModel.filter(task_id=task_id, asset=asset, status=ACTIVE)
                .using_db(connection)
                .first()
            )
            if existing is not None:
                return FundReservationResult(_row_to_reservation(existing), created=False)

            rows = await AccountFundReservationModel.filter(
                account_key=account_key,
                asset=asset,
                status=ACTIVE,
            ).using_db(connection)
            reserved = sum(float(row.reserved_amount or 0.0) for row in rows)
            if reserved + amount > capacity + 1e-12:
                raise FundReservationError(
                    "insufficient reserved capacity: "
                    f"account_key={account_key} asset={asset} capacity={capacity} "
                    f"balance={balance} max_borrowable={max_borrowable} "
                    f"borrow_limit={borrow_limit} operable_capacity={operable_capacity} "
                    f"active_reserved={reserved} requested={amount}"
                )

            row = await AccountFundReservationModel.create(
                account_key=account_key,
                exchange=exchange,
                credential_id=credential_id,
                user_id=user_id,
                task_id=task_id,
                asset=asset,
                reserved_amount=amount,
                spent_amount=0.0,
                status=ACTIVE,
                reason=reason,
                using_db=connection,
            )
            return FundReservationResult(_row_to_reservation(row), created=True)

    async def active_reserved_amount(self, account_key: str, asset: str) -> float:
        rows = await AccountFundReservationModel.filter(
            account_key=str(account_key or "").strip(),
            asset=str(asset or "").strip().upper(),
            status=ACTIVE,
        )
        return sum(float(row.reserved_amount or 0.0) for row in rows)

    async def remaining_for_task(self, task_id: int, asset: str) -> float | None:
        row = await AccountFundReservationModel.filter(
            task_id=task_id,
            asset=str(asset or "").strip().upper(),
            status=ACTIVE,
        ).first()
        if row is None:
            return None
        return max(float(row.reserved_amount or 0.0) - float(row.spent_amount or 0.0), 0.0)

    async def mark_spent(self, task_id: int, asset: str, amount: float) -> FundReservation | None:
        asset = str(asset or "").strip().upper()
        amount = float(amount or 0.0)
        if amount <= 0:
            return await self.get_active_for_task(task_id, asset)
        async with in_transaction() as connection:
            row = (
                await AccountFundReservationModel.filter(task_id=task_id, asset=asset, status=ACTIVE)
                .using_db(connection)
                .first()
            )
            if row is None:
                return None
            row.spent_amount = min(float(row.reserved_amount or 0.0), float(row.spent_amount or 0.0) + amount)
            await row.save(using_db=connection)
            return _row_to_reservation(row)

    async def release_task(self, task_id: int, *, reason: str) -> int:
        now = datetime.now(timezone.utc)
        return await AccountFundReservationModel.filter(task_id=task_id, status=ACTIVE).update(
            status=RELEASED,
            reason=reason,
            released_at=now,
        )

    async def get_active_for_task(self, task_id: int, asset: str) -> FundReservation | None:
        row = await AccountFundReservationModel.filter(
            task_id=task_id,
            asset=str(asset or "").strip().upper(),
            status=ACTIVE,
        ).first()
        if row is None:
            return None
        return _row_to_reservation(row)

    async def release_inactive_tasks(self, running_task_ids: set[int], *, reason: str) -> int:
        rows = await AccountFundReservationModel.filter(status=ACTIVE)
        total = 0
        for row in rows:
            if int(row.task_id) in running_task_ids:
                continue
            total += await self.release_task(int(row.task_id), reason=reason)
        return total
