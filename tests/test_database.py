"""Database migration, concurrency and one-way export without external services."""
import asyncio
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import httpx

from config import Settings
from mini_app.backend.api import create_app
from mini_app.backend.database import Database, SQLiteUserRepository, SQLiteCategoryRepository, SQLiteTransactionRepository
from mini_app.backend.database_migration import import_snapshot, read_source
from mini_app.backend.database_sync import DailyDatabaseSync, DatabaseBackup
from mini_app.backend.errors import StaleTransactionError, TransactionConflictError, UserAlreadyExistsError, RepositorySchemaError
from mini_app.backend.models import Category, CurrentUser, User, UserRole, Transaction
from mini_app.backend.transaction_version import transaction_version
from mini_app.backend.sheets import SheetsGateway


class ExportWorksheet:
    def __init__(self, title, identifier, rows=100, cols=9):
        self.title, self.id = title, identifier
        self.row_count, self.col_count = rows, cols

    def resize(self, *, rows, cols):
        self.row_count, self.col_count = rows, cols


class ExportBook:
    def __init__(self):
        self.sheets = [ExportWorksheet('Main', 1), ExportWorksheet('Transactions', 2)]
        self.batches = []
        self.fail = False

    def worksheets(self):
        return self.sheets

    def add_worksheet(self, *, title, rows, cols):
        sheet = ExportWorksheet(title, len(self.sheets) + 1, rows, cols)
        self.sheets.append(sheet)
        return sheet

    def batch_update(self, batch):
        if self.fail:
            raise TimeoutError('secret must not escape')
        self.batches.append(batch)


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.settings = Settings(bot_token='token', google_sheet_id='fake-db', state_dir=self.folder.name,
                                 dev_auth_enabled=True)
        self.database = Database(self.settings)
        self.users = SQLiteUserRepository(self.settings)
        self.transactions = SQLiteTransactionRepository(self.settings)
        self.admin = User(1, 'Админ', UserRole.ADMIN, True)
        self.author = CurrentUser.from_user(self.admin)
        self.legacy = Transaction(date(2026, 9, 1), 'История', 'Еда', Decimal('123.4500'), transaction_id='legacy')

    def seed(self):
        import_snapshot(self.database, ([self.admin], [Category('Еда', ('Кафе',))], [self.legacy]))

    async def create(self, **overrides):
        values = dict(date=date(2026, 10, 1), description='=literal', category='Еда', amount=Decimal('0.10'), author=self.author)
        return await self.transactions.create(**{**values, **overrides})

    async def test_atomic_import_preserves_history_authors_and_decimal(self):
        self.seed()
        self.assertEqual(await self.transactions.get('legacy'), self.legacy)
        self.assertEqual(await self.users.get(1), self.admin)
        self.assertEqual(await SQLiteCategoryRepository(self.settings).list(), [Category('Еда', ('Кафе',))])
        with self.assertRaises(ValueError):
            self.seed()
        self.assertEqual(len(await self.transactions.list()), 1)

    async def test_failed_import_rolls_back_all_tables(self):
        with self.assertRaises(Exception):
            import_snapshot(self.database, ([self.admin, self.admin], [Category('Еда')], [self.legacy]))
        self.assertEqual(self.database.snapshot(), ([], [], []))
        self.assertIsNone(self.database.get_metadata('import_complete'))
        self.seed()

    async def test_duplicate_ids_rejected_before_import(self):
        with self.assertRaises(RepositorySchemaError):
            import_snapshot(self.database, ([self.admin], [], [self.legacy, self.legacy]))
        self.assertFalse(self.database.path.exists())

    async def test_parallel_idempotent_creates_survive_restart(self):
        items = await asyncio.gather(*[self.create(transaction_id='repeat') for _ in range(8)])
        self.assertTrue(all(item == items[0] for item in items))
        restarted = SQLiteTransactionRepository(self.settings)
        self.assertEqual(await restarted.list(), [items[0]])
        with self.assertRaises(TransactionConflictError):
            await self.create(transaction_id='repeat', amount=Decimal('2'))

    async def test_concurrent_edits_allow_only_one_version(self):
        item = await self.create()
        results = await asyncio.gather(*[
            self.transactions.update(item.transaction_id, {'description': text}, expected_version=transaction_version(item))
            for text in ('Первое', 'Второе')], return_exceptions=True)
        self.assertEqual(sum(isinstance(result, StaleTransactionError) for result in results), 1)
        with self.assertRaises(StaleTransactionError):
            await self.transactions.delete(item.transaction_id, expected_version=transaction_version(item))
        fresh = await self.transactions.get(item.transaction_id)
        self.assertTrue(await self.transactions.delete(item.transaction_id, expected_version=transaction_version(fresh)))
        self.assertFalse(await self.transactions.delete(item.transaction_id))

    async def test_user_settings_persist_and_duplicates_are_rejected(self):
        await self.users.create(self.admin)
        with self.assertRaises(UserAlreadyExistsError):
            await self.users.create(self.admin)
        await self.users.update(1, {'active': False, 'reminder_time': '20:30', 'chat_id': 100})
        restarted = SQLiteUserRepository(self.settings)
        self.assertEqual(await restarted.get(1), replace(self.admin, active=False, reminder_time='20:30', chat_id=100))
        self.assertIsNone(await self.users.update(99, {'active': False}))

    async def test_database_io_runs_in_worker_thread(self):
        import threading
        current = threading.get_ident()
        original = self.transactions._list_sync
        seen = []
        def read():
            seen.append(threading.get_ident())
            return original()
        with patch.object(self.transactions, '_list_sync', side_effect=read):
            await self.transactions.list()
        self.assertNotEqual(seen, [current])

    async def test_invalid_expenses_do_not_change_database(self):
        for amount in ('0', '-1', 'NaN', 'Infinity'):
            with self.assertRaises(ValueError):
                await self.create(amount=Decimal(amount))
        self.assertEqual(await self.transactions.list(), [])

    async def test_monthly_rotation_keeps_all_history(self):
        self.seed()
        self.assertFalse(await self.transactions.rotate(date(2026, 10, 1)))
        self.assertEqual(await self.transactions.list(), [self.legacy])

    async def test_api_uses_database_and_live_revocation_without_google(self):
        self.seed()
        app = create_app(self.settings)
        with patch('gspread.service_account', side_effect=AssertionError('network')):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test',
                                         headers={'X-Dev-Telegram-User-Id': '1'}) as client:
                self.assertEqual((await client.get('/api/categories')).status_code, 200)
                response = await client.get('/api/transactions')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['total'], 1)
                await self.users.update(1, {'active': False})
                self.assertEqual((await client.get('/api/transactions')).status_code, 403)

    async def test_backup_can_restore_decimal_users_and_history(self):
        self.seed()
        backup = DatabaseBackup(self.settings, retention=2)
        for day in range(1, 4):
            await asyncio.to_thread(backup.run_sync, date(2026, 10, day))
        files = sorted((Path(self.folder.name) / 'backups').glob('*.sqlite3'))
        self.assertEqual(len(files), 2)
        with sqlite3.connect(files[-1]) as restored:
            self.assertEqual(restored.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(restored.execute('SELECT COUNT(*) FROM users').fetchone()[0], 1)
            self.assertIn('123.4500', restored.execute('SELECT payload FROM transactions').fetchone()[0])
        self.assertFalse(list((Path(self.folder.name) / 'backups').glob('*.tmp')))

    def sync(self, book, settings=None):
        return DailyDatabaseSync(settings or self.settings, gateway=SheetsGateway(self.settings, spreadsheet=book))

    async def test_daily_export_is_atomic_typed_and_preserves_old_sheets(self):
        self.seed()
        item = await self.create()
        book = ExportBook()
        sync = self.sync(book)
        now = datetime(2026, 10, 10, 10, tzinfo=timezone.utc)
        await sync.tick(now)
        await self.sync(book).tick(now + timedelta(hours=1))
        self.assertEqual(len(book.batches), 1)
        requests = book.batches[0]['requests']
        self.assertEqual(len(requests), 3)
        self.assertTrue(all(request['updateCells']['range']['sheetId'] > 2 for request in requests))
        values = requests[0]['updateCells']['rows'][1]['values']
        self.assertEqual(values[1]['userEnteredValue'], {'stringValue': '=literal'})
        self.assertEqual(values[3]['userEnteredValue'], {'stringValue': '0.10'})
        self.assertNotIn('reminder_time', str(requests))
        self.assertEqual(self.database.get_metadata('sheets_sync_date'), '2026-10-10')
        await self.transactions.delete(item.transaction_id)
        await sync.tick(now + timedelta(days=1))
        self.assertEqual(len(book.batches), 2)
        replacement = book.batches[-1]['requests'][0]['updateCells']
        self.assertEqual(len(replacement['rows']), 2)
        self.assertGreater(replacement['range']['endRowIndex'], len(replacement['rows']))

    async def test_failed_sync_retries_and_does_not_mark_complete(self):
        self.seed()
        book = ExportBook()
        sync = self.sync(book)
        book.fail = True
        now = datetime(2026, 10, 10, 10, tzinfo=timezone.utc)
        await sync.tick(now)
        self.assertIsNone(self.database.get_metadata('sheets_sync_date'))
        book.fail = False
        await sync.tick(now + timedelta(seconds=30))
        self.assertFalse(book.batches)
        await sync.tick(now + timedelta(minutes=5))
        self.assertEqual(len(book.batches), 1)
        self.assertEqual(self.database.get_metadata('sheets_sync_date'), '2026-10-10')

    async def test_sync_without_backup_and_catches_up_after_offline_days(self):
        self.seed()
        book = ExportBook()
        sync = self.sync(book, replace(self.settings, backup_enabled=False))
        await sync.tick(datetime(2026, 10, 10, 22, tzinfo=timezone.utc))
        self.assertEqual(self.database.get_metadata('sheets_sync_date'), '2026-10-11')
        await self.sync(book).tick(datetime(2026, 10, 15, 10, tzinfo=timezone.utc))
        self.assertEqual(len(book.batches), 2)
        self.assertEqual(self.database.get_metadata('sheets_sync_date'), '2026-10-15')

    async def test_empty_database_is_never_exported(self):
        book = ExportBook()
        await self.sync(book).tick()
        self.assertFalse(book.batches)
        self.assertFalse((Path(self.folder.name) / 'backups').exists())
