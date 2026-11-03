"""Trips, historic currency conversion and report boundaries without live services."""
import asyncio
from dataclasses import asdict, replace
from datetime import date, datetime, timezone
from decimal import Decimal
import json
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx

from config import Settings
from mini_app.backend.api import create_app
from mini_app.backend.database import Database, SQLiteTransactionRepository, SQLiteUserRepository
from mini_app.backend.database_migration import import_snapshot
from mini_app.backend.database_sync import DatabaseBackup, DailyDatabaseSync
from mini_app.backend.exchange import ExchangeService
from mini_app.backend.models import Category, CurrentUser, Transaction, User, UserRole
from mini_app.backend.travel import TripRepository
from tests.test_database import ExportBook
from mini_app.backend.sheets import SheetsGateway


class TravelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.settings = Settings(bot_token='test', google_sheet_id='fake', state_dir=self.folder.name, dev_auth_enabled=True)
        self.db = Database(self.settings)
        self.users = [User(1, 'Иван', UserRole.ADMIN, True), User(2, 'Анна', UserRole.MEMBER, True), User(3, 'Олег', UserRole.MEMBER, True)]
        import_snapshot(self.db, (self.users, [Category('Продукты')], []))
        self.calls = []
        self.fx = ExchangeService(self.settings, transport=httpx.MockTransport(self.rates))
        self.app = create_app(self.settings, exchange_service=self.fx)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://test', headers={'X-Dev-Telegram-User-Id': '1'})
        self.addAsyncCleanup(self.client.aclose)
        self.repo = TripRepository(self.settings)
        self.transactions = SQLiteTransactionRepository(self.settings)

    def rates(self, request):
        self.calls.append(request)
        return httpx.Response(200, json=[{'Cur_Abbreviation': 'EUR', 'Cur_Scale': 1,
                                         'Cur_OfficialRate': '3.5', 'Date': request.url.params['ondate'] + 'T00:00:00'},
                                        {'Cur_Abbreviation': 'RUB', 'Cur_Scale': 100,
                                         'Cur_OfficialRate': '3.75', 'Date': request.url.params['ondate'] + 'T00:00:00'}])

    async def trip(self, **changes):
        response = await self.client.post('/api/trips', json={'name': 'Италия', 'date_from': '2026-03-10', 'date_to': '2026-03-20', 'currency': 'EUR', **changes})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def expense(self, **changes):
        return await self.client.post('/api/transactions', json={'request_id': str(uuid4()), 'date': '2026-03-12', 'amount': '25', 'category': 'Еда и продукты', 'description': 'Ужин', **changes})

    async def test_personal_modes_persist_and_completion_clears_every_participant(self):
        trip = await self.trip()
        for user in (1, 2):
            result = await self.client.put('/api/travel-mode', headers={'X-Dev-Telegram-User-Id': str(user)}, json={'trip_id': trip['trip_id']})
            self.assertEqual(result.status_code, 200)
        self.assertIsNone(await self.repo.active_id(3))
        self.assertEqual(await TripRepository(self.settings).active_id(2), trip['trip_id'])
        self.assertEqual((await self.client.post(f"/api/trips/{trip['trip_id']}/complete")).status_code, 200)
        self.assertIsNone(await self.repo.active_id(1))
        self.assertIsNone(await self.repo.active_id(2))
        self.assertEqual((await self.client.put('/api/travel-mode', json={'trip_id': trip['trip_id']})).status_code, 422)
        self.assertEqual((await self.expense(trip_id=trip['trip_id'])).status_code, 201)

    async def test_mode_sets_currency_and_categories_but_explicit_null_is_everyday(self):
        trip = await self.trip()
        await self.client.put('/api/travel-mode', json={'trip_id': trip['trip_id']})
        saved = await self.expense()
        self.assertEqual(saved.status_code, 201, saved.text)
        row = saved.json()
        self.assertEqual((row['trip_id'], row['currency'], row['original_amount'], row['amount']), (trip['trip_id'], 'EUR', '25', '87.50'))
        self.assertEqual(row['rate_date'], '2026-03-12')
        self.assertEqual((await self.expense(category='Продукты')).status_code, 422)
        ordinary = await self.expense(trip_id=None, category='Продукты')
        self.assertEqual(ordinary.status_code, 201, ordinary.text)
        self.assertEqual((ordinary.json()['currency'], ordinary.json()['trip_id']), ('BYN', None))
        foreign_ordinary = await self.expense(trip_id=None, category='Продукты', currency='EUR')
        self.assertEqual(foreign_ordinary.json()['amount'], '87.50')

    async def test_prepaid_tickets_trip_total_and_month_comparisons(self):
        trip = await self.trip()
        self.assertEqual((await self.expense(trip_id=trip['trip_id'], date='2026-01-15', category='Междугородний транспорт', amount='100')).status_code, 201)
        await self.expense(trip_id=trip['trip_id'], amount='200')
        await self.expense(trip_id=None, category='Продукты', date='2026-01-15', amount='50')
        await self.expense(trip_id=None, category='Продукты', amount='60')
        report = (await self.client.get(f"/api/trips/{trip['trip_id']}/report")).json()
        self.assertEqual(Decimal(report['total']), Decimal('1050'))
        self.assertEqual(report['count'], 2)
        self.assertEqual(len(report['participants']), 1)
        self.assertIsNone(await self.repo.active_id(1))
        for scope, before, after in [('all', 400, 760), ('everyday', 50, 60), ('travel', 350, 700)]:
            result = await self.client.get('/api/statistics', params={'mode': 'compare', 'compare_from': '2026-01', 'compare_to': '2026-03', 'scope': scope})
            self.assertEqual(result.status_code, 200, result.text)
            comparison = result.json()['comparison']
            self.assertEqual(Decimal(comparison['from_total']), before)
            self.assertEqual(Decimal(comparison['to_total']), after)
            if scope == 'all':
                self.assertEqual({c['category'] for c in result.json()['categories']}, {'Продукты', 'Поездки'})
        page = (await self.client.get('/api/transactions', params={'trip_id': trip['trip_id']})).json()
        self.assertEqual(page['total'], 2)

    async def test_default_statistics_and_home_exclude_trips_but_trip_report_keeps_them(self):
        from mini_app.backend.services import ExpenseService
        from mini_app.backend.database import SQLiteCategoryRepository
        from mini_app.backend.statistics import StatisticsService, StatisticsQuery
        from bot.sheet import Sheet
        from datetime import datetime
        from zoneinfo import ZoneInfo

        trip = await self.trip()
        await self.expense(trip_id=trip['trip_id'], date='2026-01-15', amount='1000')
        await self.expense(trip_id=trip['trip_id'], amount='2000')
        await self.expense(trip_id=None, category='Продукты', date='2026-01-15', amount='50')
        await self.expense(trip_id=None, category='Продукты', amount='60')
        query = {'mode': 'compare', 'compare_from': '2026-01', 'compare_to': '2026-03'}
        response = await self.client.get('/api/statistics', params=query)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(Decimal(data['total']), Decimal('110'))
        self.assertEqual(Decimal(data['family_total']), Decimal('110'))
        self.assertEqual(data['count'], 2)
        self.assertEqual({c['category'] for c in data['categories']}, {'Продукты'})
        self.assertEqual(Decimal(data['comparison']['from_total']), Decimal('50'))
        self.assertEqual(Decimal(data['comparison']['to_total']), Decimal('60'))
        self.assertEqual(Decimal(data['participants'][0]['total']), Decimal('110'))
        service = ExpenseService(self.transactions, SQLiteCategoryRepository(self.settings))
        home = await service.home(today=date(2026, 3, 15))
        self.assertEqual(home.total, Decimal('60'))
        self.assertTrue(all(t.trip_id is None for t in home.recent))
        self.assertEqual({c.category for c in home.categories}, {'Продукты'})
        today = datetime.now(ZoneInfo('Europe/Minsk')).date()
        await self.expense(trip_id=trip['trip_id'], date=today.isoformat(), amount='100')
        await self.expense(trip_id=None, category='Продукты', date=today.isoformat(), amount='10')
        api_home = (await self.client.get('/api/home')).json()
        stats = await StatisticsService(self.transactions).get(StatisticsQuery())
        self.assertEqual(Decimal(api_home['total']), stats.total)
        self.assertTrue(all(t['trip_id'] is None for t in api_home['recent']))
        bot_categories = Sheet(self.settings).get_statistics_by_categories()
        self.assertFalse(any(name == 'Поездки' or name == 'Еда и продукты' for name, amount in bot_categories))
        report = (await self.client.get(f"/api/trips/{trip['trip_id']}/report")).json()
        self.assertEqual(report['count'], 3)
        self.assertEqual(Decimal(report['total']), Decimal('10850'))

    async def test_replay_does_not_fetch_rate_or_depend_on_current_mode(self):
        trip = await self.trip()
        await self.repo.set_active(1, trip['trip_id'])
        key = str(uuid4())
        saved = await self.expense(request_id=key)
        await self.repo.set_active(1, None)
        with patch.object(self.fx, 'convert', side_effect=AssertionError('Replay must not convert')):
            replay = await self.expense(request_id=key)
        self.assertEqual(replay.json(), saved.json())
        self.assertEqual(len(await self.transactions.list()), 1)
        self.assertEqual((await self.expense(request_id=key, currency='RUB')).status_code, 409)
        self.assertEqual((await self.expense(request_id=key, trip_id=None, category='Еда и продукты')).status_code, 409)

    async def test_parallel_retries_create_one_and_detect_conflicting_originals(self):
        trip = await self.trip()
        key = str(uuid4())
        results = await asyncio.gather(*[self.expense(request_id=key, trip_id=trip['trip_id']) for _ in range(5)])
        self.assertTrue(all(r.status_code == 201 for r in results), [r.text for r in results])
        self.assertEqual(len({r.json()['transaction_id'] for r in results}), 1)
        self.assertEqual((await self.expense(request_id=key, trip_id=trip['trip_id'], amount='26')).status_code, 409)

    async def test_edit_keeps_rate_for_notes_recalculates_money_and_enforces_owner(self):
        trip = await self.trip()
        saved = (await self.expense(trip_id=trip['trip_id'])).json()
        async def edit(row, **changes):
            payload = {k: row[k] for k in ('date', 'category', 'description', 'currency', 'trip_id', 'version')}
            return await self.client.patch('/api/transactions/' + row['transaction_id'], json={**payload, 'amount': row['original_amount'], **changes})
        with patch.object(self.fx, 'convert', side_effect=AssertionError('Notes keep rate')):
            updated = await edit(saved, description='Кафе')
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()['exchange_rate'], saved['exchange_rate'])
        changed = await edit(updated.json(), amount='100', currency='RUB', date='2026-03-13')
        self.assertEqual(changed.json()['amount'], '3.75')
        self.assertEqual(changed.json()['rate_date'], '2026-03-13')
        self.assertEqual((await edit(saved, description='stale')).status_code, 409)
        self.client.headers['X-Dev-Telegram-User-Id'] = '2'
        self.assertEqual((await edit(changed.json(), description='other')).status_code, 403)

    async def test_rate_failure_never_saves_or_exposes_provider_response(self):
        trip = await self.trip()
        def fail(request):
            raise httpx.ConnectError('secret provider detail')
        self.fx.transport = httpx.MockTransport(fail)
        result = await self.expense(trip_id=trip['trip_id'])
        self.assertEqual(result.status_code, 503)
        self.assertNotIn('secret', result.text)
        self.assertEqual(await self.transactions.list(), [])

    async def test_rate_scale_rounding_cache_and_monthly_currency(self):
        self.assertEqual((await self.fx.convert(Decimal('100'), 'RUB', date(2026, 1, 10)))['amount'], Decimal('3.75'))
        self.assertEqual((await self.fx.convert(Decimal('0.11'), 'EUR', date(2026, 1, 10)))['amount'], Decimal('0.39'))
        cached = ExchangeService(self.settings, transport=httpx.MockTransport(lambda r: self.fail('Cache should survive restart')))
        self.assertEqual((await cached.rate('EUR', date(2026, 1, 10))).value, Decimal('3.5'))
        def monthly(request):
            if request.url.params['periodicity'] == '0':
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=[{'Cur_Abbreviation': 'THB', 'Cur_Scale': 100, 'Cur_OfficialRate': '9', 'Date': '2026-01-10T00:00:00'}])
        self.fx.transport = httpx.MockTransport(monthly)
        self.assertEqual((await self.fx.rate('THB', date(2026, 1, 10))).value, Decimal('.09'))

    async def test_wrong_date_or_malformed_rate_is_rejected(self):
        for row in [dict(Cur_Scale=0, Cur_OfficialRate=3, Date='2026-01-10'), dict(Cur_Scale=1, Cur_OfficialRate='NaN', Date='2026-01-10'), dict(Cur_Scale=1, Cur_OfficialRate=3, Date='2026-01-11')]:
            self.fx.transport = httpx.MockTransport(lambda req: httpx.Response(200, json=[dict(Cur_Abbreviation='EUR', **row)]))
            with self.assertRaises(Exception) as ctx:
                await self.fx.rate('EUR', date(2026, 1, 10))
            self.assertEqual(ctx.exception.status_code, 503)

    async def test_trip_permissions_validation_and_revocation(self):
        trip = await self.trip()
        self.client.headers['X-Dev-Telegram-User-Id'] = '2'
        self.assertEqual((await self.client.post(f"/api/trips/{trip['trip_id']}/complete")).status_code, 403)
        self.assertEqual((await self.client.get(f"/api/trips/{trip['trip_id']}/report")).status_code, 200)
        self.assertEqual((await self.client.post('/api/trips', json={**{k: trip[k] for k in ('name', 'date_from', 'date_to', 'currency')}, 'date_to': '2026-01-01'})).status_code, 422)
        self.assertEqual((await self.expense(trip_id='missing')).status_code, 422)
        await SQLiteUserRepository(self.settings).update(2, {'active': False})
        for path in ['/api/trips', '/api/travel-mode', f"/api/trips/{trip['trip_id']}/report"]:
            self.assertEqual((await self.client.get(path)).status_code, 403)

    async def test_legacy_payload_backup_and_export_preserve_trip_data(self):
        legacy = Transaction(date(2026, 1, 1), '', 'Продукты', Decimal('10'), transaction_id='old')
        fields = {k: v for k, v in asdict(legacy).items() if k not in {'trip_id', 'currency', 'original_amount', 'exchange_rate', 'rate_date', 'rate_source'}}
        with self.db.connection(write=True) as conn:
            conn.execute('INSERT INTO transactions VALUES (?, ?, ?, ?)', ('old', '2026-01-01', None, json.dumps(fields, default=str)))
        self.assertEqual(await self.transactions.get('old'), legacy)
        trip = await self.trip()
        saved = await self.expense(trip_id=trip['trip_id'])
        await self.repo.set_active(1, trip['trip_id'])
        backup = DatabaseBackup(self.settings)
        backup.run_sync(date(2026, 4, 1))
        with sqlite3.connect(backup.directory / 'finance-2026-04-01.sqlite3') as restored:
            self.assertEqual(restored.execute('SELECT COUNT(*) FROM trips').fetchone()[0], 1)
            self.assertEqual(restored.execute('SELECT trip_id FROM travel_preferences WHERE user_id=1').fetchone()[0], trip['trip_id'])
        book = ExportBook()
        sync = DailyDatabaseSync(self.settings, gateway=SheetsGateway(self.settings, spreadsheet=book))
        await sync.tick(datetime(2026, 4, 2, tzinfo=timezone.utc))
        self.assertTrue({'DB Trips', 'DB Travel Categories'} <= {ws.title for ws in book.sheets})
        exported = str(book.batches)
        self.assertIn(trip['trip_id'], exported)
        self.assertIn('original_amount', exported)
        self.assertIn('87.50', exported)

    async def test_bot_uses_same_mode_rates_and_idempotent_save_after_lost_response(self):
        from aiogram.fsm.context import FSMContext
        from aiogram.fsm.storage.base import StorageKey
        from aiogram.fsm.storage.memory import MemoryStorage
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from bot.handlers import expenses
        from bot.sheet import Sheet
        from mini_app.backend.errors import RepositoryUnavailableError

        trip = await self.trip()
        await self.repo.set_active(1, trip['trip_id'])
        sheet = Sheet(self.settings)
        storage = MemoryStorage()
        state = FSMContext(storage, StorageKey(bot_id=1, chat_id=1, user_id=1))
        author = CurrentUser.from_user(self.users[0])
        message = SimpleNamespace(text='Проживание', answer=AsyncMock())
        with patch.object(expenses, 'authorize_message', AsyncMock(return_value=author)), patch.object(expenses, 'Sheet', return_value=sheet), patch('bot.keyboards.user.Sheet', return_value=sheet), patch('bot.sheet.ExchangeService', return_value=self.fx):
            await expenses.process_category(message, state)
            data = await state.get_data()
            self.assertEqual((data['trip_id'], data['currency']), (trip['trip_id'], 'EUR'))
            message.text = '100 RUB'
            await expenses.process_amount(message, state)
            original = sheet.add_transaction
            def lost(*args, **kwargs):
                original(*args, **kwargs)
                raise RepositoryUnavailableError()
            message.text = 'Отель'
            with patch.object(sheet, 'add_transaction', side_effect=lost):
                await expenses.process_record_description(message, state)
            self.assertEqual((await state.get_data())['request_id'], data['request_id'])
            message.text = '/retry'
            await expenses.process_record_description(message, state)
        self.assertEqual(await state.get_data(), {})
        rows = await self.transactions.list()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].amount, rows[0].currency, rows[0].trip_id), (Decimal('3.75'), 'RUB', trip['trip_id']))
        await storage.close()


if __name__ == '__main__':
    unittest.main()
