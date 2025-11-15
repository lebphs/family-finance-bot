import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

logging.basicConfig(level=logging.DEBUG)

load_dotenv()
logging.debug("Trying connect to BOT")
BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


async def main():
    register_handlers(dp)
    await dp.start_polling(bot, skip_updates=True)


def register_handlers(dp):
    register_user(dp)
    register_expenses(dp)


if __name__ == "__main__":
    from handlers.expenses import register_expenses
    from handlers.user import register_user

    asyncio.run(main())
