"""Framework-independent application services."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from backend.errors import ApiError, TransactionConflictError, StaleTransactionError
from backend.transaction_version import transaction_version
from backend.models import CurrentUser, User, UserRole
from backend.repositories import CategoryRepository, TransactionRepository, UserAlreadyExistsError, UserRepository
from backend.schemas import (CreateExpenseRequest, HomeResponse, CategoryTotal, TransactionResponse,
                             TransactionFilters, TransactionPage, TransactionParticipant, UpdateTransactionRequest)


class ExpenseService:
    def __init__(self, transactions: TransactionRepository, categories: CategoryRepository):
        self.transactions = transactions
        self.categories = categories

    async def create(self, request: CreateExpenseRequest, user: CurrentUser) -> TransactionResponse:
        # Namespace the client key by the verified identity; it is never an author ID.
        transaction_id = str(uuid5(NAMESPACE_URL, f"family-finance:{user.telegram_user_id}:{request.request_id}"))
        existing = await self.transactions.get(transaction_id)
        if existing:
            if (existing.date, existing.description, existing.category, existing.amount, existing.author_id) != (
                    request.date, request.description, request.category, request.amount, user.telegram_user_id):
                raise self.conflict()
            return TransactionResponse.from_domain(existing)
        if request.category not in {item.name for item in await self.categories.list()}:
            raise ApiError(code="unknown_category", message="Выберите категорию из списка", status_code=422)
        try:
            transaction = await self.transactions.create(
                date=request.date, description=request.description, category=request.category,
                amount=request.amount, author=user, transaction_id=transaction_id,
            )
        except TransactionConflictError as error:
            raise self.conflict() from error
        return TransactionResponse.from_domain(transaction)

    @staticmethod
    def conflict():
        return ApiError(code="request_conflict", message="Этот запрос уже сохранён с другими данными", status_code=409)

    async def list(self, filters: TransactionFilters) -> TransactionPage:
        items = [item for item in await self.transactions.list()
                 if (not filters.date_from or item.date >= filters.date_from)
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
        if request.category != item.category and request.category not in {c.name for c in await self.categories.list()}:
            raise ApiError(code="unknown_category", message="Выберите категорию из списка", status_code=422)
        changes = {field: getattr(request, field) for field in ("date", "amount", "category", "description")
                   if getattr(request, field) != getattr(item, field)}
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

    async def home(self, today: date | None = None) -> HomeResponse:
        today = today or datetime.now(ZoneInfo("Europe/Minsk")).date()
        start = today.replace(day=1)
        previous = (start - timedelta(days=1)).replace(day=1)
        transactions = await self.transactions.list()
        current = [item for item in transactions if (item.date.year, item.date.month) == (start.year, start.month)]
        total = sum((item.amount for item in current), Decimal(0))
        previous_total = sum((item.amount for item in transactions if previous <= item.date < start), Decimal(0))
        by_category: dict[str, Decimal] = {}
        for item in current:
            by_category[item.category] = by_category.get(item.category, Decimal(0)) + item.amount

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
