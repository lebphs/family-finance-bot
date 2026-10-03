"""Synchronous compatibility facade for bot worker threads; no import-time I/O."""
from backend.sheets import (
    GoogleSheetsCategoryRepository, GoogleSheetsTransactionRepository, SheetsGateway,
)
from backend.services import UserService
from backend.models import CurrentUser
from config import load_settings
from datetime import date, datetime
from zoneinfo import ZoneInfo
from decimal import Decimal


class Sheet:
    def __init__(self, settings=None, *, gateway=None):
        settings = settings or load_settings()
        self.gateway = gateway or SheetsGateway(settings)
        self.categories = GoogleSheetsCategoryRepository(settings, gateway=self.gateway)
        self.transactions = GoogleSheetsTransactionRepository(settings, gateway=self.gateway)

    def get_statistics_by_categories(self):
        def read():
            rows = self.gateway.worksheet("Main").get("J11:K23")
            result = [(row[0], row[1]) for row in rows if len(row) >= 2 and row[0]]
            total = sum(float(str(value).replace(",", ".")) for _, value in result)
            return result + [("🧾 Итого", str(total))]
        return self.gateway.run(read, read_only=True)

    def get_categories(self):
        return list(self.get_subcategories())

    def get_subcategories(self):
        categories = self.gateway.run(self.categories._list_sync, read_only=True)
        return {category.name: list(category.subcategories) for category in categories}

    def add_transaction(self, data: list, *, author: CurrentUser):
        return self.gateway.run(
            self.transactions._create_sync, date.fromisoformat(data[0]),
            data[1], data[2], Decimal(str(data[3])), author,
        )

    def rotate_transactions_sheet_for_new_month(self, today=None):
        return self.gateway.run(self.transactions._rotate_sync, today or datetime.now(ZoneInfo("Europe/Minsk")).date())

    def delete_last_transaction(self, *, author: CurrentUser):
        # Legacy bot action affects a shared row; limit it to an active admin.
        UserService.require_admin(author)
        def delete():
            ws = self.gateway.worksheet("Transactions")
            rows = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
            if len(rows) < 2 or len(rows[1]) < 7 or not rows[1][6]:
                return False
            return self.transactions._delete_sync(str(rows[1][6]))
        return self.gateway.run(delete)

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
