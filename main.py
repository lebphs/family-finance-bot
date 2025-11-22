import asyncio
import logging
import os
from dotenv import load_dotenv
from scheduler_bot import AsyncSchedulerBot

logging.basicConfig(level=logging.DEBUG)

load_dotenv()

if __name__ == "__main__":

    BOT_TOKEN = os.getenv("BOT_TOKEN")
    bot = AsyncSchedulerBot(BOT_TOKEN)
    asyncio.run(bot.run())
