"""Data-access boundary for users stored in Google Sheets."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from mini_app.backend.models import Category, CurrentUser, Transaction, User, UserRole
from mini_app.backend.sheets import AsyncSheetsRepository, GoogleSheetsCategoryRepository, GoogleSheetsTransactionRepository
from mini_app.backend.errors import RepositorySchemaError, UserAlreadyExistsError
from datetime import date
from decimal import Decimal


USERS_HEADERS = (
    "telegram_user_id",
    "display_name",
    "role",
    "active",
    "reminder_enabled",
    "reminder_time",
    "reminder_days",
    "timezone",
    "chat_id",
)


class UserRepository(Protocol):
    async def get(self, telegram_user_id: int) -> User | None: ...

    async def list(self) -> list[User]: ...

    async def create(self, user: User) -> User: ...

    async def update(self, telegram_user_id: int, changes: dict[str, object]) -> User | None: ...


class CategoryRepository(Protocol):
    async def list(self) -> list[Category]: ...


class TransactionRepository(Protocol):
    async def list(self) -> list[Transaction]: ...
    async def get(self, transaction_id: str) -> Transaction | None: ...
    async def create(self, *, date: date, description: str, category: str,
                     amount: Decimal, author: CurrentUser, transaction_id: str | None = None) -> Transaction: ...
    async def update(self, transaction_id: str, changes: dict[str, object], *, expected_version: str | None = None) -> Transaction | None: ...
    async def delete(self, transaction_id: str, *, expected_version: str | None = None) -> bool: ...
    async def rotate(self, today: date) -> bool: ...


class GoogleSheetsUserRepository(AsyncSheetsRepository):
    """Runs every blocking gspread operation outside the event loop."""

    async def get(self, telegram_user_id: int) -> User | None:
        return await self._run(self._get_sync, telegram_user_id, read_only=True)

    async def list(self) -> list[User]:
        return await self._run(self._list_sync, read_only=True)

    async def create(self, user: User) -> User:
        return await self._run(self._create_sync, user)

    async def update(self, telegram_user_id: int, changes: dict[str, object]) -> User | None:
        return await self._run(self._update_sync, telegram_user_id, changes)

    def _worksheet(self):
        worksheet = self.gateway.worksheet("Users")
        if tuple(worksheet.row_values(1)) != USERS_HEADERS:
            raise RepositorySchemaError()
        return worksheet

    def _get_sync(self, telegram_user_id: int) -> User | None:
        return next(
            (user for user in self._list_sync() if user.telegram_user_id == telegram_user_id),
            None,
        )

    def _list_sync(self) -> list[User]:
        # Preserve comma-separated weekdays and identifiers as stored: gspread
        # otherwise numericises "0,1,2,3,4,5,6" into 123456.
        records = self._worksheet().get_all_records(numericise_ignore=["all"])
        users = [_user_from_record(record) for record in records]
        if len({user.telegram_user_id for user in users}) != len(users):
            raise RepositorySchemaError()
        return users

    def _create_sync(self, user: User) -> User:
        worksheet = self._worksheet()
        records = worksheet.get_all_records(numericise_ignore=["all"])
        if any(_parse_int(record.get("telegram_user_id")) == user.telegram_user_id for record in records):
            raise UserAlreadyExistsError
        worksheet.append_row(_user_to_row(user), value_input_option="RAW")
        return user

    def _update_sync(self, telegram_user_id: int, changes: dict[str, object]) -> User | None:
        worksheet = self._worksheet()
        records = worksheet.get_all_records(numericise_ignore=["all"])
        for index, record in enumerate(records, start=2):
            if _parse_int(record.get("telegram_user_id")) != telegram_user_id:
                continue
            updated = replace(_user_from_record(record), **changes)
            worksheet.update(
                f"A{index}:I{index}",
                [_user_to_row(updated)],
                value_input_option="RAW",
            )
            return updated
        return None


def _user_from_record(record: dict[str, object]) -> User:
    return User(
        telegram_user_id=_parse_int(record.get("telegram_user_id")),
        display_name=str(record.get("display_name") or "").strip(),
        role=UserRole(str(record.get("role") or "").strip().lower()),
        active=_parse_bool(record.get("active")),
        reminder_enabled=_parse_bool(record.get("reminder_enabled")),
        reminder_time=str(record.get("reminder_time") or "22:00"),
        reminder_days=str(record.get("reminder_days") or "0,1,2,3,4,5,6"),
        timezone=str(record.get("timezone") or "Europe/Minsk"),
        chat_id=_parse_optional_int(record.get("chat_id")),
    )


def _user_to_row(user: User) -> list[object]:
    return [
        user.telegram_user_id,
        user.display_name,
        user.role.value,
        user.active,
        user.reminder_enabled,
        user.reminder_time,
        user.reminder_days,
        user.timezone,
        user.chat_id or "",
    ]


def _parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "да"}


def _parse_int(value: object) -> int:
    return int(str(value).strip())


def _parse_optional_int(value: object) -> int | None:
    return None if value in {None, ""} else _parse_int(value)
