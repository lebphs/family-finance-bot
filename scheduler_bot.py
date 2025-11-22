import asyncio
from datetime import datetime, time
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
import logging

logger = logging.getLogger(__name__)


class AsyncSchedulerBot:

    def __init__(self, token):
        self.bot = Bot(token=token)
        storage = MemoryStorage()
        self.dp = Dispatcher(storage=storage)
        self.subscribed_users = set()
        self.scheduler_task = None
        self.subscribed_chats = set()
        self.notification_time = time(22, 00)

        from handlers.expenses import register_expenses
        from handlers.user import register_user
        self.dp.message.register(self.subscribe_chat, Command("subscribe"))
        register_user(self.dp)
        register_expenses(self.dp)

    async def subscribe_chat(self, message):
        time_str = message.text.split()[1]
        hour,minute = map(int, time_str.split(":"))
        self.notification_time = time(hour, minute)

        chat_id = message.chat.id
        self.subscribed_chats.add(chat_id)
        await message.answer(f"✅ Этот чат подписан на ежедневные напоминания в {time_str}!")

    async def send_daily_notification(self):
        for chat_id in self.subscribed_chats.copy():
            try:
                await self.bot.send_message(chat_id=chat_id, text="⏰ Напоминаю! Заполни свои расходы за сегодня")
                logging.debug(f"Notification was send in chat {chat_id}")
            except Exception as e:
                logging.debug(f"Error sending notification in chat {chat_id}")
                self.subscribed_chats.discard(chat_id)
    
    async def scheduler_loop(self):
        logging.info("Scheduler is started..")

        while True:
            now = datetime.now()
            await self.send_daily_notification()
            if now.hour == self.notification_time.hour and now.minute == self.notification_time.minute:
                await self.send_daily_notification()
            await asyncio.sleep(60)
    
    async def run(self):
        self.scheduler_task = asyncio.create_task(self.scheduler_loop())
        
        logging.info("Bot is started..")
        try:
            await self.dp.start_polling(self.bot)
        finally:
            if self.scheduler_task:
                self.scheduler_task.cancel()