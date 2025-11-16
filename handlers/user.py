from aiogram import Dispatcher, F, types
from aiogram.types import Message
from keyboards.user import categories_keyboard
from sheet import Sheet

async def show_statistics(callback: types.CallbackQuery):
    sheet = Sheet()
    statistics = sheet.get_statistics_by_categories()
    stats_message = "Ваши рассходы:\n\n"
    stats_message += "```\n"
    max_category = max(len(row[0].split(' ', 1)[1]) for row in statistics)
    max_length = 0
    for row in statistics:
        category = row[0].split(' ', 1)[1]
        number = f"{float(row[1]):.2f}"

        spaces_needed = max_category - len(category)

        message = f"{row[0]}{' ' * spaces_needed} {number:>8}\n"
        if max_length < len(message): max_length = len(message)
        if '🧾 Итого' in row:
            stats_message += "-" * (max_length - 2) + "\n"

        stats_message += message
    stats_message += "```"
    await callback.message.answer(stats_message, parse_mode="MarkdownV2", reply_markup=categories_keyboard())


async def delete_last_transaction(message: Message):
    sheet = Sheet()
    sheet.delete_last_transaction()
    await message.answer("Транзакция успешно удалена")

def register_user(dp: Dispatcher):
    dp.callback_query.register(show_statistics, F.data == "show_statistics")
    dp.callback_query.register(delete_last_transaction, F.data == "delete_last_transaction")
