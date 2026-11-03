"""Framework-independent application services."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from mini_app.backend.errors import ApiError, TransactionConflictError, StaleTransactionError
from mini_app.backend.transaction_version import transaction_version
from mini_app.backend.models import CurrentUser, User, UserRole
from mini_app.backend.repositories import CategoryRepository, TransactionRepository, UserAlreadyExistsError, UserRepository
from mini_app.backend.schemas import (CreateExpenseRequest, HomeResponse, CategoryTotal, TransactionResponse,
                             TransactionFilters, TransactionPage, TransactionParticipant, UpdateTransactionRequest)


class ExpenseService:
    def __init__(self, transactions: TransactionRepository, categories: CategoryRepository, *, trips=None, exchange=None):
        self.transactions = transactions
        self.categories = categories
        self.trips = trips
        self.exchange = exchange

    async def create(self, request: CreateExpenseRequest, user: CurrentUser) -> TransactionResponse:
        # Namespace the client key by the verified identity; it is never an author ID.
        transaction_id = str(uuid5(NAMESPACE_URL, f"family-finance:{user.telegram_user_id}:{request.request_id}"))
        existing = await self.transactions.get(transaction_id)
        if existing:
            expected_trip = request.trip_id if 'trip_id' in request.model_fields_set else existing.trip_id
            expected_currency = request.currency or existing.currency
            if (existing.date, existing.description, existing.category, existing.original_amount or existing.amount,
                existing.author_id, existing.trip_id, existing.currency) != (
                    request.date, request.description, request.category, request.amount,
                    user.telegram_user_id, expected_trip, expected_currency):
                raise self.conflict()
            return TransactionResponse.from_domain(existing)
        trip_id = request.trip_id
        if self.trips and 'trip_id' not in request.model_fields_set:
            trip_id = await self.trips.active_id(user.telegram_user_id)
        trip = await self.resolve_trip(trip_id)
        currency = request.currency or (trip.currency if trip else 'BYN')
        await self.validate_category(request.category, trip_id)
        details = {}
        if trip_id or currency != 'BYN':
            if self.exchange is None:
                raise ApiError(code='currency_unavailable', message='Пересчёт валют недоступен', status_code=503)
            details = await self.exchange.convert(request.amount, currency, request.date)
            details['trip_id'] = trip_id
        try:
            transaction = await self.transactions.create(
                date=request.date, description=request.description, category=request.category,
                amount=details.pop('amount', request.amount), author=user, transaction_id=transaction_id, **details,
            )
        except TransactionConflictError as error:
            raise self.conflict() from error
        return TransactionResponse.from_domain(transaction)

    async def resolve_trip(self, trip_id):
        if trip_id is None:
            return None
        trip = await self.trips.get(trip_id) if self.trips else None
        if trip is None:
            raise ApiError(code='trip_not_found', message='Поездка не найдена', status_code=422)
        return trip

    async def validate_category(self, category, trip_id):
        categories = await self.trips.categories() if trip_id and self.trips else await self.categories.list()
        if category not in {item.name for item in categories}:
            raise ApiError(code="unknown_category", message="Выберите категорию из списка", status_code=422)

    @staticmethod
    def conflict():
        return ApiError(code="request_conflict", message="Этот запрос уже сохранён с другими данными", status_code=409)

    async def list(self, filters: TransactionFilters) -> TransactionPage:
        from mini_app.backend.travel import in_scope
        items = [item for item in await self.transactions.list()
                 if in_scope(item, filters.scope)
                 and (not filters.trip_id or item.trip_id == filters.trip_id)
                 and (not filters.date_from or item.date >= filters.date_from)
                 and (not filters.date_to or item.date <= filters.date_to)
                 and (not filters.category or item.category == filters.category)
                 and (filters.author_id is None or item.author_id == filters.author_id)
                 and (not filters.unknown_author or item.author_id is None)
                 and filters.search.casefold() in item.description.casefold()]
        def key(item):
            created = item.created_at or datetime.min.replace(tzinfo=timezone.utc)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            return item.date, created, item.transaction_id or ""
        items.sort(key=key, reverse=True)
        end = filters.offset + filters.limit
        return TransactionPage(items=[TransactionResponse.from_domain(item) for item in items[filters.offset:end]],
                               total=len(items), next_offset=end if end < len(items) else None)

    async def participants(self) -> list[TransactionParticipant]:
        # Only public author labels from the family ledger, never Users settings.
        names = {}
        for item in await self.transactions.list():
            names[item.author_id] = item.author_name
        return [TransactionParticipant(author_id=identifier, author_name=name)
                for identifier, name in sorted(names.items(), key=lambda pair: (pair[0] is None, pair[0] or 0))]

    async def get(self, transaction_id: str):
        item = await self.transactions.get(transaction_id)
        if item is None:
            raise ApiError(code="transaction_not_found", message="Операция удалена или не найдена", status_code=404)
        return item

    @staticmethod
    def require_owner(item, user: CurrentUser):
        if user.role is not UserRole.ADMIN and item.author_id != user.telegram_user_id:
            raise ApiError(code="access_denied", message="Можно изменять только свои операции", status_code=403)

    @staticmethod
    def stale():
        return ApiError(code="transaction_changed", message="Операция уже изменена. Загрузите актуальные данные", status_code=409)

    async def update(self, transaction_id: str, request: UpdateTransactionRequest, user: CurrentUser):
        item = await self.get(transaction_id)
        self.require_owner(item, user)
        if transaction_version(item) != request.version:
            raise self.stale()
        trip_id = request.trip_id if 'trip_id' in request.model_fields_set else item.trip_id
        await self.resolve_trip(trip_id)
        if request.category != item.category or trip_id != item.trip_id:
            await self.validate_category(request.category, trip_id)
        currency = request.currency or item.currency
        changes = {field: getattr(request, field) for field in ("date", "category", "description")
                   if getattr(request, field) != getattr(item, field)}
        if trip_id != item.trip_id:
            changes['trip_id'] = trip_id
        if request.amount != (item.original_amount or item.amount) or currency != item.currency or request.date != item.date:
            if self.exchange and (currency != 'BYN' or item.original_amount is not None or trip_id):
                changes.update(await self.exchange.convert(request.amount, currency, request.date))
            else:
                changes['amount'] = request.amount
        if not changes:
            return TransactionResponse.from_domain(item)
        try:
            updated = await self.transactions.update(transaction_id, changes, expected_version=request.version)
        except StaleTransactionError as error:
            raise self.stale() from error
        if updated is None:
            raise ApiError(code="transaction_not_found", message="Операция уже удалена", status_code=404)
        return TransactionResponse.from_domain(updated)

    async def delete(self, transaction_id: str, version: str, user: CurrentUser):
        item = await self.get(transaction_id)
        self.require_owner(item, user)
        try:
            deleted = await self.transactions.delete(transaction_id, expected_version=version)
        except StaleTransactionError as error:
            raise self.stale() from error
        if not deleted:
            raise ApiError(code="transaction_not_found", message="Операция уже удалена", status_code=404)

    async def home(self, today: date | None = None, scope='everyday') -> HomeResponse:
        today = today or datetime.now(ZoneInfo("Europe/Minsk")).date()
        start = today.replace(day=1)
        previous = (start - timedelta(days=1)).replace(day=1)
        from mini_app.backend.travel import in_scope
        transactions = [item for item in await self.transactions.list() if in_scope(item, scope)]
        current = [item for item in transactions if (item.date.year, item.date.month) == (start.year, start.month)]
        total = sum((item.amount for item in current), Decimal(0))
        previous_total = sum((item.amount for item in transactions if previous <= item.date < start), Decimal(0))
        by_category: dict[str, Decimal] = {}
        for item in current:
            name = 'Поездки' if scope == 'all' and item.trip_id else item.category
            by_category[name] = by_category.get(name, Decimal(0)) + item.amount

        def recent_key(item):
            created = item.created_at or datetime.min.replace(tzinfo=timezone.utc)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            return item.date, created, item.transaction_id or ""

        recent = sorted(transactions, key=recent_key, reverse=True)[:5]
        return HomeResponse(
            month=start.strftime("%Y-%m"), total=total, previous_total=previous_total,
            change=total - previous_total,
            change_percent=((total - previous_total) / previous_total * 100).quantize(Decimal("0.01")) if previous_total else None,
            categories=[CategoryTotal(category=name, amount=amount) for name, amount in
                        sorted(by_category.items(), key=lambda pair: (-pair[1], pair[0]))],
            recent=[TransactionResponse.from_domain(item) for item in recent],
        )


class ApplicationStatusService:
    def get_status(self) -> dict[str, str]:
        return {"status": "ok", "service": "family-finance-backend"}


class UserService:
    def __init__(self, repository: UserRepository) -> None:
        self._repository = repository

    async def authorize(self, telegram_user_id: int) -> CurrentUser:
        user = await self._repository.get(telegram_user_id)
        if user is None or not user.active:
            raise ApiError(code="access_denied", message="Нет доступа", status_code=403)
        return CurrentUser.from_user(user)

    @staticmethod
    def require_admin(current_user: CurrentUser) -> None:
        if current_user.role is not UserRole.ADMIN:
            raise ApiError(code="access_denied", message="Недостаточно прав", status_code=403)

    async def list_users(self) -> list[User]:
        return await self._repository.list()

    async def create_user(self, user: User) -> User:
        try:
            return await self._repository.create(user)
        except UserAlreadyExistsError as error:
            raise ApiError(
                code="user_already_exists",
                message="Пользователь уже существует",
                status_code=409,
            ) from error

    async def update_user(self, telegram_user_id: int, changes: dict[str, object]) -> User:
        user = await self._repository.update(telegram_user_id, changes)
        if user is None:
            raise ApiError(code="user_not_found", message="Пользователь не найден", status_code=404)
        return user
