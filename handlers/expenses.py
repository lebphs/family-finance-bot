import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal, InvalidOperation

from aiogram import Dispatcher
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from backend.errors import RepositoryError
from handlers.access import authorize_message
from keyboards import user
from sheet import Sheet


class ExpenseState(StatesGroup):
    amount = State()
    category = State()
    description = State()


async def cmd_start(message: Message, state: FSMContext):
    if await authorize_message(message) is None:
        return
    try:
        keyboard = await user.categories_keyboard()
    except RepositoryError as error:
        await message.answer(str(error))
        return
    await state.set_state(ExpenseState.category)
    await message.answer("Привет! Чтобы добавить расходы выбери категорию:", reply_markup=keyboard)


def to_float(value: str):
    amount = Decimal((value or "").replace(",", ".").strip())
    if not amount.is_finite() or amount <= 0:
        raise ValueError
    return amount


async def process_amount(message: Message, state: FSMContext):
    try:
        amount = to_float(message.text)
    except (InvalidOperation, ValueError):
        await message.answer("Введи положительную сумму, например 12,50")
        return
    data = await state.get_data()
    try:
        keyboard = await user.subcategories_keyboard(data["category"])
    except RepositoryError as error:
        await message.answer(str(error))
        return
    await state.update_data(amount=str(amount))
    await state.set_state(ExpenseState.description)
    await message.answer("Добавь описание или выбери подкатегорию", reply_markup=keyboard)


async def process_category(message: Message, state: FSMContext):
    if await authorize_message(message) is None:
        return
    try:
        categories = await asyncio.to_thread(lambda: Sheet().get_categories())
    except RepositoryError as error:
        await message.answer(str(error))
        return
    if message.text not in categories:
        await message.answer("Выбери категорию из списка")
        return
    await state.update_data(category=message.text)
    await state.set_state(ExpenseState.amount)
    await message.answer("Введи сумму...")


async def process_record_description(message: Message, state: FSMContext):
    author = await authorize_message(message)
    if author is None:
        return
    description = "" if message.text == "Без описания" else message.text
    if description is None:
        await message.answer("Отправь описание текстом")
        return
    await state.update_data(description=description)
    data = await state.get_data()
    record = [datetime.now(ZoneInfo("Europe/Minsk")).date().isoformat(), description, data["category"], data["amount"]]
    try:
        await asyncio.to_thread(lambda: Sheet().add_transaction(record, author=author))
    except RepositoryError as error:
        # Keep the entered data. Do not automatically retry an ambiguous write.
        await message.answer(str(error))
        return
    await state.clear()
    try:
        keyboard = await user.categories_keyboard()
    except RepositoryError:
        keyboard = None
    await message.answer(
        f"Транзакция успешно добавлена: {data['amount']} BYN, {data['category']}! "
        "Для нового расхода выбери категорию или отправь /start.",
        reply_markup=keyboard,
    )
    await message.answer("Так же вы можете:", reply_markup=user.main_inlinekeyboard())


async def category_message(message: Message):
    if not message.text:
        return False
    try:
        return message.text in await asyncio.to_thread(lambda: Sheet().get_categories())
    except RepositoryError:
        return False


def register_expenses(dp: Dispatcher):
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(process_amount, ExpenseState.amount)
    dp.message.register(process_category, ExpenseState.category)
    dp.message.register(process_record_description, ExpenseState.description)
    dp.message.register(process_category, category_message)
