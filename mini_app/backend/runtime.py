"""Coordinates Telegram polling with the ASGI server lifecycle."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Protocol

from config import Settings
from bot.scheduler_bot import AsyncSchedulerBot


logger = logging.getLogger(__name__)


class BotApplication(Protocol):
    async def run(self) -> None: ...


class BotRuntime:
    def __init__(self, settings: Settings) -> None:
        self._bot: BotApplication = AsyncSchedulerBot(settings.bot_token, settings=settings)
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._bot.run(), name="telegram-polling")
            self._task.add_done_callback(self._finished)

    @staticmethod
    def _finished(task):
        if not task.cancelled() and task.exception() is not None:
            logger.error("Фоновый процесс Telegram остановился из-за ошибки")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None
