"""HTTP request and response schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import re
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

from backend.models import CurrentUser, Transaction, User, UserRole


class ExpenseFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    date: date
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2, allow_inf_nan=False)
    category: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)

    @field_validator("date", mode="before")
    @classmethod
    def validate_date(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Use YYYY-MM-DD")
        return value

    @field_validator("amount", mode="before")
    @classmethod
    def validate_amount(cls, value):
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError("Invalid amount")
        if not re.fullmatch(r"\d+(?:\.\d{1,2})?", str(value)):
            raise ValueError("Invalid amount")
        return value


class CreateExpenseRequest(ExpenseFields):
    request_id: UUID


class TransactionResponse(BaseModel):
    version: str
    date: date
    description: str
    category: str
    amount: Decimal
    author_id: int | None
    author_name: str
    transaction_id: str | None
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def from_domain(cls, transaction: Transaction):
        from backend.transaction_version import transaction_version
        return cls(version=transaction_version(transaction), **{name: getattr(transaction, name) for name in cls.model_fields if name != "version"})


class CategoryTotal(BaseModel):
    category: str
    amount: Decimal


class HomeResponse(BaseModel):
    month: str
    total: Decimal
    previous_total: Decimal
    change: Decimal
    change_percent: Decimal | None
    categories: list[CategoryTotal]
    recent: list[TransactionResponse]


class CurrentUserResponse(BaseModel):
    telegram_user_id: int
    display_name: str
    role: UserRole

    @classmethod
    def from_domain(cls, user: CurrentUser) -> "CurrentUserResponse":
        return cls(
            telegram_user_id=user.telegram_user_id,
            display_name=user.display_name,
            role=user.role,
        )


class UserResponse(BaseModel):
    telegram_user_id: int
    display_name: str
    role: UserRole
    active: bool
    reminder_enabled: bool
    reminder_time: str
    reminder_days: str
    timezone: str
    chat_id: int | None

    @classmethod
    def from_domain(cls, user: User) -> "UserResponse":
        return cls(
            telegram_user_id=user.telegram_user_id,
            display_name=user.display_name,
            role=user.role,
            active=user.active,
            reminder_enabled=user.reminder_enabled,
            reminder_time=user.reminder_time,
            reminder_days=user.reminder_days,
            timezone=user.timezone,
            chat_id=user.chat_id,
        )


class CreateUserRequest(BaseModel):
    telegram_user_id: int = Field(gt=0)
    display_name: str = Field(min_length=1, max_length=100)
    role: UserRole = UserRole.MEMBER
    active: bool = True


class UpdateUserRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    role: UserRole | None = None
    active: bool | None = None

    def changes(self) -> dict[str, object]:
        return {
            name: value
            for name, value in (
                ("display_name", self.display_name),
                ("role", self.role),
                ("active", self.active),
            )
            if value is not None
        }


class UpdateTransactionRequest(ExpenseFields):
    version: str = Field(pattern=r"^[a-f0-9]{64}$")


class TransactionFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    date_from: date | None = None
    date_to: date | None = None
    category: str | None = Field(default=None, min_length=1, max_length=100)
    author_id: int | None = Field(default=None, gt=0)
    unknown_author: bool = False
    search: str = Field(default="", max_length=500)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)

    @field_validator("date_from", "date_to", mode="before")
    @classmethod
    def strict_date(cls, value):
        return None if value is None else CreateExpenseRequest.validate_date(value)

    @model_validator(mode="after")
    def valid_range(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("Invalid period")
        if self.author_id and self.unknown_author:
            raise ValueError("Conflicting authors")
        return self


class TransactionPage(BaseModel):
    items: list[TransactionResponse]
    total: int
    next_offset: int | None


class TransactionParticipant(BaseModel):
    author_id: int | None
    author_name: str
