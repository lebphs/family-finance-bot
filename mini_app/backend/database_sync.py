"""Daily database backup and one-way, atomic publication to dedicated Sheets tabs."""
import asyncio
from datetime import datetime
import logging
import os
from pathlib import Path
import sqlite3
import tempfile
from zoneinfo import ZoneInfo

from mini_app.backend.database import Database
from mini_app.backend.sheets import SheetsGateway, cell

logger = logging.getLogger(__name__)
EXPENSE_HEADERS = ('date', 'description', 'category', 'amount', 'telegram_user_id',
                   'display_name', 'transaction_id', 'created_at', 'updated_at',
                   'trip_id', 'original_amount', 'currency', 'exchange_rate', 'rate_date', 'rate_source')


class DatabaseBackup:
    def __init__(self, settings, *, retention=30):
        self.database = Database(settings)
        self.directory = Path(settings.state_dir) / 'backups'
        self.retention = retention

    def run_sync(self, today):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = self.directory / f'finance-{today.isoformat()}.sqlite3'
        if target.exists():
            return
        fd, name = tempfile.mkstemp(dir=self.directory, suffix='.tmp')
        os.close(fd)
        try:
            # SQLite's backup API includes committed WAL pages safely.
            with self.database.connection() as source:
                destination = sqlite3.connect(name)
                try:
                    source.backup(destination)
                finally:
                    destination.close()
            os.replace(name, target)
        finally:
            Path(name).unlink(missing_ok=True)
        for expired in sorted(self.directory.glob('finance-*.sqlite3'))[:-self.retention]:
            expired.unlink()


class DailyDatabaseSync:
    def __init__(self, settings, *, gateway=None):
        self.settings = settings
        self.database = Database(settings)
        self.gateway = gateway or SheetsGateway(settings)
        self.backup = DatabaseBackup(settings)
        self._lock = asyncio.Lock()
        self._last_attempt = None

    async def tick(self, now=None):
        now = now or datetime.now(ZoneInfo('Europe/Minsk'))
        today = now.astimezone(ZoneInfo('Europe/Minsk')).date()
        async with self._lock:
            # Retry failures at most every five minutes; no retry of individual writes.
            if self._last_attempt is not None and (now - self._last_attempt).total_seconds() < 300:
                return
            self._last_attempt = now
            # Never publish a fresh, empty database over a valid export.
            if await asyncio.to_thread(self.database.get_metadata, 'import_complete') != 'true':
                logger.warning('Выгрузка ожидает завершения импорта базы данных')
                return
            if self.settings.backup_enabled:
                try:
                    await asyncio.to_thread(self.backup.run_sync, today)
                except Exception:
                    logger.error('Не удалось создать резервную копию базы; повторим позже')
                    return
            if await asyncio.to_thread(self.database.get_metadata, 'sheets_sync_date') == today.isoformat():
                return
            try:
                await asyncio.to_thread(self.gateway.run, self._publish, today)
                await asyncio.to_thread(self.database.set_metadata, 'sheets_sync_date', today.isoformat())
                logger.info('Ежедневная выгрузка базы в Google Sheets завершена')
            except Exception:
                logger.error('Не удалось выгрузить базу в Google Sheets; повторим позже')

    def _publish(self, today):
        from mini_app.backend.travel import TripRepository
        TripRepository(self.settings).categories_sync()
        _, categories, transactions, trips, travel_categories = self.database.snapshot(include_travel=True)
        expense_rows = [list(EXPENSE_HEADERS)] + [[
            item.date.isoformat(), item.description, item.category, str(item.amount),
            str(item.author_id) if item.author_id is not None else '', item.author_name,
            item.transaction_id, item.created_at.isoformat() if item.created_at else '',
            item.updated_at.isoformat() if item.updated_at else '',
            item.trip_id or '', str(item.original_amount if item.original_amount is not None else item.amount),
            item.currency, str(item.exchange_rate if item.exchange_rate is not None else 1),
            item.rate_date.isoformat() if item.rate_date else item.date.isoformat(), item.rate_source or 'BYN',
        ] for item in transactions]
        category_rows = [['category', 'subcategory']]
        for category in categories:
            category_rows.extend([[category.name, child] for child in category.subcategories] or [[category.name, '']])
        trip_rows = [['trip_id', 'name', 'date_from', 'date_to', 'currency', 'completed', 'created_by']] + [
            [t.trip_id, t.name, t.date_from.isoformat(), t.date_to.isoformat(), t.currency, str(t.completed), str(t.created_by)]
            for t in trips]
        travel_rows = [['category', 'subcategory']]
        for category in travel_categories:
            travel_rows.extend([[category['name'], child] for child in category['subcategories']] or [[category['name'], '']])
        exports = [('DB Transactions', expense_rows), ('DB Categories', category_rows), ('DB Trips', trip_rows),
                   ('DB Travel Categories', travel_rows),
                   ('DB Sync', [['export_date', 'source', 'transactions'], [today.isoformat(), 'SQLite', str(len(transactions))]])]
        book = self.gateway.spreadsheet
        worksheets = {ws.title: ws for ws in book.worksheets()}
        requests = []
        for title, rows in exports:
            ws = worksheets.get(title)
            if ws is None:
                ws = book.add_worksheet(title=title, rows=max(100, len(rows)), cols=len(rows[0]))
            elif ws.row_count < len(rows) or ws.col_count < len(rows[0]):
                ws.resize(rows=max(ws.row_count, len(rows)), cols=max(ws.col_count, len(rows[0])))
            # A range rather than start clears stale tail cells in the same atomic
            # batch as replacement. Typed strings prevent formula injection.
            requests.append({'updateCells': {
                'range': {'sheetId': ws.id, 'startRowIndex': 0, 'startColumnIndex': 0,
                          'endRowIndex': ws.row_count, 'endColumnIndex': ws.col_count},
                'rows': [{'values': [cell(value) for value in row]} for row in rows],
                'fields': 'userEnteredValue',
            }})
        book.batch_update({'requests': requests})
