"""Trip mode and summaries; uses the same persistent context as Mini App."""
from aiogram import F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.handlers.access import authorize_message
from bot.handlers.expenses import ExpenseState
from bot.keyboards.user import categories_keyboard
from config import load_settings
from mini_app.backend.database import SQLiteTransactionRepository
from mini_app.backend.errors import ApiError, RepositoryError
from mini_app.backend.travel import TripRepository, TravelService


async def show_trips(message):
    if await authorize_message(message) is None:
        return
    try:
        trips = await TripRepository(load_settings()).list()
        buttons = []
        for trip in trips:
            buttons.append([InlineKeyboardButton(text=trip.name, callback_data=f'trip:report:{trip.trip_id}')])
        buttons.append([InlineKeyboardButton(text='Обычный режим', callback_data='trip:off')])
        await message.answer('Выберите поездку. Создать или изменить её можно в Mini App.',
                             reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    except RepositoryError as error:
        await message.answer(str(error))


async def trip_action(callback, state):
    author = await authorize_message(callback)
    if author is None:
        return
    await callback.answer()
    parts = (callback.data or '').split(':')
    settings = load_settings()
    trips = TripRepository(settings)
    try:
        if parts == ['trip', 'off']:
            await trips.set_active(author.telegram_user_id, None)
            await state.clear()
            await callback.message.answer('Обычный режим · BYN. Выберите категорию:', reply_markup=await categories_keyboard())
            return
        if len(parts) != 3 or parts[1] not in {'report', 'mode', 'expense'}:
            return
        trip = await trips.get(parts[2])
        if trip is None:
            await callback.message.answer('Поездка не найдена')
            return
        if parts[1] == 'mode':
            await trips.set_active(author.telegram_user_id, trip.trip_id)
        if parts[1] in {'mode', 'expense'}:
            await state.clear()
            await state.update_data(trip_id=trip.trip_id, currency=trip.currency)
            await state.set_state(ExpenseState.category)
            await callback.message.answer(f'{trip.name} · {trip.currency}. Выберите категорию:',
                                          reply_markup=await categories_keyboard(True))
            return
        report = await TravelService(trips, SQLiteTransactionRepository(settings)).report(trip.trip_id)
        lines = [f'{trip.name} · {trip.date_from} — {trip.date_to}', f"Всего: {report['total']} BYN", 'Все оплаты, включая покупки заранее.']
        lines.extend(f'{item.category}: {item.amount} BYN' for item in report['categories'])
        lines.extend(f"{p['author_name']}: {p['amount']} BYN" for p in report['participants'])
        buttons = [[InlineKeyboardButton(text='Добавить расход', callback_data=f'trip:expense:{trip.trip_id}')]]
        if not trip.completed:
            buttons.append([InlineKeyboardButton(text='Включить режим поездки', callback_data=f'trip:mode:{trip.trip_id}')])
        await callback.message.answer('\n'.join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    except (ApiError, RepositoryError) as error:
        await callback.message.answer(str(error))


def register_trips(dispatcher):
    dispatcher.message.register(show_trips, Command('trips'))
    dispatcher.callback_query.register(trip_action, F.data.startswith('trip:'))
