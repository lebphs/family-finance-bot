import asyncio
import logging
from contextlib import suppress
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
logger = logging.getLogger(__name__)


class AsyncSchedulerBot:

    def __init__(self, token, *, settings=None, users=None, ledger=None):
        from config import load_settings
        from mini_app.backend.repositories import GoogleSheetsUserRepository
        from mini_app.backend.reminders import DeliveryLedger, ReminderDispatcher
        from pathlib import Path

        self.settings = settings or load_settings()
        self.users = users or GoogleSheetsUserRepository(self.settings)
        self.bot = Bot(token=token)
        self.dp = Dispatcher(storage=MemoryStorage())
        self.scheduler_task = None
        self._sheet_rotation_done_for = None
        self.reminders = ReminderDispatcher(self.users, ledger or DeliveryLedger(
            str(Path(self.settings.state_dir) / "reminders.sqlite3")), self.bot)

        from bot.handlers.expenses import register_expenses
        from bot.handlers.user import register_user
        self.dp.message.register(self.connect_chat, Command("start", "register"))
        self.dp.message.register(self.subscribe_chat, Command("subscribe"))
        self.dp.message.register(self.unsubscribe_chat, Command("unsubscribe"))
        register_user(self.dp)
        register_expenses(self.dp)
        self.dp.errors.register(self.handle_error)

    async def handle_error(self, event):
        logger.error("Ошибка обработки команды Telegram")
        message = event.update.message
        if message is not None:
            try:
                await message.answer("Не удалось выполнить команду. Попробуйте позже.")
            except Exception:
                logger.error("Не удалось отправить сообщение об ошибке")
        return True

    async def _authorized_private_user(self, message):
        # Never attach financial reminders to a group or a client-supplied ID.
        if message.from_user is None or message.chat.type != "private":
            await message.answer("Откройте личный чат с ботом")
            return None
        user = await self.users.get(message.from_user.id)
        if not user or not user.active:
            await message.answer("Нет доступа")
            return None
        return user

    async def connect_chat(self, message):
        user = await self._authorized_private_user(message)
        if user is None:
            return
        await self.users.update(user.telegram_user_id, {"chat_id": message.chat.id})
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
        markup = None
        if self.settings.mini_app_url:
            markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                text="Открыть семейные расходы", web_app=WebAppInfo(url=self.settings.mini_app_url))]])
        await message.answer("✅ Чат подключён. Настройте напоминания в Mini App.", reply_markup=markup)

    async def subscribe_chat(self, message):
        from mini_app.backend.reminders import ReminderSettings
        parts = (message.text or "").split()
        if len(parts) > 2:
            await message.answer("Используйте /subscribe или /subscribe HH:MM")
            return
        try:
            validated = ReminderSettings(reminder_time=parts[1] if len(parts) == 2 else "22:00")
        except ValueError:
            await message.answer("Укажите время в формате HH:MM, например /subscribe 22:00")
            return
        user = await self._authorized_private_user(message)
        if user is None:
            return
        await self.users.update(user.telegram_user_id, {
            "chat_id": message.chat.id, "reminder_enabled": True,
            "reminder_time": validated.reminder_time,
        })
        await message.answer("✅ Персональные напоминания включены")

    async def unsubscribe_chat(self, message):
        user = await self._authorized_private_user(message)
        if user is not None:
            await self.users.update(user.telegram_user_id, {"reminder_enabled": False})
            await message.answer("Напоминания отключены")

    async def send_daily_notification(self):
        await self.reminders.tick()

    async def run_monthly_transactions_sheet_rotation(self, now: datetime) -> None:
        period = (now.year, now.month)
        if self._sheet_rotation_done_for == period:
            return
        from bot.sheet import Sheet

        def _rotate() -> bool:
            return Sheet(self.settings).rotate_transactions_sheet_for_new_month(now.date())

        try:
            rotated = await asyncio.to_thread(_rotate)
            self._sheet_rotation_done_for = period
            if rotated:
                logger.info("Лист Transactions скопирован в архив прошлого месяца и очищен.")
        except Exception:
            logger.error("Ошибка ротации листа Transactions; повторим позже")
            return

    async def scheduler_loop(self):
        from mini_app.backend.backups import SheetsBackup
        from mini_app.backend.sheets import SheetsGateway
        backup = SheetsBackup(SheetsGateway(self.settings), self.settings.state_dir)
        while True:
            try:
                await self.send_daily_notification()
                now = datetime.now(ZoneInfo("Europe/Minsk"))
                if now.day == 1:
                    await self.run_monthly_transactions_sheet_rotation(now)
                if self.settings.backup_enabled:
                    await backup.run(now.date())
            except Exception:
                logger.error("Ошибка фоновой задачи; повторим на следующем цикле")
            await asyncio.sleep(30)

    async def run(self):
        self.scheduler_task = asyncio.create_task(self.scheduler_loop())
        
        logging.info("Bot is started..")
        try:
            await self.dp.start_polling(self.bot, handle_signals=False)
        finally:
            if self.scheduler_task:
                self.scheduler_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self.scheduler_task
            await self.bot.session.close()
