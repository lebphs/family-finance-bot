"""Application models whose values are trusted only after server-side checks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from datetime import date, datetime
from decimal import Decimal


class UserRole(str, Enum):
    ADMIN = "admin"
    MEMBER = "member"


@dataclass(frozen=True, slots=True)
class User:
    telegram_user_id: int
    display_name: str
    role: UserRole
    active: bool
    reminder_enabled: bool = False
    reminder_time: str = "22:00"
    reminder_days: str = "0,1,2,3,4,5,6"
    timezone: str = "Europe/Minsk"
    chat_id: int | None = None


@dataclass(frozen=True, slots=True)
class VerifiedTelegramIdentity:
    telegram_user_id: int


@dataclass(frozen=True, slots=True)
class CurrentUser:
    telegram_user_id: int
    display_name: str
    role: UserRole

    @classmethod
    def from_user(cls, user: User) -> "CurrentUser":
        return cls(
            telegram_user_id=user.telegram_user_id,
            display_name=user.display_name,
            role=user.role,
        )



@dataclass(frozen=True, slots=True)
class Category:
    name: str
    subcategories: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Transaction:
    date: "date"
    description: str
    category: str
    amount: "Decimal"
    author_id: int | None = None
    author_name: str = "Автор не указан"
    transaction_id: str | None = None
    created_at: "datetime | None" = None
    updated_at: "datetime | None" = None
