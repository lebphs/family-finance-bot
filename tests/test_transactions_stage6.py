"""Transaction management against fake Sheets and verified dev identities."""
import asyncio
from datetime import date
from unittest.mock import patch
import unittest
from uuid import uuid4

import httpx

from mini_app.backend.api import create_app
from mini_app.backend.models import User, UserRole
from mini_app.backend.migration import migrate
from mini_app.backend.sheets import SheetsGateway, GoogleSheetsCategoryRepository, GoogleSheetsTransactionRepository
from config import Settings
from tests.test_sheets_stage3 import FakeSpreadsheet, SETTINGS
from tests.test_users_api import FakeUserRepository


class TransactionManagementTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.book = FakeSpreadsheet()
        gateway = SheetsGateway(SETTINGS, spreadsheet=self.book)
        await migrate(gateway, apply=True)
        self.repo = GoogleSheetsTransactionRepository(SETTINGS, gateway=gateway)
        self.users = FakeUserRepository([User(42, 'Иван', UserRole.MEMBER, True),
                                        User(43, 'Анна', UserRole.MEMBER, True),
                                        User(1, 'Админ', UserRole.ADMIN, True),
                                        User(44, 'Отключён', UserRole.MEMBER, False)])
        app = create_app(Settings(bot_token='test', google_sheet_id='fake', environment='test', dev_auth_enabled=True),
                         user_repository=self.users, transaction_repository=self.repo,
                         category_repository=GoogleSheetsCategoryRepository(SETTINGS, gateway=gateway))
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                       base_url='http://test', headers={'X-Dev-Telegram-User-Id': '42'})
        self.input = {'date': '2026-10-04', 'amount': '10.20', 'category': 'Еда', 'description': 'Магазин'}
        self.own = await self.create()
        self.other = await self.create(user='43', description='Кафе')

    async def asyncTearDown(self):
        await self.client.aclose()

    async def create(self, user='42', **changes):
        response = await self.client.post('/api/transactions', json={**self.input, **changes, 'request_id': str(uuid4())},
                                          headers={'X-Dev-Telegram-User-Id': user})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def edit(self, item, user='42', **changes):
        return await self.client.patch('/api/transactions/' + item['transaction_id'],
                                       json={**self.input, 'version': item['version'], **changes},
                                       headers={'X-Dev-Telegram-User-Id': user})

    async def delete(self, item, user='42'):
        return await self.client.delete('/api/transactions/' + item['transaction_id'], params={'version': item['version']},
                                        headers={'X-Dev-Telegram-User-Id': user})

    async def test_order_pagination_archive_filters_and_search(self):
        await self.repo.rotate(date(2026, 11, 1))
        newer = await self.create(date='2026-11-02', category='Транспорт', description='Такси')
        first = (await self.client.get('/api/transactions', params={'limit': 2})).json()
        self.assertEqual(first['total'], 5)
        self.assertEqual(first['items'][0]['transaction_id'], newer['transaction_id'])
        second = (await self.client.get('/api/transactions', params={'limit': 2, 'offset': first['next_offset']})).json()
        third = (await self.client.get('/api/transactions', params={'limit': 2, 'offset': second['next_offset']})).json()
        ids = [item['transaction_id'] for page in [first, second, third] for item in page['items']]
        self.assertEqual(len(set(ids)), 5)
        self.assertIsNone(third['next_offset'])
        result = (await self.client.get('/api/transactions', params={'date_from': '2026-10-01', 'date_to': '2026-10-31',
                          'category': 'Еда', 'author_id': 43, 'search': 'КАФ'})).json()
        self.assertEqual([t['transaction_id'] for t in result['items']], [self.other['transaction_id']])
        unknown = (await self.client.get('/api/transactions', params={'unknown_author': 'true'})).json()
        self.assertEqual(unknown['total'], 2)
        self.assertTrue(all(t['author_name'] == 'Автор не указан' for t in unknown['items']))
        self.assertEqual((await self.client.get('/api/transactions', params={'search': 'нет такого текста'})).json()['total'], 0)
        self.assertEqual((await self.client.get('/api/transactions', params={'offset': 100})).json()['items'], [])

    async def test_author_options_are_public_and_include_unknown(self):
        people = (await self.client.get('/api/transactions/participants')).json()
        self.assertEqual({p['author_id'] for p in people}, {42, 43, None})
        self.assertTrue(all(set(p) == {'author_id', 'author_name'} for p in people))
        self.book.worksheet('Transactions 08.2026').rows[1][2] = 'Старая категория'
        self.assertIn('Старая категория', (await self.client.get('/api/transactions/categories')).json())

    async def test_owner_can_edit_and_delete_archive_by_id_preserving_metadata(self):
        await self.repo.rotate(date(2026, 11, 1))
        changed = await self.edit(self.own, amount='12.34', category='Транспорт', date='2026-09-30', description='=без формулы')
        self.assertEqual(changed.status_code, 200, changed.text)
        data = changed.json()
        self.assertNotEqual(data['version'], self.own['version'])
        for key in ['transaction_id', 'author_id', 'author_name', 'created_at']:
            self.assertEqual(data[key], self.own[key])
        persisted = (await self.client.get('/api/transactions/' + data['transaction_id'])).json()
        self.assertEqual(data, persisted)
        self.assertEqual(self.book.worksheet('Transactions 10.2026').rows[2][1], '=без формулы')
        self.assertEqual((await self.delete(data)).status_code, 204)
        self.assertEqual((await self.client.get('/api/transactions/' + data['transaction_id'])).status_code, 404)

    async def test_member_denied_foreign_and_legacy_admin_can_manage_both(self):
        legacy = next(t for t in (await self.client.get('/api/transactions')).json()['items'] if t['author_id'] is None)
        for item in [self.other, legacy]:
            self.assertEqual((await self.edit(item)).status_code, 403)
            self.assertEqual((await self.delete(item)).status_code, 403)
            edited = await self.edit(item, user='1', description='Правка админа')
            self.assertEqual(edited.status_code, 200, edited.text)
            self.assertEqual(edited.json()['author_id'], item['author_id'])
            self.assertEqual((await self.delete(edited.json(), user='1')).status_code, 204)

    async def test_stale_edit_delete_and_deleted_record(self):
        edited = await self.edit(self.own, amount='11')
        self.assertEqual(edited.status_code, 200)
        for response in [await self.edit(self.own, amount='13'), await self.delete(self.own)]:
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(response.json()['error']['code'], 'transaction_changed')
        self.assertEqual((await self.delete(edited.json())).status_code, 204)
        self.assertEqual((await self.edit(edited.json())).status_code, 404)
        self.assertEqual((await self.delete(edited.json())).status_code, 404)

    async def test_legacy_external_edit_is_detected_without_timestamp(self):
        legacy = next(t for t in (await self.client.get('/api/transactions')).json()['items'] if t['author_id'] is None)
        for ws in self.book.worksheets():
            for row in ws.rows[1:]:
                if len(row) > 6 and row[6] == legacy['transaction_id']:
                    row[1] = 'Изменено в Sheets'
        self.assertEqual((await self.edit(legacy, user='1')).status_code, 409)
        self.assertEqual((await self.delete(legacy, user='1')).status_code, 409)

    async def test_repository_checks_version_inside_writer_lock(self):
        original_get = self.repo.get
        barrier = asyncio.Event()
        count = 0
        async def simultaneous_get(identifier):
            nonlocal count
            value = await original_get(identifier)
            count += 1
            if count == 2:
                barrier.set()
            await asyncio.wait_for(barrier.wait(), 5)
            return value
        with patch.object(self.repo, 'get', side_effect=simultaneous_get):
            responses = await asyncio.gather(self.edit(self.own, amount='11'), self.edit(self.own, amount='12'))
        self.assertEqual(sorted(r.status_code for r in responses), [200, 409])

    async def test_invalid_requests_never_write(self):
        before = await self.repo.list()
        for changes in [{'amount': '0'}, {'amount': 'NaN'}, {'amount': '1.234'}, {'amount': True}, {'date': '2026-02-30'},
                        {'date': '04.10.2026'}, {'category': 'Неизвестно'}, {'author_id': 43}, {'transaction_id': 'fake'},
                        {'created_at': 'fake'}, {'description': 'x' * 501}, {'request_id': str(uuid4())}, {'version': 'bad'}]:
            with self.subTest(changes=changes):
                self.assertEqual((await self.edit(self.own, **changes)).status_code, 422)
        for params in [{'date_from': '2026-11-01', 'date_to': '2026-10-01'}, {'date_from': '2026-1-01'},
                       {'limit': 101}, {'limit': 0}, {'offset': -1}, {'author_id': 0}, {'author_id': 42, 'unknown_author': 'true'}, {'unexpected': '1'}]:
            with self.subTest(params=params):
                self.assertEqual((await self.client.get('/api/transactions', params=params)).status_code, 422)
        self.assertEqual((await self.client.delete('/api/transactions/' + self.own['transaction_id'])).status_code, 422)
        self.assertEqual(await self.repo.list(), before)

    async def test_unauthorized_all_endpoints_never_read_ledger(self):
        with patch.object(self.repo, 'list', side_effect=AssertionError('must not read')), patch.object(self.repo, 'get', side_effect=AssertionError('must not read')):
            for identity, status in [('', 401), ('999', 403), ('44', 403)]:
                for method, path, kwargs in [('GET', '/api/transactions', {}), ('GET', '/api/transactions/participants', {}),
                    ('GET', '/api/transactions/categories', {}), ('GET', '/api/transactions/x', {}),
                    ('PATCH', '/api/transactions/x', {'json': {**self.input, 'version': self.own['version']}}),
                    ('DELETE', '/api/transactions/x', {'params': {'version': self.own['version']}})]:
                    self.assertEqual((await self.client.request(method, path, headers={'X-Dev-Telegram-User-Id': identity}, **kwargs)).status_code, status)

    async def test_storage_failure_does_not_change_row_or_expose_details(self):
        self.book.worksheet('Transactions').fail = True
        failed = await self.edit(self.own, amount='12')
        self.assertEqual(failed.status_code, 503)
        self.assertNotIn('must-not-leak', failed.text)
        self.book.worksheet('Transactions').fail = False
        self.assertEqual((await self.edit(self.own, amount='12')).status_code, 200)

    async def test_lost_update_response_requires_refresh_before_retry(self):
        ws = self.book.worksheet('Transactions')
        original = ws.batch_update
        def lost_response(*args, **kwargs):
            original(*args, **kwargs)
            raise TimeoutError('secret')
        with patch.object(ws, 'batch_update', side_effect=lost_response):
            response = await self.edit(self.own, amount='18')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('secret', response.text)
        self.assertEqual((await self.edit(self.own, amount='18')).status_code, 409)
        current = (await self.client.get('/api/transactions/' + self.own['transaction_id'])).json()
        self.assertEqual(float(current['amount']), 18)
        self.assertEqual((await self.edit(current, amount='19')).status_code, 200)

    async def test_lost_delete_response_is_reconciled_as_missing(self):
        ws = self.book.worksheet('Transactions')
        original = ws.delete_rows
        def lost_response(*args):
            original(*args)
            raise TimeoutError('secret')
        with patch.object(ws, 'delete_rows', side_effect=lost_response):
            self.assertEqual((await self.delete(self.own)).status_code, 503)
        self.assertEqual((await self.delete(self.own)).status_code, 404)
        self.assertEqual((await self.client.get('/api/transactions/' + self.own['transaction_id'])).status_code, 404)
        self.assertIsNotNone(await self.repo.get(self.other['transaction_id']))

    async def test_deletion_between_authorization_and_mutation_returns_not_found(self):
        original_update = self.repo.update
        async def deleted_before_update(identifier, changes, **kwargs):
            await self.repo.delete(identifier)
            return await original_update(identifier, changes, **kwargs)
        with patch.object(self.repo, 'update', side_effect=deleted_before_update):
            self.assertEqual((await self.edit(self.own, amount='17')).status_code, 404)

    async def test_existing_category_removed_from_preferences_can_be_retained(self):
        self.book.worksheet('Preferences').rows = [['Транспорт', '']]
        result = await self.edit(self.own, description='Только описание')
        self.assertEqual(result.status_code, 200)


if __name__ == '__main__':
    unittest.main()
