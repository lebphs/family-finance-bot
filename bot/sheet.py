"""Synchronous compatibility facade for bot worker threads; no import-time I/O."""
from mini_app.backend.database import SQLiteCategoryRepository, SQLiteTransactionRepository
from mini_app.backend.services import UserService, ExpenseService
from mini_app.backend.travel import TripRepository
from mini_app.backend.exchange import ExchangeService
from mini_app.backend.schemas import CreateExpenseRequest
import asyncio
from uuid import uuid4
from mini_app.backend.models import CurrentUser
from config import load_settings
from datetime import date, datetime
from zoneinfo import ZoneInfo
from decimal import Decimal


class Sheet:
    def __init__(self, settings=None):
        settings = settings or load_settings()
        self.settings = settings
        self.trips = TripRepository(settings)
        self.categories = SQLiteCategoryRepository(settings)
        self.transactions = SQLiteTransactionRepository(settings)

    def get_statistics_by_categories(self):
        today = datetime.now(ZoneInfo("Europe/Minsk")).date()
        totals = {}
        for item in self.transactions._list_sync():
            if item.trip_id is None and (item.date.year, item.date.month) == (today.year, today.month):
                name = item.category
                totals[name] = totals.get(name, Decimal(0)) + item.amount
        return [(name, str(amount)) for name, amount in sorted(totals.items())] + [
            ("🧾 Итого", str(sum(totals.values(), Decimal(0))))]

    def get_categories(self, travel=False):
        return list(self.get_subcategories(travel))

    def get_subcategories(self, travel=False):
        categories = self.trips.categories_sync() if travel else self.categories._list_sync()
        return {category.name: list(category.subcategories) for category in categories}

    def get_travel_context(self, user_id):
        identifier = self.trips.active_id_sync(user_id)
        return next((t for t in self.trips.list_sync() if t.trip_id == identifier and not t.completed), None)

    def add_transaction(self, data: list, *, author: CurrentUser, request_id=None, **context):
        request = CreateExpenseRequest(request_id=request_id or uuid4(), date=data[0],
                                       description=data[1], category=data[2], amount=data[3], **context)
        service = ExpenseService(self.transactions, self.categories, trips=self.trips,
                                 exchange=ExchangeService(self.settings))
        return asyncio.run(service.create(request, author))

    def rotate_transactions_sheet_for_new_month(self, today=None):
        return False

    def delete_last_transaction(self, *, author: CurrentUser):
        UserService.require_admin(author)
        items = self.transactions._list_sync()
        if not items:
            return False
        # Bot's latest operation follows creation order, regardless of expense date.
        def created(item):
            value = item.created_at or datetime.min.replace(tzinfo=ZoneInfo("UTC"))
            return value if value.tzinfo else value.replace(tzinfo=ZoneInfo("UTC"))
        latest = max(items, key=created)
        from mini_app.backend.transaction_version import transaction_version
        return self.transactions._delete_sync(latest.transaction_id, transaction_version(latest))

    def send_excel_chart_as_image(self):
        from io import BytesIO
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib.figure import Figure
        from aiogram.types import BufferedInputFile
        statistics = self.get_statistics_by_categories()
        labels, values = [], []
        for name, value in statistics:
            if "🧾 Итого" in name:
                continue
            labels.append(name.split(" ", 1)[-1])
            values.append(float(str(value).replace(",", ".")))
        figure = Figure(figsize=(8, 8))
        axes = figure.subplots()
        if any(values):
            axes.pie(values, labels=labels,
                     autopct=lambda pct: f"{pct:.1f}%" if pct >= 3 else "", startangle=90)
        else:
            axes.text(0.5, 0.5, "Нет расходов", ha="center")
        axes.axis("equal")
        figure.tight_layout()
        output = BytesIO()
        figure.savefig(output, format="png")
        return BufferedInputFile(output.getvalue(), filename="chart.png")
