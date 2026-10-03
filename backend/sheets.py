"""Lazy Google Sheets connection and the synchronous repository boundary.

The lock serializes reads and writes in this process. Run one writer process;
migration additionally requires stopping every other writer.
"""
from __future__ import annotations

import asyncio
import math
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import threading
import time
from uuid import uuid4

from backend.errors import RepositoryError, RepositorySchemaError, RepositoryUnavailableError, UserAlreadyExistsError
from backend.models import Category, CurrentUser, Transaction
from config import Settings

TRANSACTION_HEADERS = ("telegram_user_id", "display_name", "transaction_id", "created_at", "updated_at")
ARCHIVE_PATTERN = re.compile(r"Transactions (0[1-9]|1[0-2])\.([0-9]{4})")
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


class SheetsGateway:
    def __init__(self, settings: Settings, *, spreadsheet=None):
        self.sheet_id = settings.google_sheet_id
        self._spreadsheet = spreadsheet
        with _LOCKS_GUARD:
            self.lock = _LOCKS.setdefault(self.sheet_id, threading.RLock())

    @property
    def spreadsheet(self):
        if self._spreadsheet is None:
            import gspread
            account = gspread.service_account(
                filename=str(Path(__file__).resolve().parents[1] / "google-credentials.json")
            )
            self._spreadsheet = account.open_by_key(self.sheet_id)
        return self._spreadsheet

    def worksheet(self, title):
        return self.spreadsheet.worksheet(title)

    def run(self, function, *args, read_only=False):
        # Retry only reads: a timeout after a write may mean it already succeeded.
        import gspread
        from requests.exceptions import RequestException
        from google.auth.exceptions import GoogleAuthError
        attempts = 3 if read_only else 1
        with self.lock:
            for attempt in range(attempts):
                try:
                    return function(*args)
                except (RepositoryError, UserAlreadyExistsError):
                    raise
                except gspread.exceptions.APIError as error:
                    status = getattr(error.response, "status_code", None)
                    temporary = status in {408, 429, 500, 502, 503, 504}
                    if temporary and attempt + 1 < attempts:
                        time.sleep(0.1 * (2 ** attempt))
                        continue
                    exception = RepositoryUnavailableError if temporary else RepositoryError
                    raise exception() from None
                except (RequestException, TimeoutError, ConnectionError):
                    if attempt + 1 < attempts:
                        time.sleep(0.1 * (2 ** attempt))
                        continue
                    raise RepositoryUnavailableError() from None
                except (gspread.exceptions.GSpreadException, GoogleAuthError, OSError):
                    raise RepositoryError() from None
                except (ValueError, TypeError, KeyError, InvalidOperation):
                    raise RepositorySchemaError() from None


class AsyncSheetsRepository:
    def __init__(self, settings: Settings, *, gateway=None):
        self.gateway = gateway or SheetsGateway(settings)

    async def _run(self, function, *args, read_only=False):
        return await asyncio.to_thread(
            self.gateway.run, function, *args, read_only=read_only
        )


class GoogleSheetsCategoryRepository(AsyncSheetsRepository):
    async def list(self) -> list[Category]:
        return await self._run(self._list_sync, read_only=True)

    def _list_sync(self):
        rows = self.gateway.worksheet("Preferences").get("B4:C43")
        categories: dict[str, list[str]] = {}
        current = None
        for row in rows:
            if row and str(row[0]).strip():
                current = str(row[0]).strip()
                categories.setdefault(current, [])
            if current and len(row) > 1 and str(row[1]).strip():
                name = str(row[1]).strip()
                if name not in categories[current]:
                    categories[current].append(name)
        return [Category(name, tuple(children)) for name, children in categories.items()]


def transaction_worksheets(spreadsheet):
    return [
        ws for ws in spreadsheet.worksheets()
        if ws.title == "Transactions" or ARCHIVE_PATTERN.fullmatch(ws.title)
    ]


def expanded(row):
    return (list(row) + [""] * 9)[:9]


def has_transaction(row):
    return any(value != "" for value in row[:4])


def parse_date(value):
    if isinstance(value, (int, float)):
        return date(1899, 12, 30) + timedelta(days=int(value))
    text = str(value).strip()
    for pattern in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            pass
    raise RepositorySchemaError()


def parse_timestamp(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None


def parse_transaction(row):
    a, b, c, d, e, f, g, h, i = expanded(row)
    amount = Decimal(str(d).replace("\u00a0", "").replace(" ", "").replace(",", "."))
    if not amount.is_finite():
        raise RepositorySchemaError()
    return Transaction(
        date=parse_date(a), description=str(b), category=str(c), amount=amount,
        author_id=int(e) if e else None,
        author_name=str(f) if e and f else "Автор не указан",
        transaction_id=str(g).strip() or None,
        created_at=parse_timestamp(h), updated_at=parse_timestamp(i),
    )


def verify_transaction_headers(ws):
    header = expanded(ws.row_values(1))
    if tuple(header[4:9]) != TRANSACTION_HEADERS:
        raise RepositorySchemaError()


def date_serial(value):
    return (value - date(1899, 12, 30)).days


def cell(value):
    if isinstance(value, (int, float)):
        return {"userEnteredValue": {"numberValue": value}}
    return {"userEnteredValue": {"stringValue": str(value)}}


def transaction_row(transaction):
    return [
        date_serial(transaction.date), transaction.description, transaction.category,
        float(transaction.amount), transaction.author_id or "", transaction.author_name,
        transaction.transaction_id, transaction.created_at.isoformat() if transaction.created_at else "",
        transaction.updated_at.isoformat() if transaction.updated_at else "",
    ]


class GoogleSheetsTransactionRepository(AsyncSheetsRepository):
    async def list(self) -> list[Transaction]:
        return await self._run(self._list_sync, read_only=True)

    async def get(self, transaction_id: str) -> Transaction | None:
        return await self._run(self._get_sync, transaction_id, read_only=True)

    async def create(self, *, date: date, description: str, category: str,
                     amount: Decimal, author: CurrentUser) -> Transaction:
        return await self._run(self._create_sync, date, description, category, amount, author)

    async def update(self, transaction_id: str, changes: dict[str, object]) -> Transaction | None:
        return await self._run(self._update_sync, transaction_id, changes)

    async def delete(self, transaction_id: str) -> bool:
        return await self._run(self._delete_sync, transaction_id)

    async def rotate(self, today: date) -> bool:
        return await self._run(self._rotate_sync, today)

    def _rows(self):
        ids = set()
        result = []
        for ws in transaction_worksheets(self.gateway.spreadsheet):
            for index, row in enumerate(ws.get_all_values(value_render_option="UNFORMATTED_VALUE")[1:], 2):
                if not has_transaction(row):
                    continue
                transaction = parse_transaction(row)
                if transaction.transaction_id:
                    if transaction.transaction_id in ids:
                        raise RepositorySchemaError()
                    ids.add(transaction.transaction_id)
                result.append((ws, index, transaction))
        return result

    def _list_sync(self):
        return sorted((t for _, _, t in self._rows()), key=lambda t: t.date, reverse=True)

    def _find(self, transaction_id):
        if not transaction_id:
            raise ValueError("A permanent ID is required")
        return next((entry for entry in self._rows() if entry[2].transaction_id == transaction_id), None)

    def _get_sync(self, transaction_id):
        entry = self._find(transaction_id)
        return entry[2] if entry else None

    def _create_sync(self, expense_date, description, category, amount, author):
        if not isinstance(expense_date, date) or not isinstance(author, CurrentUser):
            raise ValueError("Invalid transaction")
        amount = Decimal(str(amount))
        if (not amount.is_finite() or amount <= 0 or not math.isfinite(float(amount))
                or not category.strip() or author.telegram_user_id <= 0):
            raise ValueError("Invalid transaction")
        ws = self.gateway.worksheet("Transactions")
        verify_transaction_headers(ws)
        now = datetime.now(timezone.utc)
        transaction = Transaction(expense_date, description, category, amount,
                                  author.telegram_user_id, author.display_name, str(uuid4()), now, now)
        values = [cell(value) for value in transaction_row(transaction)]
        values[0]["userEnteredFormat"] = {"numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}}
        # Atomic insert + typed cells: descriptions starting with '=' stay plain text.
        self.gateway.spreadsheet.batch_update({"requests": [
            {"insertDimension": {"range": {"sheetId": ws.id, "dimension": "ROWS",
                                          "startIndex": 1, "endIndex": 2},
                                 "inheritFromBefore": False}},
            {"updateCells": {"start": {"sheetId": ws.id, "rowIndex": 1, "columnIndex": 0},
                             "rows": [{"values": values}],
                             "fields": "userEnteredValue,userEnteredFormat.numberFormat"}},
        ]})
        return transaction

    def _update_sync(self, transaction_id, changes):
        from dataclasses import replace
        if not changes or set(changes) - {"date", "description", "category", "amount"}:
            raise ValueError("Invalid transaction fields")
        entry = self._find(transaction_id)
        if entry is None:
            return None
        ws, row, transaction = entry
        verify_transaction_headers(ws)
        if "amount" in changes:
            changes = {**changes, "amount": Decimal(str(changes["amount"]))}
        updated = replace(transaction, **changes, updated_at=datetime.now(timezone.utc))
        if (not isinstance(updated.date, date) or not updated.category.strip()
                or not updated.amount.is_finite() or updated.amount <= 0
                or not math.isfinite(float(updated.amount))):
            raise ValueError("Invalid transaction")
        values = transaction_row(updated)
        # E-H are immutable, and legacy blank authors remain blank.
        columns = {"date": ("A", 0), "description": ("B", 1),
                   "category": ("C", 2), "amount": ("D", 3)}
        updates = [
            {"range": f"{columns[field][0]}{row}",
             "values": [[values[columns[field][1]]]]}
            for field in changes
        ]
        updates.append({"range": f"I{row}", "values": [[values[8]]]})
        ws.batch_update(updates, value_input_option="RAW")
        return updated

    def _delete_sync(self, transaction_id):
        entry = self._find(transaction_id)
        if entry is None:
            return False
        ws, row, _ = entry
        ws.delete_rows(row)
        return True

    def _rotate_sync(self, today):
        if today.day != 1:
            return False
        previous = today.replace(day=1) - timedelta(days=1)
        title = f"Transactions {previous:%m.%Y}"
        book = self.gateway.spreadsheet
        if title in {ws.title for ws in book.worksheets()}:
            return False
        current = book.worksheet("Transactions")
        verify_transaction_headers(current)
        # Duplicate and clear in one atomic request. Keep the current sheet ID:
        # existing Main formulas must continue to refer to Transactions.
        book.batch_update({"requests": [
            {"duplicateSheet": {"sourceSheetId": current.id, "newSheetName": title}},
            {"updateCells": {"range": {"sheetId": current.id, "startRowIndex": 1,
                                      "startColumnIndex": 0, "endColumnIndex": 9},
                             "fields": "userEnteredValue"}},
        ]})
        return True
