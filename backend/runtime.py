"""Coordinates Telegram polling with the ASGI server lifecycle."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Protocol

from config import Settings
from scheduler_bot import AsyncSchedulerBot


class BotApplication(Protocol):
    async def run(self) -> None: ...


class BotRuntime:
    def __init__(self, settings: Settings) -> None:
        self._bot: BotApplication = AsyncSchedulerBot(settings.bot_token)
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._bot.run(), name="telegram-polling")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None
