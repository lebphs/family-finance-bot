"""Persistent family trips and per-participant entry context."""
import asyncio
import json
import re
from datetime import date
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mini_app.backend.database import Database, encode
from mini_app.backend.errors import ApiError
from mini_app.backend.models import Category, Trip


# Entry currency choices. Availability in NBRB for a historical date is checked
# by the rate provider, never inferred from the current catalogue.
CURRENCIES = ('BYN', 'EUR', 'USD', 'RUB', 'PLN', 'GBP', 'CHF', 'CNY', 'TRY',
              'AED', 'GEL', 'KZT', 'THB', 'UAH', 'CZK', 'SEK', 'NOK', 'DKK',
              'JPY', 'CAD', 'AUD', 'HUF', 'INR', 'VND', 'SGD', 'NZD', 'ILS',
              'IDR', 'BRL', 'KRW', 'MYR', 'RON', 'RSD', 'AMD', 'AZN', 'BGN',
              'EGP', 'HKD', 'ISK', 'KGS', 'KWD', 'MDL', 'SAR', 'TWD', 'UZS')
TRAVEL_CATEGORIES = (
    'Проживание', 'Междугородний транспорт', 'Местный транспорт',
    'Еда и продукты', 'Экскурсии и развлечения', 'Покупки и сувениры',
    'Документы и страховки', 'Связь', 'Прочее',
)
Scope = Literal['all', 'everyday', 'travel']


def in_scope(item, scope):
    return scope == 'all' or (item.trip_id is None if scope == 'everyday' else item.trip_id is not None)


def trip_from_json(value):
    fields = json.loads(value)
    for key in ('date_from', 'date_to'):
        fields[key] = date.fromisoformat(fields[key])
    return Trip(**fields)


class TripInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    date_from: date
    date_to: date
    currency: str = 'EUR'

    @field_validator('date_from', 'date_to', mode='before')
    @classmethod
    def date_string(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise ValueError('Use YYYY-MM-DD')
        return value

    @field_validator('currency')
    @classmethod
    def currency_code(cls, value):
        if value not in CURRENCIES:
            raise ValueError('Unsupported currency')
        return value

    @model_validator(mode='after')
    def valid_dates(self):
        if self.date_from > self.date_to:
            raise ValueError('Invalid trip dates')
        return self


class TravelModeInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    trip_id: str | None = Field(default=None, min_length=1, max_length=100)


class TripRepository:
    def __init__(self, settings):
        self.database = Database(settings)

    async def list(self):
        return await asyncio.to_thread(self.list_sync)

    def list_sync(self):
        with self.database.connection() as conn:
            return [trip_from_json(row[0]) for row in conn.execute('SELECT payload FROM trips ORDER BY rowid DESC')]

    async def get(self, identifier):
        return next((trip for trip in await self.list() if trip.trip_id == identifier), None)

    async def save(self, request, user, identifier=None, *, complete=False):
        return await asyncio.to_thread(self._save, request, user, identifier, complete)

    def _save(self, request, user, identifier, complete):
        with self.database.connection(write=True) as conn:
            existing = None
            if identifier:
                row = conn.execute('SELECT payload FROM trips WHERE id=?', (identifier,)).fetchone()
                if not row:
                    raise missing_trip()
                existing = trip_from_json(row[0])
                if existing.created_by != user.telegram_user_id and user.role.value != 'admin':
                    raise ApiError(code='access_denied', message='Изменять поездку может её создатель или администратор', status_code=403)
            values = request.model_dump() if request else {
                key: getattr(existing, key) for key in ('name', 'date_from', 'date_to', 'currency')}
            trip = Trip(trip_id=identifier or str(uuid4()), created_by=existing.created_by if existing else user.telegram_user_id,
                        completed=complete or bool(existing and existing.completed), **values)
            conn.execute('INSERT OR REPLACE INTO trips VALUES (?, ?)', (trip.trip_id, encode(trip)))
            if trip.completed:
                conn.execute('UPDATE travel_preferences SET trip_id=NULL WHERE trip_id=?', (trip.trip_id,))
            return trip

    async def active_id(self, user_id):
        return await asyncio.to_thread(self.active_id_sync, user_id)

    def active_id_sync(self, user_id):
        with self.database.connection() as conn:
            row = conn.execute('SELECT trip_id FROM travel_preferences WHERE user_id=?', (user_id,)).fetchone()
            return row[0] if row else None

    async def set_active(self, user_id, identifier):
        await asyncio.to_thread(self._set_active, user_id, identifier)

    def _set_active(self, user_id, identifier):
        with self.database.connection(write=True) as conn:
            if identifier:
                row = conn.execute('SELECT payload FROM trips WHERE id=?', (identifier,)).fetchone()
                if not row:
                    raise missing_trip()
                if trip_from_json(row[0]).completed:
                    raise ApiError(code='trip_completed', message='Поездка завершена. Добавьте расход через её карточку', status_code=422)
            conn.execute('INSERT OR REPLACE INTO travel_preferences VALUES (?, ?)', (user_id, identifier))

    async def categories(self):
        return await asyncio.to_thread(self.categories_sync)

    def categories_sync(self):
        # Idempotent seed, kept separately from imported everyday preferences.
        with self.database.connection(write=True) as conn:
            if not conn.execute("SELECT 1 FROM metadata WHERE key='travel_categories_seeded'").fetchone():
                conn.executemany('INSERT OR IGNORE INTO travel_categories VALUES (?, ?)',
                                 [(name, encode(Category(name))) for name in TRAVEL_CATEGORIES])
                conn.execute("INSERT INTO metadata VALUES ('travel_categories_seeded', 'true')")
            return [Category(item['name'], tuple(item['subcategories'])) for item in
                    (json.loads(row[0]) for row in conn.execute('SELECT payload FROM travel_categories ORDER BY rowid'))]


def missing_trip():
    return ApiError(code='trip_not_found', message='Поездка не найдена', status_code=404)


class TravelService:
    def __init__(self, repository, transactions):
        self.repository, self.transactions = repository, transactions

    async def context(self, user_id):
        identifier = await self.repository.active_id(user_id)
        trip = await self.repository.get(identifier) if identifier else None
        return {'trip': trip if trip and not trip.completed else None, 'currencies': CURRENCIES}

    async def report(self, identifier):
        from mini_app.backend.schemas import TransactionResponse
        from mini_app.backend.statistics import categories, total
        trip = await self.repository.get(identifier)
        if trip is None:
            raise missing_trip()
        items = [item for item in await self.transactions.list() if item.trip_id == identifier]
        participants = {}
        for item in items:
            key = item.author_id
            entry = participants.setdefault(key, {'author_id': key, 'author_name': item.author_name, 'amount': 0})
            entry['amount'] += item.amount
        return {'trip': trip, 'total': str(total(items)), 'count': len(items), 'categories': categories(items),
                'participants': [{**p, 'amount': str(p['amount'])} for p in participants.values()],
                'transactions': [TransactionResponse.from_domain(item) for item in items]}
