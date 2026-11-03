"""NBRB official BYN rates, pinned to payment date and cached in SQLite."""
import asyncio
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo

import httpx

from mini_app.backend.database import Database
from mini_app.backend.errors import ApiError


@dataclass(frozen=True)
class ExchangeRate:
    value: Decimal
    date: date
    source: str


class ExchangeService:
    def __init__(self, settings, *, transport=None):
        self.database = Database(settings)
        self.transport = transport

    async def rate(self, currency, payment_date):
        if currency == 'BYN':
            return ExchangeRate(Decimal(1), payment_date, 'BYN')
        if payment_date > datetime.now(ZoneInfo('Europe/Minsk')).date():
            raise ApiError(code='future_rate', message='Курс на будущую дату ещё неизвестен', status_code=422)
        cached = await asyncio.to_thread(self._cached, currency, payment_date)
        if cached:
            return cached
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=12, follow_redirects=False) as client:
                # Both daily and monthly published currencies; request the exact
                # effective date, including weekends. Never substitute today's rate.
                for periodicity in (0, 1):
                    response = await client.get('https://api.nbrb.by/exrates/rates', params={
                        'ondate': payment_date.isoformat(), 'periodicity': periodicity})
                    response.raise_for_status()
                    rows = response.json(parse_float=Decimal)
                    if not isinstance(rows, list):
                        raise ValueError('Invalid rate table')
                    for row in rows:
                        if not isinstance(row, dict):
                            raise ValueError('Invalid rate row')
                        if row.get('Cur_Abbreviation') != currency:
                            continue
                        scale = Decimal(str(row['Cur_Scale']))
                        if not scale.is_finite() or scale <= 0:
                            raise ValueError('Invalid scale')
                        value = Decimal(str(row['Cur_OfficialRate'])) / scale
                        effective_date = date.fromisoformat(row['Date'][:10])
                        if not value.is_finite() or value <= 0 or effective_date != payment_date:
                            raise ValueError('Invalid rate')
                        result = ExchangeRate(value, effective_date, 'NBRB')
                        return await asyncio.to_thread(self._store, currency, payment_date, result)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, InvalidOperation, ZeroDivisionError):
            raise unavailable() from None
        raise ApiError(code='currency_unavailable', message='Для этой валюты нет курса на выбранную дату. Выберите другую валюту', status_code=422)

    def _cached(self, currency, payment_date):
        with self.database.connection() as conn:
            row = conn.execute('SELECT rate, rate_date, source FROM exchange_rates WHERE currency=? AND date=?',
                               (currency, payment_date.isoformat())).fetchone()
            return ExchangeRate(Decimal(row[0]), date.fromisoformat(row[1]), row[2]) if row else None

    def _store(self, currency, payment_date, result):
        with self.database.connection(write=True) as conn:
            conn.execute('INSERT OR IGNORE INTO exchange_rates VALUES (?, ?, ?, ?, ?)',
                         (currency, payment_date.isoformat(), str(result.value), result.date.isoformat(), result.source))
            row = conn.execute('SELECT rate, rate_date, source FROM exchange_rates WHERE currency=? AND date=?',
                               (currency, payment_date.isoformat())).fetchone()
            return ExchangeRate(Decimal(row[0]), date.fromisoformat(row[1]), row[2])

    async def convert(self, amount, currency, payment_date):
        rate = await self.rate(currency, payment_date)
        amount_byn = (amount * rate.value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if amount_byn <= 0 or amount_byn >= Decimal('10000000000'):
            raise ApiError(code='invalid_conversion', message='Сумма после пересчёта выходит за допустимые пределы', status_code=422)
        return dict(amount=amount_byn, original_amount=amount, currency=currency,
                    exchange_rate=rate.value, rate_date=rate.date, rate_source=rate.source)


def unavailable():
    return ApiError(code='rate_unavailable', message='Не удалось получить курс. Данные не потеряны, повторите сохранение', status_code=503)
