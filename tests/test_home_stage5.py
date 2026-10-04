"""Stage 5 integration checks; all Google/Telegram boundaries are fake."""
import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx

from backend.api import create_app
from backend.migration import migrate
from backend.models import CurrentUser, Transaction, User, UserRole
from backend.services import ExpenseService
from backend.sheets import GoogleSheetsCategoryRepository, GoogleSheetsTransactionRepository, SheetsGateway
from tests.test_sheets_stage3 import FakeSpreadsheet, SETTINGS
from tests.test_users_api import FakeUserRepository
from config import Settings


class HomeApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.book = FakeSpreadsheet()
        self.gateway = SheetsGateway(SETTINGS, spreadsheet=self.book)
        await migrate(self.gateway, apply=True)
        self.transactions = GoogleSheetsTransactionRepository(SETTINGS, gateway=self.gateway)
        self.categories = GoogleSheetsCategoryRepository(SETTINGS, gateway=self.gateway)
        self.users = FakeUserRepository([User(42, 'Иван', UserRole.MEMBER, True), User(43, 'Анна', UserRole.MEMBER, True), User(44, 'Отключён', UserRole.MEMBER, False)])
        self.app = create_app(Settings(bot_token='test', google_sheet_id='fake', environment='test', dev_auth_enabled=True),
                              user_repository=self.users, transaction_repository=self.transactions, category_repository=self.categories)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app, raise_app_exceptions=False), base_url='http://test', headers={'X-Dev-Telegram-User-Id': '42'})
        self.payload = {'request_id': str(uuid4()), 'date': '2026-10-03', 'amount': '23.45', 'category': 'Еда', 'description': 'Кафе'}

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_save_persists_id_author_and_refreshes_home(self):
        response = await self.client.post('/api/transactions', json=self.payload)
        self.assertEqual(response.status_code, 201, response.text)
        result = response.json()
        self.assertEqual((result['author_id'], result['author_name']), (42, 'Иван'))
        self.assertEqual((await self.transactions.get(result['transaction_id'])).amount, Decimal('23.45'))
        with patch('backend.services.datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 3, tzinfo=timezone.utc)
            home = (await self.client.get('/api/home')).json()
        self.assertIn(result['transaction_id'], [item['transaction_id'] for item in home['recent']])
        self.assertEqual(home['month'], '2026-10')

    async def test_invalid_inputs_never_write(self):
        before = len(await self.transactions.list())
        for changes in [
            {'amount': value} for value in ['0', '-1', 'NaN', 'Infinity', 'abc', '1,23', '1.234', '10000000000', True, None, '1e3']
        ] + [{'date': value} for value in ['03.10.2026', '2026-02-30', '2026-1-01', '2026-10-03T00:00:00', 1790985600]] + [
            {'category': 'Несуществующая'}, {'category': ' '}, {'description': 'x' * 501}, {'request_id': 'invalid'}, {'author_id': 43}, {'author_name': 'Подмена'}
        ]:
            with self.subTest(changes=changes):
                response = await self.client.post('/api/transactions', json={**self.payload, **changes})
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(len(await self.transactions.list()), before)

    async def test_valid_amounts(self):
        for amount in ['0.01', '1', '9999999999.99', 2.5]:
            response = await self.client.post('/api/transactions', json={**self.payload, 'amount': amount, 'request_id': str(uuid4())})
            self.assertEqual(response.status_code, 201, response.text)

    async def test_parallel_replay_and_repository_restart_are_idempotent(self):
        before = len(await self.transactions.list())
        replies = await asyncio.gather(*(self.client.post('/api/transactions', json=self.payload) for _ in range(4)))
        self.assertTrue(all(reply.status_code == 201 for reply in replies))
        self.assertEqual(len({reply.json()['transaction_id'] for reply in replies}), 1)
        self.assertEqual(len(await self.transactions.list()), before + 1)
        restarted = GoogleSheetsTransactionRepository(SETTINGS, gateway=SheetsGateway(SETTINGS, spreadsheet=self.book))
        service = ExpenseService(restarted, self.categories)
        from backend.schemas import CreateExpenseRequest
        replay = await service.create(CreateExpenseRequest(**self.payload), CurrentUser(42, 'Новое имя', UserRole.MEMBER))
        self.assertEqual(replay.transaction_id, replies[0].json()['transaction_id'])
        self.assertEqual(replay.author_name, 'Иван')
        conflict = await self.client.post('/api/transactions', json={**self.payload, 'amount': '7'})
        self.assertEqual(conflict.status_code, 409)
        other_user = await self.client.post('/api/transactions', json=self.payload, headers={'X-Dev-Telegram-User-Id': '43'})
        self.assertNotEqual(other_user.json()['transaction_id'], replay.transaction_id)
        self.assertEqual(other_user.json()['author_id'], 43)

    async def test_lost_response_after_write_retries_without_duplicate(self):
        original = self.book.batch_update
        def lost_response(body):
            original(body)
            raise TimeoutError('secret must not leak')
        before = len(await self.transactions.list())
        with patch.object(self.book, 'batch_update', side_effect=lost_response):
            response = await self.client.post('/api/transactions', json=self.payload)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('secret', response.text)
        retry = await self.client.post('/api/transactions', json=self.payload)
        self.assertEqual(retry.status_code, 201)
        self.assertEqual(len(await self.transactions.list()), before + 1)

    async def test_saved_request_replays_when_category_is_no_longer_available(self):
        saved = await self.client.post('/api/transactions', json=self.payload)
        before = len(await self.transactions.list())
        with patch.object(self.categories, 'list', side_effect=AssertionError('replay needs no categories')):
            replay = await self.client.post('/api/transactions', json=self.payload)
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay.json(), saved.json())
        self.assertEqual(len(await self.transactions.list()), before)

    async def test_concurrent_conflicting_payloads_insert_only_one_transaction(self):
        # Force both service lookups to finish before either insert. The
        # repository must detect the conflict inside its writer lock.
        barrier = asyncio.Event()
        readers = 0
        original_get = self.transactions.get

        async def simultaneous_get(transaction_id):
            nonlocal readers
            existing = await original_get(transaction_id)
            readers += 1
            if readers == 2:
                barrier.set()
            await asyncio.wait_for(barrier.wait(), timeout=5)
            return existing

        before = len(await self.transactions.list())
        with patch.object(self.transactions, 'get', side_effect=simultaneous_get):
            responses = await asyncio.gather(
                self.client.post('/api/transactions', json=self.payload),
                self.client.post('/api/transactions', json={**self.payload, 'amount': '7'}),
            )
        self.assertEqual(sorted(response.status_code for response in responses), [201, 409])
        conflict = next(response for response in responses if response.status_code == 409)
        self.assertEqual(conflict.json()['error']['code'], 'request_conflict')
        self.assertEqual(len(await self.transactions.list()), before + 1)

    async def test_failure_before_write_is_retryable(self):
        before = len(await self.transactions.list())
        with patch.object(self.book, 'batch_update', side_effect=TimeoutError()):
            self.assertEqual((await self.client.post('/api/transactions', json=self.payload)).status_code, 503)
        self.assertEqual(len(await self.transactions.list()), before)
        self.assertEqual((await self.client.post('/api/transactions', json=self.payload)).status_code, 201)

    async def test_unauthorized_requests_do_not_read_financial_data(self):
        for user_id, expected in [('999', 403), ('44', 403), ('', 401)]:
            with patch.object(self.transactions, 'list', side_effect=AssertionError('must not read')), patch.object(self.transactions, 'get', side_effect=AssertionError('must not read')):
                for method, path, kwargs in [('GET', '/api/home', {}), ('POST', '/api/transactions', {'json': self.payload})]:
                    response = await self.client.request(method, path, headers={'X-Dev-Telegram-User-Id': user_id}, **kwargs)
                    self.assertEqual(response.status_code, expected)

    async def test_replay_after_archival_rotation(self):
        saved = (await self.client.post('/api/transactions', json=self.payload)).json()
        await self.transactions.rotate(date(2026, 11, 1))
        replay = await self.client.post('/api/transactions', json=self.payload)
        self.assertEqual(replay.json()['transaction_id'], saved['transaction_id'])
        self.assertEqual(len([item for item in await self.transactions.list() if item.transaction_id == saved['transaction_id']]), 1)


class SummaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_previous_month_and_mixed_creation_timestamps(self):
        class Transactions:
            async def list(self):
                return [
                    Transaction(date(2026, 10, 1), '', 'Еда', Decimal('0.1'), transaction_id='legacy'),
                    Transaction(date(2026, 10, 1), '', 'Еда', Decimal('0.2'), transaction_id='naive', created_at=datetime(2026, 10, 1, 10)),
                    Transaction(date(2026, 10, 1), '', 'Еда', Decimal('0.3'), transaction_id='aware', created_at=datetime(2026, 10, 1, 11, tzinfo=timezone.utc)),
                ]
        service = ExpenseService(Transactions(), None)
        with patch('backend.services.datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 1, tzinfo=timezone.utc)
            clock.min = datetime.min
            home = await service.home()
            self.assertEqual(str(clock.now.call_args.args[0]), 'Europe/Minsk')
        self.assertEqual(home.total, Decimal('0.6'))
        self.assertEqual(home.change, Decimal('0.6'))
        self.assertIsNone(home.change_percent)
        self.assertEqual([item.transaction_id for item in home.recent], ['aware', 'naive', 'legacy'])

    async def test_totals_boundaries_recent_and_zero_previous(self):
        class Transactions:
            async def list(self):
                return [Transaction(date.fromisoformat(day), '', category, Decimal(amount)) for day, category, amount in [
                    ('2025-12-31', 'Еда', '100'), ('2026-01-01', 'Еда', '10.10'), ('2026-01-31', 'Еда', '0.20'),
                    ('2026-01-05', 'Транспорт', '39.70'), ('2026-02-01', 'Еда', '999'), ('2025-11-30', 'Еда', '555')]]
        service = ExpenseService(Transactions(), None)
        home = await service.home(date(2026, 1, 3))
        self.assertEqual((home.total, home.previous_total, home.change, home.change_percent), (Decimal('50'), Decimal('100'), Decimal('-50'), Decimal('-50')))
        self.assertEqual([(item.category, item.amount) for item in home.categories], [('Транспорт', Decimal('39.70')), ('Еда', Decimal('10.30'))])
        self.assertEqual(len(home.recent), 5)
        self.assertEqual(home.recent[0].date, date(2026, 2, 1))
        self.assertEqual(home.recent[0].author_name, 'Автор не указан')
        empty = await service.home(date(2027, 1, 1))
        self.assertEqual(empty.total, 0)
        self.assertIsNone(empty.change_percent)
        self.assertEqual(empty.categories, [])
        growth = await service.home(date(2026, 2, 1))
        self.assertEqual(growth.change_percent, Decimal('1898.00'))
