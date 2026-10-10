"""The ASGI server owns signal handling; no real Telegram requests."""
import asyncio
import unittest
from unittest.mock import AsyncMock

from bot.scheduler_bot import AsyncSchedulerBot


class BotLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_polling_preserves_uvicorn_signal_handlers_and_cleans_scheduler(self):
        scheduler = AsyncSchedulerBot.__new__(AsyncSchedulerBot)
        scheduler.bot = AsyncMock()
        scheduler.dp = AsyncMock()
        entered = asyncio.Event()
        stopped = asyncio.Event()

        async def loop():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        async def polling(*_args, **_kwargs):
            await entered.wait()

        scheduler.scheduler_loop = loop
        scheduler.dp.start_polling.side_effect = polling
        await scheduler.run()
        scheduler.dp.start_polling.assert_awaited_once_with(scheduler.bot, handle_signals=False)
        self.assertTrue(stopped.is_set())
        scheduler.bot.session.close.assert_awaited_once()
