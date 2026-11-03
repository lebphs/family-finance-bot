import asyncio
import re
from uuid import uuid4
from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal, InvalidOperation

from aiogram import Dispatcher
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from mini_app.backend.errors import RepositoryError, ApiError
from mini_app.backend.travel import CURRENCIES
from bot.handlers.access import authorize_message
from bot.keyboards import user
from bot.sheet import Sheet


class ExpenseState(StatesGroup):
    amount = State()
    category = State()
    description = State()


async def cmd_start(message: Message, state: FSMContext):
    author = await authorize_message(message)
    if author is None:
        return
    try:
        trip = await asyncio.to_thread(lambda: Sheet().get_travel_context(author.telegram_user_id))
        keyboard = await user.categories_keyboard(bool(trip))
    except RepositoryError as error:
        await message.answer(str(error))
        return
    await state.clear()
    await state.set_state(ExpenseState.category)
    await message.answer("Привет! Чтобы добавить расходы выбери категорию:", reply_markup=keyboard)


def to_float(value: str):
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,10}(?:[.,]\d{1,2})?", value.strip()):
        raise ValueError
    amount = Decimal(value.replace(",", ".").strip())
    if not amount.is_finite() or amount <= 0:
        raise ValueError
    return amount


async def process_amount(message: Message, state: FSMContext):
    try:
        parts = (message.text or '').strip().split()
        if len(parts) not in (1, 2) or (len(parts) == 2 and parts[1].upper() not in CURRENCIES):
            raise ValueError
        amount = to_float(parts[0])
    except (InvalidOperation, ValueError):
        await message.answer("Введи положительную сумму, например 12,50")
        return
    data = await state.get_data()
    try:
        keyboard = await user.subcategories_keyboard(data["category"], bool(data.get("trip_id")))
    except RepositoryError as error:
        await message.answer(str(error))
        return
    await state.update_data(amount=str(amount), currency=parts[1].upper() if len(parts) == 2 else data.get("currency", "BYN"))
    await state.set_state(ExpenseState.description)
    await message.answer("Добавь описание или выбери подкатегорию", reply_markup=keyboard)


async def process_category(message: Message, state: FSMContext):
    author = await authorize_message(message)
    if author is None:
        return
    data = await state.get_data()
    try:
        trip = None
        if 'trip_id' not in data:
            trip = await asyncio.to_thread(lambda: Sheet().get_travel_context(author.telegram_user_id))
        trip_id = data.get('trip_id', trip.trip_id if trip else None)
        currency = data.get('currency', trip.currency if trip else 'BYN')
        categories = await asyncio.to_thread(lambda: Sheet().get_categories(bool(trip_id)))
    except RepositoryError as error:
        await message.answer(str(error))
        return
    if message.text not in categories:
        await message.answer("Выбери категорию из списка")
        return
    await state.update_data(category=message.text, trip_id=trip_id, currency=currency, request_id=str(uuid4()), date=datetime.now(ZoneInfo('Europe/Minsk')).date().isoformat())
    await state.set_state(ExpenseState.amount)
    await message.answer(f"Введи сумму в {currency}. Для другой валюты: 25 EUR")


async def process_record_description(message: Message, state: FSMContext):
    author = await authorize_message(message)
    if author is None:
        return
    if message.text == '/retry':
        data = await state.get_data()
        if not data.get('request_id') or 'description' not in data:
            await message.answer('Нет расхода для повторной отправки. Начните с /expense')
            return
        description = data['description']
    else:
        description = "" if message.text == "Без описания" else message.text
    if description is None:
        await message.answer("Отправь описание текстом")
        return
    await state.update_data(description=description)
    data = await state.get_data()
    record = [data.get("date", datetime.now(ZoneInfo("Europe/Minsk")).date().isoformat()), description, data["category"], data["amount"]]
    try:
        saved = await asyncio.to_thread(lambda: Sheet().add_transaction(record, author=author,
            request_id=data.get('request_id'), trip_id=data.get('trip_id'), currency=data.get('currency', 'BYN')))
    except (RepositoryError, ApiError) as error:
        # Keep both payload and idempotency key after an ambiguous write.
        await message.answer(f'{error} Для повторной отправки используйте /retry.')
        return
    await state.clear()
    try:
        trip = await asyncio.to_thread(lambda: Sheet().get_travel_context(author.telegram_user_id))
        keyboard = await user.categories_keyboard(bool(trip))
    except RepositoryError:
        keyboard = None
    await message.answer(
        f"Транзакция успешно добавлена: {data['amount']} {data.get('currency', 'BYN')}, {data['category']}! "
        + (f"≈ {saved.amount} BYN. " if data.get('currency', 'BYN') != 'BYN' else '') +
        "Для нового расхода выбери категорию или отправь /expense.",
        reply_markup=keyboard,
    )
    await message.answer("Так же вы можете:", reply_markup=user.main_inlinekeyboard())


async def category_message(message: Message):
    if not message.text:
        return False
    try:
        trip = await asyncio.to_thread(lambda: Sheet().get_travel_context(message.from_user.id))
        return message.text in await asyncio.to_thread(lambda: Sheet().get_categories(bool(trip)))
    except RepositoryError:
        return False


def register_expenses(dp: Dispatcher):
    dp.message.register(cmd_start, Command("expense"))
    dp.message.register(process_record_description, Command("retry"))
    dp.message.register(process_amount, ExpenseState.amount)
    dp.message.register(process_category, ExpenseState.category)
    dp.message.register(process_record_description, ExpenseState.description)
    dp.message.register(process_category, category_message)
