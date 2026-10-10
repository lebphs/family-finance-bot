"""Request-count and cache consistency regressions; no network required."""
import asyncio
from datetime import date
from decimal import Decimal
import unittest
from unittest.mock import Mock, patch

from mini_app.backend.errors import RepositoryUnavailableError
from mini_app.backend.models import CurrentUser, UserRole
from mini_app.backend.repositories import GoogleSheetsUserRepository, USERS_HEADERS
from mini_app.backend.sheets import GoogleSheetsTransactionRepository, SheetsGateway
from tests.test_sheets_stage3 import FakeSpreadsheet, SETTINGS


class SheetsPerformanceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.book = FakeSpreadsheet(migrated=True)
        self.gateway = SheetsGateway(SETTINGS, spreadsheet=self.book)
        self.repository = GoogleSheetsTransactionRepository(SETTINGS, gateway=self.gateway)
        self.book.values_batch_get = Mock(wraps=self.book.values_batch_get)
        self.book.worksheets = Mock(wraps=self.book.worksheets)

    async def test_parallel_pages_share_one_batch_and_metadata_request(self):
        pages = await asyncio.gather(*[self.repository.list() for _ in range(6)])
        self.assertTrue(all(len(page) == 2 for page in pages))
        self.book.values_batch_get.assert_called_once_with(
            ["'Transactions'!A:I", "'Transactions 08.2026'!A:I"],
            params={"valueRenderOption": "UNFORMATTED_VALUE"},
        )
        self.book.worksheets.assert_called_once()
        pages[0].clear()
        self.assertEqual(len(await self.repository.list()), 2)

    async def test_external_edits_refresh_after_ttl(self):
        with patch("mini_app.backend.sheets.time", Mock(monotonic=Mock(return_value=100))):
            await self.repository.list()
        self.book.worksheet("Transactions").rows[1][3] = "99"
        with patch("mini_app.backend.sheets.time", Mock(monotonic=Mock(return_value=114))):
            self.assertEqual((await self.repository.list())[0].amount, Decimal("12.50"))
        with patch("mini_app.backend.sheets.time", Mock(monotonic=Mock(return_value=116))):
            self.assertEqual((await self.repository.list())[0].amount, Decimal("99"))
        self.assertEqual(self.book.values_batch_get.call_count, 2)

    async def test_bot_gateway_write_invalidates_api_snapshot(self):
        await self.repository.list()
        bot_gateway = SheetsGateway(SETTINGS, spreadsheet=self.book)
        bot = GoogleSheetsTransactionRepository(SETTINGS, gateway=bot_gateway)
        await bot.create(date=date(2026, 10, 10), description="", category="Еда",
                         amount=Decimal("3"), author=CurrentUser(1, "А", UserRole.ADMIN))
        self.assertEqual(len(await self.repository.list()), 3)
        self.assertEqual(self.book.values_batch_get.call_count, 2)

    async def test_lost_write_response_invalidates_and_never_retries(self):
        await self.repository.list()
        original = self.book.batch_update

        def lost_response(body):
            original(body)
            raise TimeoutError()

        self.book.batch_update = Mock(side_effect=lost_response)
        with self.assertRaises(RepositoryUnavailableError):
            await self.repository.create(date=date(2026, 10, 10), description="", category="Еда",
                                         amount=Decimal("3"), author=CurrentUser(1, "А", UserRole.ADMIN))
        self.book.batch_update.assert_called_once()
        self.assertEqual(len(await self.repository.list()), 3)

    async def test_users_are_checked_live_with_one_value_request(self):
        ws = self.book.worksheet("Users")
        ws.rows.append([1, "А", "member", True, False, "22:00", "0,1", "Europe/Minsk", ""])
        ws.get_all_values = Mock(wraps=ws.get_all_values)
        ws.row_values = Mock(side_effect=AssertionError("extra header request"))
        users = GoogleSheetsUserRepository(SETTINGS, gateway=self.gateway)
        self.assertTrue((await users.get(1)).active)
        ws.rows[1][3] = False
        self.assertFalse((await users.get(1)).active)
        self.assertEqual(ws.get_all_values.call_count, 2)
        self.assertEqual(ws.rows[0], list(USERS_HEADERS))

    async def test_failed_reads_do_not_poison_cache(self):
        self.book.values_batch_get.side_effect = TimeoutError()
        with patch("mini_app.backend.sheets.time.sleep"), self.assertRaises(RepositoryUnavailableError):
            await self.repository.list()
        self.book.values_batch_get.side_effect = None
        self.assertEqual(len(await self.repository.list()), 2)
        self.assertEqual(self.book.values_batch_get.call_count, 4)


class SheetsTimeoutTests(unittest.TestCase):
    def test_timeout_is_set_before_first_network_call(self):
        with patch("gspread.service_account") as service_account:
            gateway = SheetsGateway(SETTINGS)
            account = service_account.return_value
            account.open_by_key.side_effect = lambda _: self.assertEqual(account.timeout, (3.05, 10))
            gateway.spreadsheet
