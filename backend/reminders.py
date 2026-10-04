"""Personal schedules and durable, at-most-once delivery claims."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator

from backend.errors import ApiError
from backend.models import CurrentUser, User
from backend.repositories import UserRepository

logger = logging.getLogger(__name__)


class ReminderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reminder_enabled: StrictBool = False
    reminder_time: str = Field(default="22:00", pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    reminder_days: list[StrictInt] = Field(default_factory=lambda: list(range(7)), min_length=1, max_length=7)
    timezone: str = Field(default="Europe/Minsk", max_length=100)

    @field_validator("reminder_days")
    @classmethod
    def days(cls, value):
        if any(day < 0 or day > 6 for day in value) or len(set(value)) != len(value):
            raise ValueError("Invalid weekdays")
        return sorted(value)

    @field_validator("timezone")
    @classmethod
    def zone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Invalid timezone") from None
        return value

    @classmethod
    def from_user(cls, user: User):
        return cls(reminder_enabled=user.reminder_enabled, reminder_time=user.reminder_time,
                   reminder_days=[int(day) for day in user.reminder_days.split(",")], timezone=user.timezone)

    def changes(self):
        return {**self.model_dump(), "reminder_days": ",".join(map(str, self.reminder_days))}


class ReminderResponse(ReminderSettings):
    chat_connected: bool


class ReminderService:
    def __init__(self, users: UserRepository):
        self.users = users

    async def get(self, identity: CurrentUser):
        user = await self.users.get(identity.telegram_user_id)
        if not user or not user.active:
            raise ApiError(code="access_denied", message="Нет доступа", status_code=403)
        return ReminderResponse(**ReminderSettings.from_user(user).model_dump(), chat_connected=user.chat_id is not None)

    async def update(self, identity: CurrentUser, settings: ReminderSettings):
        await self.get(identity)
        await self.users.update(identity.telegram_user_id, settings.changes())
        return await self.get(identity)


class DeliveryLedger:
    """Persist a claim BEFORE sending; never resend an ambiguous Telegram timeout.

    Telegram has no idempotency key. Crash/timeout after claiming can lose that
    day's reminder; retrying it could duplicate a successfully delivered message.
    Settings remain intact, and the next scheduled day is attempted normally.
    """
    def __init__(self, path: str):
        self.path = Path(path)

    def claim(self, user_id: int, local_date: str) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS deliveries (user_id INTEGER, local_date TEXT, PRIMARY KEY(user_id, local_date))")
            result = db.execute("INSERT OR IGNORE INTO deliveries VALUES (?, ?)", (user_id, local_date))
            return result.rowcount == 1


class ReminderDispatcher:
    def __init__(self, users: UserRepository, ledger: DeliveryLedger, bot):
        self.users, self.ledger, self.bot = users, ledger, bot

    async def tick(self, now: datetime | None = None):
        now = now or datetime.now(timezone.utc)
        for user in await self.users.list():
            if not user.active or not user.reminder_enabled or user.chat_id is None:
                continue
            try:
                settings = ReminderSettings.from_user(user)
                local = now.astimezone(ZoneInfo(settings.timezone))
                # Catch up after restart within the scheduled local day only.
                if local.weekday() not in settings.reminder_days or local.strftime("%H:%M") < settings.reminder_time:
                    continue
                if not await asyncio.to_thread(self.ledger.claim, user.telegram_user_id, local.date().isoformat()):
                    continue
                await self.bot.send_message(chat_id=user.chat_id, text="⏰ Напоминаю! Заполни свои расходы за сегодня")
            except Exception:
                # No raw exception, IDs, settings or Telegram URLs in logs.
                logger.error("Не удалось обработать персональное напоминание; настройки сохранены")
