"""Stage 7 control examples; Google Sheets and Telegram are always fake."""
from datetime import date, datetime, timezone
from decimal import Decimal
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from backend.api import create_app
from backend.errors import RepositoryUnavailableError
from backend.models import Transaction, User, UserRole
from backend.statistics import StatisticsQuery, StatisticsService
from backend.sheets import GoogleSheetsTransactionRepository, SheetsGateway
from config import Settings
from tests.test_sheets_stage3 import FakeSpreadsheet, FakeWorksheet, EXTENDED, SETTINGS
from tests.test_users_api import FakeUserRepository


def expense(day, amount, author=None, category='Еда', name='Автор не указан'):
    return Transaction(date.fromisoformat(day), '', category, Decimal(amount), author, name)


DATA = [
    expense('2025-12-31', '100', 42, name='Старое имя'),
    expense('2026-01-01', '10.10', 42, name='Иван'),
    expense('2026-01-31', '19.90', 42, 'Транспорт', 'Иван'),
    expense('2026-01-15', '20', 43, name='Анна'),
    expense('2026-01-20', '10'),
    expense('2026-03-01', '30', 42, name='Иван'),
    expense('2026-03-31', '90', 43, 'Транспорт', 'Анна'),
    expense('2026-04-01', '999', 43, name='Анна'),
]


class StatisticsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.repository = AsyncMock()
        self.repository.list.return_value = DATA
        self.service = StatisticsService(self.repository)

    async def test_family_control_example_and_participant_metrics(self):
        result = await self.service.get(StatisticsQuery(mode='range', month_from='2026-01', month_to='2026-03'))
        self.assertEqual((result.total, result.family_total, result.count), (Decimal('180'), Decimal('180'), 6))
        self.assertEqual([(c.category, c.amount) for c in result.categories], [('Транспорт', Decimal('109.90')), ('Еда', Decimal('70.10'))])
        self.assertEqual([m.total for m in result.monthly], [60, 0, 120])
        self.assertEqual([m.change for m in result.monthly], [None, -60, 120])
        self.assertEqual([m.change_percent for m in result.monthly], [None, -100, None])
        ivan, anna, unknown = result.participants
        self.assertEqual((ivan.total, ivan.count, ivan.average, ivan.share_percent), (60, 3, 20, Decimal('33.33')))
        self.assertEqual((anna.total, anna.count, anna.average, anna.share_percent), (110, 2, 55, Decimal('61.11')))
        self.assertEqual((unknown.author_id, unknown.author_name, unknown.total, unknown.share_percent), (None, 'Автор не указан', 10, Decimal('5.56')))
        self.assertEqual([m.total for m in ivan.monthly], [30, 0, 30])
        self.assertEqual(sum(p.total for p in result.participants), result.family_total)
        self.assertEqual(sum(c.amount for c in ivan.categories), ivan.total)
        self.repository.list.assert_awaited_once()

    async def test_participant_and_unknown_filters_keep_family_denominator(self):
        for filters, expected, count in [({'author_id': 42}, 60, 3), ({'unknown_author': True}, 10, 1), ({'author_id': 999}, 0, 0)]:
            result = await self.service.get(StatisticsQuery(mode='range', month_from='2026-01', month_to='2026-03', **filters))
            self.assertEqual((result.total, result.count, result.family_total), (expected, count, 180))
            self.assertEqual(len(result.participants), 3)

    async def test_all_presets_include_current_month_and_cross_year(self):
        for count in [1, 2, 3, 6, 12]:
            result = await self.service.get(StatisticsQuery(months=count), date(2026, 1, 15))
            self.assertEqual(len(result.months), count)
            self.assertEqual(result.months[-1], '2026-01')
            self.assertEqual(result.total, 60 if count == 1 else 160)
        self.assertEqual((await self.service.get(StatisticsQuery(months=2), date(2026, 1, 15))).months, ['2025-12', '2026-01'])

    async def test_default_clock_uses_minsk(self):
        with patch('backend.statistics.datetime') as clock:
            clock.now.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)
            result = await self.service.get(StatisticsQuery())
        self.assertEqual(str(clock.now.call_args.args[0]), 'Europe/Minsk')
        self.assertEqual(result.months, ['2026-01'])

    async def test_comparison_direction_and_noncontiguous_months(self):
        for before, after, change, percent in [('2026-01', '2026-03', 60, 100), ('2026-03', '2026-01', -60, -50), ('2026-02', '2026-03', 120, None)]:
            result = await self.service.get(StatisticsQuery(mode='compare', compare_from=before, compare_to=after))
            self.assertEqual(len(result.months), 2)
            self.assertEqual((result.comparison.change, result.comparison.change_percent), (change, percent))
        filtered = await self.service.get(StatisticsQuery(mode='compare', compare_from='2026-01', compare_to='2026-03', author_id=43))
        self.assertEqual((filtered.total, filtered.comparison.change, filtered.comparison.change_percent), (110, 70, 350))

    async def test_empty_months_and_empty_ledger(self):
        result = await self.service.get(StatisticsQuery(mode='range', month_from='2027-01', month_to='2027-03'))
        self.assertEqual(result.total, 0)
        self.assertEqual(result.categories, [])
        self.assertEqual([m.total for m in result.monthly], [0, 0, 0])
        self.assertTrue(all(p.average == 0 and p.share_percent is None and p.count == 0 for p in result.participants))
        self.repository.list.return_value = []
        result = await self.service.get(StatisticsQuery(), date(2026, 1, 1))
        self.assertEqual(result.available_participants, [])
        self.assertEqual(result.participants, [])

    async def test_decimal_precision_and_average_rounding(self):
        self.repository.list.return_value = [expense('2026-01-01', str(amount), 42) for amount in ['0.1', '0.2', '0.2']]
        result = await self.service.get(StatisticsQuery(), date(2026, 1, 1))
        self.assertEqual(result.total, Decimal('0.5'))
        self.assertEqual(result.participants[0].average, Decimal('0.17'))


class StatisticsApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.book = FakeSpreadsheet(migrated=True)
        self.book.worksheet('Transactions').rows = [EXTENDED, ['2026-10-01', '', 'Еда', '0.10', 42, 'Иван']]
        self.book.worksheet('Transactions 08.2026').rows = [EXTENDED, ['2026-08-31', '', 'Транспорт', '10', 43, 'Анна']]
        self.book.sheets.append(FakeWorksheet('Transactions 09.2026', [EXTENDED, ['2026-09-01', '', 'Еда', '0.20']], 7))
        self.repository = GoogleSheetsTransactionRepository(SETTINGS, gateway=SheetsGateway(SETTINGS, spreadsheet=self.book))
        users = FakeUserRepository([User(42, 'Иван', UserRole.MEMBER, True), User(43, 'Анна', UserRole.ADMIN, True), User(44, 'Отключён', UserRole.MEMBER, False)])
        app = create_app(Settings(bot_token='test', google_sheet_id='fake', environment='test', dev_auth_enabled=True), user_repository=users, transaction_repository=self.repository)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url='http://test', headers={'X-Dev-Telegram-User-Id': '42'})

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_current_and_multiple_archives_read_without_writes(self):
        response = await self.client.get('/api/statistics', params={'mode': 'range', 'month_from': '2026-08', 'month_to': '2026-10'})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(Decimal(data['total']), Decimal('10.30'))
        self.assertEqual([Decimal(m['total']) for m in data['monthly']], [Decimal('10'), Decimal('0.20'), Decimal('0.10')])
        self.assertEqual(data['participants'][-1]['author_name'], 'Автор не указан')
        self.assertTrue(all(not ws.writes for ws in self.book.sheets))
        self.assertNotIn('chat_id', response.text)
        for user_id in ['42', '43']:
            self.assertEqual((await self.client.get('/api/statistics?months=3', headers={'X-Dev-Telegram-User-Id': user_id})).status_code, 200)

    async def test_invalid_queries_do_not_read_ledger(self):
        cases = [
            {'months': value} for value in ['0', '4', '-1', '13', 'x', '2.0']
        ] + [
            {'mode': 'range'}, {'mode': 'other'},
            {'mode': 'range', 'month_from': '2026-03', 'month_to': '2026-01'},
            {'mode': 'compare', 'compare_from': '2026-01', 'compare_to': '2026-01'},
            {'mode': 'compare', 'compare_from': '2026-01'},
            {'month_from': '2026-01'}, {'compare_to': '2026-01'},
            {'author_id': '0'}, {'author_id': '42', 'unknown_author': 'true'},
            {'unknown_author': 'oops'}, {'telegram_user_id': '42'},
        ] + [{'mode': 'range', 'month_from': value, 'month_to': '2026-03'} for value in ['0000-01', '2026-00', '2026-13', '26-01', '2026-1', '2026-01-01']]
        with patch.object(self.repository, 'list', side_effect=AssertionError('must not read')):
            for query in cases:
                with self.subTest(query=query):
                    response = await self.client.get('/api/statistics', params=query)
                    self.assertEqual(response.status_code, 422, response.text)

    async def test_no_financial_read_before_authorization(self):
        with patch.object(self.repository, 'list', side_effect=AssertionError('must not read')):
            for user_id, code in [('', 401), ('999', 403), ('44', 403)]:
                response = await self.client.get('/api/statistics', headers={'X-Dev-Telegram-User-Id': user_id})
                self.assertEqual(response.status_code, code)
                self.assertNotIn('total', response.text)

    async def test_storage_error_is_sanitized(self):
        with patch.object(self.repository, 'list', side_effect=RepositoryUnavailableError()):
            response = await self.client.get('/api/statistics')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['error']['code'], 'storage_unavailable')

    async def test_filter_unknown_author_and_reverse_comparison(self):
        response = await self.client.get('/api/statistics', params={'mode': 'compare', 'compare_from': '2026-10', 'compare_to': '2026-09', 'unknown_author': 'true'})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(Decimal(data['total']), Decimal('0.20'))
        self.assertEqual(Decimal(data['family_total']), Decimal('0.30'))
        self.assertEqual(Decimal(data['comparison']['change']), Decimal('0.20'))
        self.assertIsNone(data['comparison']['change_percent'])
