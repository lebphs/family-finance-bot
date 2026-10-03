import asyncio
from backend.errors import ApiError, RepositoryError
from handlers.access import authorize_message
from aiogram import Dispatcher, F, types
from sheet import Sheet

async def show_statistics(callback: types.CallbackQuery):
    if await authorize_message(callback) is None:
        return
    try:
        statistics = await asyncio.to_thread(lambda: Sheet().get_statistics_by_categories())
    except RepositoryError as error:
        await callback.message.answer(str(error))
        return
    stats_message = "Ваши рассходы:\n\n"
    stats_message += "```\n"
    max_category = max(len(row[0].split(" ", 1)[-1]) for row in statistics)
    max_length = 0
    for row in statistics:
        category = row[0].split(' ', 1)[-1]
        number = f"{float(row[1]):.2f}"

        spaces_needed = max_category - len(category)

        message = f"{row[0]}{' ' * spaces_needed} {number:>8}\n"
        if max_length < len(message): max_length = len(message)
        if '🧾 Итого' in row:
            stats_message += "-" * (max_length - 2) + "\n"

        stats_message += message
    stats_message += "```"
    await callback.message.answer(stats_message, parse_mode="MarkdownV2")


async def send_excel_chart(callback: types.CallbackQuery):
    if await authorize_message(callback) is None:
        return
    try:
        image = await asyncio.to_thread(lambda: Sheet().send_excel_chart_as_image())
    except RepositoryError as error:
        await callback.message.answer(str(error))
        return
    await callback.message.answer_photo(image)
    await callback.answer()

async def delete_last_transaction(callback: types.CallbackQuery):
    author = await authorize_message(callback)
    if author is None:
        return
    try:
        deleted = await asyncio.to_thread(lambda: Sheet().delete_last_transaction(author=author))
    except (RepositoryError, ApiError) as error:
        await callback.message.answer(str(error))
        return
    await callback.message.answer("Транзакция успешно удалена" if deleted else "Нет транзакции с постоянным ID")
    await callback.answer()

def register_user(dp: Dispatcher):
    dp.callback_query.register(show_statistics, F.data == "show_statistics")
    dp.callback_query.register(send_excel_chart, F.data == "show_excel_chart")
    dp.callback_query.register(delete_last_transaction, F.data == "delete_last_transaction")
