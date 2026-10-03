import asyncio
import unittest

from backend.runtime import BotRuntime
from config import Settings


class _FakeBot:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()

    async def run(self) -> None:
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.stopped.set()


class BotRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_bot_runs_as_background_task_and_stops_cleanly(self):
        runtime = BotRuntime.__new__(BotRuntime)
        bot = _FakeBot()
        runtime._bot = bot
        runtime._task = None

        await runtime.start()
        await asyncio.wait_for(bot.started.wait(), timeout=1)
        self.assertIsNotNone(runtime._task)

        await runtime.stop()
        self.assertTrue(bot.stopped.is_set())
        self.assertIsNone(runtime._task)


if __name__ == "__main__":
    unittest.main()
