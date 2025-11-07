from aiogram import Dispatcher, F, types
from aiogram.types import Message
from keyboards.user import categories_keyboard
from sheet import Sheet

async def show_statistics(callback: types.CallbackQuery):
    sheet = Sheet()
    statistics = sheet.get_statistics_by_categories()
    stats_message = "Ваши рассходы:\n\n"
    stats_message += "```\n"
    for row in statistics:
        stats_message += row[0] + " - "  + row[1] + "\n"
    stats_message += "```"
    await callback.message.answer(stats_message, parse_mode="MarkdownV2", reply_markup=categories_keyboard())

async def delete_last_transaction(message: Message):
    sheet = Sheet()
    sheet.delete_last_transaction()
    await message.answer("Транзакция успешно удалена")

def register_user(dp: Dispatcher):
    dp.callback_query.register(show_statistics, F.data == "show_statistics")
    dp.callback_query.register(delete_last_transaction, F.data == "delete_last_transaction")
