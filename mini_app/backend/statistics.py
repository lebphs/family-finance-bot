"""Read-only statistics over the current ledger and all monthly archives."""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mini_app.backend.repositories import TransactionRepository
from mini_app.backend.schemas import CategoryTotal, TransactionParticipant


class StatisticsQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal['months', 'range', 'compare'] = 'months'
    months: Literal[1, 2, 3, 6, 12] = 1
    month_from: str | None = None
    month_to: str | None = None
    compare_from: str | None = None
    compare_to: str | None = None
    author_id: int | None = Field(default=None, gt=0)
    unknown_author: bool = False

    @field_validator('months', mode='before')
    @classmethod
    def parse_months(cls, value):
        if isinstance(value, str) and value in {'1', '2', '3', '6', '12'}:
            return int(value)
        return value

    @field_validator('month_from', 'month_to', 'compare_from', 'compare_to')
    @classmethod
    def month(cls, value):
        if value is not None:
            if not re.fullmatch(r'\d{4}-\d{2}', value):
                raise ValueError('Use YYYY-MM')
            date.fromisoformat(value + '-01')
        return value

    @model_validator(mode='after')
    def valid_selection(self):
        if self.author_id is not None and self.unknown_author:
            raise ValueError('Conflicting authors')
        if self.mode == 'range':
            if not self.month_from or not self.month_to or self.month_from > self.month_to:
                raise ValueError('Invalid range')
        elif self.month_from is not None or self.month_to is not None:
            raise ValueError('Range requires range mode')
        if self.mode == 'compare':
            if not self.compare_from or not self.compare_to or self.compare_from == self.compare_to:
                raise ValueError('Choose two distinct months')
        elif self.compare_from is not None or self.compare_to is not None:
            raise ValueError('Comparison requires compare mode')
        return self


class MonthTotal(BaseModel):
    month: str
    total: Decimal
    change: Decimal | None
    change_percent: Decimal | None


class ParticipantStatistics(BaseModel):
    author_id: int | None
    author_name: str
    total: Decimal
    share_percent: Decimal | None
    count: int
    average: Decimal
    categories: list[CategoryTotal]
    monthly: list[MonthTotal]


class MonthComparison(BaseModel):
    month_from: str
    month_to: str
    from_total: Decimal
    to_total: Decimal
    change: Decimal
    change_percent: Decimal | None


class StatisticsResponse(BaseModel):
    mode: str
    months: list[str]
    author_id: int | None
    unknown_author: bool
    total: Decimal
    family_total: Decimal
    count: int
    categories: list[CategoryTotal]
    monthly: list[MonthTotal]
    participants: list[ParticipantStatistics]
    available_participants: list[TransactionParticipant]
    comparison: MonthComparison | None


def percentage(value: Decimal, base: Decimal) -> Decimal | None:
    return (value / base * 100).quantize(Decimal('0.01')) if base else None


def month_number(value: str) -> int:
    year, month = map(int, value.split('-'))
    return (year - 1) * 12 + month - 1


def month_label(number: int) -> str:
    year, month = divmod(number, 12)
    return f'{year + 1:04d}-{month + 1:02d}'


def selected_months(query: StatisticsQuery, today: date) -> list[str]:
    if query.mode == 'compare':
        return sorted([query.compare_from, query.compare_to])
    if query.mode == 'range':
        first, last = month_number(query.month_from), month_number(query.month_to)
    else:
        last = (today.year - 1) * 12 + today.month - 1
        first = max(0, last - query.months + 1)
    return [month_label(number) for number in range(first, last + 1)]


def total(items) -> Decimal:
    return sum((item.amount for item in items), Decimal(0))


def categories(items) -> list[CategoryTotal]:
    result: dict[str, Decimal] = {}
    for item in items:
        result[item.category] = result.get(item.category, Decimal(0)) + item.amount
    return [CategoryTotal(category=name, amount=amount) for name, amount in
            sorted(result.items(), key=lambda pair: (-pair[1], pair[0]))]


def monthly(items, months: list[str]) -> list[MonthTotal]:
    amounts = dict.fromkeys(months, Decimal(0))
    for item in items:
        key = f'{item.date.year:04d}-{item.date.month:02d}'
        amounts[key] += item.amount
    result = []
    previous = None
    for month in months:
        amount = amounts[month]
        change = amount - previous if previous is not None else None
        result.append(MonthTotal(month=month, total=amount, change=change,
                                 change_percent=percentage(change, previous) if change is not None else None))
        previous = amount
    return result


class StatisticsService:
    def __init__(self, transactions: TransactionRepository):
        self.transactions = transactions

    async def get(self, query: StatisticsQuery, today: date | None = None) -> StatisticsResponse:
        today = today or datetime.now(ZoneInfo('Europe/Minsk')).date()
        months = selected_months(query, today)
        ledger = await self.transactions.list()
        # A single read gives consistent family/participant totals. Latest dated
        # author label wins deterministically when stored names changed over time.
        names = {}
        for item in sorted(ledger, key=lambda item: (item.date, item.transaction_id or '', item.author_name)):
            names[item.author_id] = item.author_name if item.author_id is not None else 'Автор не указан'
        identifiers = sorted(names, key=lambda identifier: (identifier is None, identifier or 0))
        month_set = set(months)
        family = [item for item in ledger if f'{item.date.year:04d}-{item.date.month:02d}' in month_set]
        family_total = total(family)
        selected = [item for item in family if
                    (query.author_id is None or item.author_id == query.author_id)
                    and (not query.unknown_author or item.author_id is None)]
        grouped = {}
        for item in family:
            grouped.setdefault(item.author_id, []).append(item)
        participants = []
        # Include known ledger authors with zero spending in this period so
        # participant comparison and filtering remain stable for empty months.
        for identifier in identifiers:
            items = grouped.get(identifier, [])
            amount = total(items)
            participants.append(ParticipantStatistics(
                author_id=identifier, author_name=names[identifier], total=amount,
                share_percent=percentage(amount, family_total), count=len(items),
                average=(amount / len(items)).quantize(Decimal('0.01')) if items else Decimal(0),
                categories=categories(items), monthly=monthly(items, months)))
        dynamics = monthly(selected, months)
        comparison = None
        if query.mode == 'compare':
            values = {item.month: item.total for item in dynamics}
            before, after = values[query.compare_from], values[query.compare_to]
            comparison = MonthComparison(month_from=query.compare_from, month_to=query.compare_to,
                                         from_total=before, to_total=after, change=after - before,
                                         change_percent=percentage(after - before, before))
        return StatisticsResponse(
            mode=query.mode, months=months, author_id=query.author_id, unknown_author=query.unknown_author,
            total=total(selected), family_total=family_total, count=len(selected),
            categories=categories(selected), monthly=dynamics, participants=participants,
            available_participants=[TransactionParticipant(author_id=identifier, author_name=names[identifier])
                                    for identifier in identifiers], comparison=comparison)
