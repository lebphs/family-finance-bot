from aiogram import Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from gspread.exceptions import GSpreadException

import sheet
from keyboards import user
from keyboards.user import categories_keyboard, no_description_keyboard
from sheet import Sheet
import datetime


class ExpenseState(StatesGroup):
    amount = State()
    category = State()
    description = State()

sheet = Sheet()
categories = sheet.get_categories()

async def cmd_start(message: Message, state: FSMContext):
    await state.set_state(ExpenseState.category)
    await message.answer(
       "Привет! Чтобы добавить расходы выбери категорию:",
        parse_mode="Markdown",
        reply_markup=categories_keyboard()
    )

async def process_amount(message: Message, state: FSMContext):
    amount = float(message.text)
    await state.update_data(amount=amount)

    await state.set_state(ExpenseState.description)
    await message.answer(
        "Добавь описание",
       reply_markup=no_description_keyboard(),
    )

async def process_category(message: Message, state: FSMContext):
    category =  message.text
    await state.update_data(category=category)

    await state.set_state(ExpenseState.amount)
    await message.answer("Введи сумму...")

async def process_record_description(message: Message, state: FSMContext):
    record = []
    description = ""
    if message.text not in ["Без описания"]:
        description = message.text
    await state.update_data(description=description)

    
    data = await state.get_data()
    record = [
        str(datetime.date.today()),
        data["description"],
        data["category"],
        data["amount"],
    ]

    sheet = Sheet()
    try:
        sheet.add_transaction(record)
    except GSpreadException:
        await state.clear()
        await message.answer("Что-то пошло не так",
            reply_markup=user.categories_keyboard()
        )
        return

    answer_message = "Транзакция успешно добавлена {amount} to {category}!"
    await message.answer(
        answer_message.format(
            amount=data["amount"], category=data["category"]
        ),
        reply_markup=user.categories_keyboard(),
    )
    await message.answer(
        "Так же вы можете:",
        reply_markup=user.main_inlinekeyboard(),
    )
    await state.clear()

def register_expenses(dp: Dispatcher):
    dp.message.register(process_amount, ExpenseState.amount)
    dp.message.register(process_category, ExpenseState.category)
    dp.message.register(process_record_description, ExpenseState.description)
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(process_category,  lambda message: F.text in categories)
