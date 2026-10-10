"""Stage 3 tests: fake Sheets storage, no Telegram or Google connections."""
import asyncio
from copy import deepcopy
from datetime import date
from decimal import Decimal
import importlib
import threading
import unittest
from unittest.mock import patch, Mock

import httpx
import gspread

from mini_app.backend.api import create_app
from mini_app.backend.errors import RepositoryError, RepositorySchemaError, RepositoryUnavailableError
from mini_app.backend.migration import migrate
from mini_app.backend.models import CurrentUser, User, UserRole
from mini_app.backend.repositories import GoogleSheetsUserRepository, USERS_HEADERS
from mini_app.backend.sheets import (
    GoogleSheetsCategoryRepository, GoogleSheetsTransactionRepository,
    SheetsGateway, TRANSACTION_HEADERS,
)
from config import Settings

SETTINGS = Settings(bot_token="token", google_sheet_id="fake-stage-three")
HEADERS = ["Дата", "Описание", "Категория", "Сумма"]
EXTENDED = HEADERS + list(TRANSACTION_HEADERS)
LEGACY = ["2026-09-15", "=текст", "Еда", "12,50"]


class FakeWorksheet:
    def __init__(self, title, rows, identifier, cols=9):
        self.title = title
        self.rows = deepcopy(rows)
        self.id = identifier
        self.col_count = cols
        self.formats = {"A2": "date", "D2": "currency"}
        self.writes = []
        self.threads = []
        self.fail = False

    def _read(self):
        self.threads.append(threading.get_ident())

    def get(self, range_name):
        self._read()
        return deepcopy(self.rows)

    def get_all_values(self, **kwargs):
        self._read()
        return deepcopy(self.rows)

    def row_values(self, index):
        self._read()
        return list(self.rows[index - 1]) if len(self.rows) >= index else []

    def get_all_records(self, **kwargs):
        self._read()
        return [dict(zip(self.rows[0], row)) for row in self.rows[1:]]

    def resize(self, *, cols):
        self.col_count = cols
        self.writes.append(("resize", cols))

    def update(self, range_name, values, **kwargs):
        self.batch_update([{"range": range_name, "values": values}], **kwargs)

    def batch_update(self, data, **kwargs):
        if self.fail:
            raise TimeoutError("must-not-leak")
        self.writes.extend(deepcopy(data))
        for update in data:
            import re
            match = re.match(r"([A-Z]+)([0-9]+)", update["range"])
            col = ord(match[1]) - ord("A")
            index = int(match[2]) - 1
            while len(self.rows) <= index:
                self.rows.append([])
            for values in update["values"]:
                row = self.rows[index]
                row.extend([""] * max(0, col + len(values) - len(row)))
                row[col:col + len(values)] = values
                index += 1

    def append_row(self, row, **kwargs):
        self.rows.append(deepcopy(row))

    def delete_rows(self, index):
        self.writes.append(("delete", index))
        del self.rows[index - 1]


class FakeSpreadsheet:
    def __init__(self, *, migrated=False):
        self.sheets = [
            FakeWorksheet("Main", [["formula"]], 1),
            FakeWorksheet("Preferences", [
                ["", "ignored"], ["Еда", "Магазин"], ["", "Кафе"],
                [], ["Транспорт", ""], ["Еда", "Магазин"],
            ], 2),
            FakeWorksheet("Transactions", [EXTENDED if migrated else HEADERS, LEGACY], 3,
                          cols=9 if migrated else 4),
            FakeWorksheet("Transactions 08.2026", [EXTENDED if migrated else HEADERS,
                                                  ["2026-08-01", "", "Еда", 5]], 4,
                          cols=9 if migrated else 4),
            FakeWorksheet("Transactions invalid", [["unused"]], 5),
        ]
        self.batches = []
        if migrated:
            self.sheets.append(FakeWorksheet("Users", [list(USERS_HEADERS)], 6))

    def worksheets(self):
        return list(self.sheets)

    def worksheet(self, title):
        for ws in self.sheets:
            if ws.title == title:
                return ws
        raise gspread.exceptions.WorksheetNotFound(title)

    def add_worksheet(self, *, title, rows, cols):
        sheet = FakeWorksheet(title, [], max(ws.id for ws in self.sheets) + 1, cols)
        self.sheets.append(sheet)
        return sheet

    def batch_update(self, body):
        self.batches.append(deepcopy(body))
        by_id = {ws.id: ws for ws in self.sheets}
        for request in body["requests"]:
            if "duplicateSheet" in request:
                spec = request["duplicateSheet"]
                source = by_id[spec["sourceSheetId"]]
                archived = self.add_worksheet(title=spec["newSheetName"], rows=1000, cols=source.col_count)
                archived.rows = deepcopy(source.rows)
                archived.formats = deepcopy(source.formats)
            elif "insertDimension" in request:
                spec = request["insertDimension"]["range"]
                by_id[spec["sheetId"]].rows.insert(spec["startIndex"], [])
            elif "updateCells" in request:
                spec = request["updateCells"]
                if "start" in spec:
                    ws = by_id[spec["start"]["sheetId"]]
                    values = spec["rows"][0]["values"]
                    ws.rows[spec["start"]["rowIndex"]] = [
                        next(iter(value["userEnteredValue"].values())) for value in values
                    ]
                else:
                    area = spec["range"]
                    ws = by_id[area["sheetId"]]
                    for row in ws.rows[area["startRowIndex"]:]:
                        row[:9] = [""] * min(9, len(row))


class SheetsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.book = FakeSpreadsheet()
        self.gateway = SheetsGateway(SETTINGS, spreadsheet=self.book)
        self.transactions = GoogleSheetsTransactionRepository(SETTINGS, gateway=self.gateway)
        self.categories = GoogleSheetsCategoryRepository(SETTINGS, gateway=self.gateway)

    async def prepare(self):
        await migrate(self.gateway, apply=True)

    async def test_categories_and_continuation_subcategories(self):
        categories = await self.categories.list()
        self.assertEqual([(c.name, c.subcategories) for c in categories],
                         [("Еда", ("Магазин", "Кафе")), ("Транспорт", ())])

    async def test_reads_current_and_valid_archives_with_unknown_authors(self):
        transactions = await self.transactions.list()
        self.assertEqual(len(transactions), 2)
        self.assertEqual(transactions[0].amount, Decimal("12.50"))
        self.assertEqual(transactions[1].date, date(2026, 8, 1))
        self.assertIsNone(transactions[0].author_id)
        self.assertIsNone(transactions[0].transaction_id)
        self.assertEqual(transactions[0].author_name, "Автор не указан")

    async def test_dated_legacy_note_without_amount_is_not_an_expense(self):
        archived = self.book.worksheet("Transactions 08.2026")
        archived.rows.append(["2026-08-02", "Заметка", "Еда", "", "", "", "legacy-note-id"])
        self.assertEqual(len(await self.transactions.list()), 2)
        self.assertIsNone(await self.transactions.get("legacy-note-id"))
        report = await migrate(self.gateway)
        self.assertEqual(report.missing_ids, 2)

    async def test_new_transaction_has_author_stable_id_and_timestamps(self):
        await self.prepare()
        author = CurrentUser(77, "Участник", UserRole.MEMBER)
        created = await self.transactions.create(
            date=date(2026, 10, 3), description="=1+1", category="Еда",
            amount=Decimal("7.25"), author=author,
        )
        stored = await self.transactions.get(created.transaction_id)
        self.assertEqual(stored, created)
        self.assertEqual(stored.author_id, 77)
        self.assertEqual(stored.author_name, "Участник")
        self.assertIsNotNone(stored.created_at)
        self.assertEqual(stored.created_at, stored.updated_at)
        row = self.book.worksheet("Transactions").rows[1]
        self.assertEqual(row[1], "=1+1")
        self.assertEqual(self.book.batches[-1]["requests"][1]["updateCells"]["rows"][0]["values"][1],
                         {"userEnteredValue": {"stringValue": "=1+1"}})
        self.assertEqual(len(row), 9)

    async def test_lookup_update_delete_by_id_survive_row_insertion(self):
        await self.prepare()
        old = (await self.transactions.list())[0]
        await self.transactions.create(date=date(2026, 10, 3), description="новая", category="Еда",
                                       amount=Decimal("1"), author=CurrentUser(1, "А", UserRole.ADMIN))
        updated = await self.transactions.update(old.transaction_id, {"amount": Decimal("30")})
        self.assertEqual(updated.amount, Decimal("30"))
        self.assertIsNone(updated.author_id)
        self.assertEqual(updated.transaction_id, old.transaction_id)
        self.assertEqual(self.book.worksheet("Transactions").rows[2][4:6], ["", ""])
        self.assertTrue(await self.transactions.delete(old.transaction_id))
        self.assertIsNone(await self.transactions.get(old.transaction_id))
        self.assertFalse(await self.transactions.delete(old.transaction_id))
        self.assertIsNone(await self.transactions.update("missing", {"description": "none"}))
        self.assertEqual(len(await self.transactions.list()), 2)

    async def test_update_and_delete_archived_id(self):
        await self.prepare()
        archived = (await self.transactions.list())[1]
        updated = await self.transactions.update(archived.transaction_id,
                                                {"date": date(2026, 8, 2), "description": "changed"})
        self.assertEqual((await self.transactions.get(archived.transaction_id)).date, updated.date)
        self.assertTrue(await self.transactions.delete(archived.transaction_id))
        self.assertEqual(len(self.book.worksheet("Transactions 08.2026").rows), 1)

    async def test_cannot_overwrite_author_id_or_creation_timestamp(self):
        await self.prepare()
        old = (await self.transactions.list())[0]
        before = deepcopy(self.book.worksheet("Transactions").rows)
        with self.assertRaises(RepositorySchemaError):
            await self.transactions.update(old.transaction_id, {"author_id": 123})
        self.assertEqual(self.book.worksheet("Transactions").rows, before)

    async def test_invalid_amount_does_not_write(self):
        await self.prepare()
        for amount in ("0", "-1", "NaN", "Infinity", "1E999"):
            with self.assertRaises(RepositorySchemaError):
                await self.transactions.create(
                    date=date(2026, 10, 3), description="", category="Еда",
                    amount=Decimal(amount), author=CurrentUser(1, "А", UserRole.ADMIN),
                )
        self.assertEqual(self.book.batches, [])

    async def test_new_rows_require_migrated_schema(self):
        with self.assertRaises(RepositorySchemaError):
            await self.transactions.create(
                date=date(2026, 10, 3), description="", category="Еда",
                amount=Decimal(1), author=CurrentUser(1, "А", UserRole.ADMIN),
            )
        self.assertEqual(self.book.batches, [])

    async def test_dry_run_has_no_writes(self):
        snapshot = deepcopy([(ws.title, ws.rows, ws.col_count, ws.formats) for ws in self.book.sheets])
        report = await migrate(self.gateway)
        self.assertEqual(report.missing_ids, 2)
        self.assertTrue(report.create_users)
        self.assertEqual(snapshot, [(ws.title, ws.rows, ws.col_count, ws.formats) for ws in self.book.sheets])
        self.assertTrue(all(not ws.writes for ws in self.book.sheets))

    async def test_migration_preserves_a_to_d_formulas_formats_and_is_idempotent(self):
        current = self.book.worksheet("Transactions")
        current.rows[1][3] = "=SUM(1,2)"
        before = deepcopy([row[:4] for row in current.rows])
        formats = deepcopy(current.formats)
        await self.prepare()
        self.assertEqual([row[:4] for row in current.rows], before)
        self.assertEqual(current.formats, formats)
        self.assertEqual(current.rows[1][4:6], ["", ""])
        snapshot = deepcopy([(ws.title, ws.rows) for ws in self.book.sheets])
        report = await migrate(self.gateway, apply=True)
        self.assertEqual((report.missing_ids, report.headers_to_extend, report.create_users), (0, 0, False))
        self.assertEqual(snapshot, [(ws.title, ws.rows) for ws in self.book.sheets])
        self.assertEqual(self.book.worksheet("Users").rows, [list(USERS_HEADERS)])

    async def test_duplicate_ids_and_conflicting_headers_fail_before_writes(self):
        current = self.book.worksheet("Transactions")
        archive = self.book.worksheet("Transactions 08.2026")
        current.rows[1] += ["", "", "duplicate"]
        archive.rows[1] += ["", "", "duplicate"]
        with self.assertRaises(RepositorySchemaError):
            await migrate(self.gateway, apply=True)
        self.assertTrue(all(not ws.writes for ws in self.book.sheets))
        with self.assertRaises(RepositorySchemaError):
            await self.transactions.list()
        archive.rows[1][6] = "different"
        archive.rows[0] += ["unexpected"]
        with self.assertRaises(RepositorySchemaError):
            await migrate(self.gateway, apply=True)
        self.assertNotIn("Users", {ws.title for ws in self.book.sheets})

    async def test_partial_migration_can_resume_without_changing_existing_ids(self):
        archive = self.book.worksheet("Transactions 08.2026")
        archive.fail = True
        with self.assertRaises(RepositoryUnavailableError):
            await migrate(self.gateway, apply=True)
        assigned = self.book.worksheet("Transactions").rows[1][6]
        archive.fail = False
        await self.prepare()
        self.assertEqual(self.book.worksheet("Transactions").rows[1][6], assigned)
        self.assertEqual((await migrate(self.gateway)).missing_ids, 0)

    async def test_users_schema_is_verified_and_users_can_be_created(self):
        await self.prepare()
        repository = GoogleSheetsUserRepository(SETTINGS, gateway=self.gateway)
        created = await repository.create(User(90, "=имя", UserRole.ADMIN, True))
        self.assertEqual(await repository.get(90), created)
        self.assertFalse((await repository.update(90, {"active": False})).active)
        self.book.worksheet("Users").rows[0][2] = "wrong"
        with self.assertRaises(RepositorySchemaError):
            await repository.get(90)

    async def test_users_schema_conflict_prevents_migration_writes(self):
        users = self.book.add_worksheet(title="Users", rows=10, cols=9)
        users.rows = [["wrong"]]
        with self.assertRaises(RepositorySchemaError):
            await migrate(self.gateway, apply=True)
        self.assertTrue(all(not ws.writes for ws in self.book.sheets))

    async def test_rotation_is_atomic_idempotent_and_keeps_formula_target(self):
        await self.prepare()
        current = self.book.worksheet("Transactions")
        before = deepcopy(current.rows)
        current_id = current.id
        main_before = deepcopy(self.book.worksheet("Main").rows)
        self.assertFalse(await self.transactions.rotate(date(2026, 10, 3)))
        self.assertTrue(await self.transactions.rotate(date(2026, 10, 1)))
        self.assertFalse(await self.transactions.rotate(date(2026, 10, 1)))
        self.assertEqual(self.book.worksheet("Transactions 09.2026").rows, before)
        self.assertEqual(current.id, current_id)
        self.assertEqual(current.rows[0], EXTENDED)
        self.assertEqual(self.book.worksheet("Main").rows, main_before)
        self.assertEqual(len(self.book.batches), 1)
        self.assertEqual(len(await self.transactions.list()), 2)
        await self.transactions.create(
            date=date(2026, 10, 1), description="", category="Еда", amount=Decimal(1),
            author=CurrentUser(1, "А", UserRole.ADMIN),
        )
        self.assertFalse(await self.transactions.rotate(date(2026, 10, 1)))
        self.assertEqual(len(await self.transactions.list()), 3)

    async def test_rotation_failure_leaves_current_available_and_retries_next_time(self):
        await self.prepare()
        original = self.book.batch_update
        self.book.batch_update = Mock(side_effect=TimeoutError("secret"))
        before = deepcopy(self.book.worksheet("Transactions").rows)
        with self.assertRaises(RepositoryUnavailableError):
            await self.transactions.rotate(date(2026, 10, 1))
        self.book.batch_update.assert_called_once()
        self.assertEqual(self.book.worksheet("Transactions").rows, before)
        self.book.batch_update = original
        self.assertTrue(await self.transactions.rotate(date(2026, 10, 1)))

    async def test_io_uses_worker_threads_and_event_loop_remains_responsive(self):
        main_thread = threading.get_ident()
        entered, release = threading.Event(), threading.Event()
        original = self.book.worksheet("Preferences").get

        def blocking_read(range_name):
            entered.set()
            if not release.wait(2):
                raise TimeoutError()
            return original(range_name)

        self.book.worksheet("Preferences").get = blocking_read
        task = asyncio.create_task(self.categories.list())
        try:
            for _ in range(100):
                if entered.is_set():
                    break
                await asyncio.sleep(0.01)
            self.assertTrue(entered.is_set())
            # If the call blocked the loop this coroutine could not reach here.
            self.assertFalse(task.done())
        finally:
            release.set()
        await task
        self.assertTrue(all(thread != main_thread for thread in self.book.worksheet("Preferences").threads))

    async def test_read_retries_transient_errors_but_write_is_never_retried(self):
        original = self.book.worksheet("Preferences").get
        read = Mock(side_effect=[TimeoutError("secret"), original("B4:C43")])
        self.book.worksheet("Preferences").get = read
        with patch("mini_app.backend.sheets.time.sleep"):
            self.assertEqual(len(await self.categories.list()), 2)
        self.assertEqual(read.call_count, 2)
        self.book.worksheet("Preferences").get = original
        await self.prepare()
        write = Mock(side_effect=TimeoutError("secret"))
        self.book.batch_update = write
        with self.assertRaises(RepositoryUnavailableError) as caught:
            await self.transactions.create(
                date=date(2026, 10, 3), description="", category="Еда", amount=Decimal(1),
                author=CurrentUser(1, "А", UserRole.ADMIN),
            )
        self.assertEqual(write.call_count, 1)
        self.assertNotIn("secret", str(caught.exception))

    async def test_permanent_api_error_is_sanitized_and_not_retried(self):
        response = Mock(status_code=403)
        response.json.return_value = {"error": {"message": "secret", "code": 403}}
        read = Mock(side_effect=gspread.exceptions.APIError(response))
        self.book.worksheet("Preferences").get = read
        with self.assertRaises(RepositoryError) as caught:
            await self.categories.list()
        self.assertEqual(read.call_count, 1)
        self.assertNotIn("secret", str(caught.exception))


    async def test_empty_users_sheet_can_resume_header_initialization(self):
        users = self.book.add_worksheet(title="Users", rows=1000, cols=4)
        await self.prepare()
        self.assertEqual(users.rows, [list(USERS_HEADERS)])
        self.assertEqual(users.col_count, 9)
        self.assertFalse((await migrate(self.gateway)).create_users)

    async def test_duplicate_user_keeps_application_conflict_error(self):
        from mini_app.backend.repositories import UserAlreadyExistsError
        from mini_app.backend.services import UserService
        from mini_app.backend.errors import ApiError
        await self.prepare()
        repository = GoogleSheetsUserRepository(SETTINGS, gateway=self.gateway)
        user = User(9, "А", UserRole.ADMIN, True)
        await repository.create(user)
        with self.assertRaises(UserAlreadyExistsError):
            await repository.create(user)
        with self.assertRaises(ApiError) as caught:
            await UserService(repository).create_user(user)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(len(await repository.list()), 1)

    async def test_rate_limit_read_is_retried_boundedly_and_sanitized(self):
        response = Mock(status_code=429)
        response.json.return_value = {"error": {"message": "secret", "code": 429}}
        read = Mock(side_effect=gspread.exceptions.APIError(response))
        self.book.worksheet("Preferences").get = read
        with patch("mini_app.backend.sheets.time.sleep"), self.assertRaises(RepositoryUnavailableError) as caught:
            await self.categories.list()
        self.assertEqual(read.call_count, 3)
        self.assertNotIn("secret", str(caught.exception))

    async def test_repositories_for_same_book_share_writer_lock(self):
        other = SheetsGateway(SETTINGS, spreadsheet=self.book)
        self.assertIs(other.lock, self.gateway.lock)
        await self.prepare()
        author = CurrentUser(1, "А", UserRole.ADMIN)
        second = GoogleSheetsTransactionRepository(SETTINGS, gateway=other)
        results = await asyncio.gather(*[
            (self.transactions if n % 2 else second).create(
                date=date(2026, 10, 3), description=str(n), category="Еда",
                amount=Decimal(1), author=author,
            ) for n in range(10)
        ])
        self.assertEqual(len({result.transaction_id for result in results}), 10)
        self.assertEqual(len(await self.transactions.list()), 12)

    async def test_editing_description_keeps_untouched_amount_formula(self):
        await self.prepare()
        ws = self.book.worksheet("Transactions")
        identifier = ws.rows[1][6]
        ws.rows[1][3] = "=SUM(10,2.5)"
        original_read = ws.get_all_values
        def read_computed(**kwargs):
            rows = original_read(**kwargs)
            rows[1][3] = 12.5
            return rows
        ws.get_all_values = read_computed
        await self.transactions.update(identifier, {"description": "Новое описание"})
        self.assertEqual(ws.rows[1][3], "=SUM(10,2.5)")
        self.assertEqual(ws.rows[1][1], "Новое описание")


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_storage_errors_are_reported_by_api_without_financial_or_secret_data(self):
        class UnavailableUsers:
            async def get(self, user_id):
                raise RepositoryUnavailableError()

        settings = Settings(bot_token="token", google_sheet_id="fake", dev_auth_enabled=True)
        app = create_app(settings, user_repository=UnavailableUsers())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/me", headers={"X-Dev-Telegram-User-Id": "1"})
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["error"]["code"], "storage_unavailable")

    async def test_categories_deny_unauthenticated_and_unknown_users_before_reading(self):
        class UnknownUsers:
            async def get(self, user_id):
                return None
        settings = Settings(bot_token="token", google_sheet_id="fake", dev_auth_enabled=True)
        app = create_app(settings, user_repository=UnknownUsers())
        with patch("mini_app.backend.sheets.GoogleSheetsCategoryRepository.list") as categories:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                self.assertEqual((await client.get("/api/categories")).status_code, 401)
                response = await client.get("/api/categories", headers={"X-Dev-Telegram-User-Id": "1"})
                self.assertEqual(response.status_code, 403)
            categories.assert_not_called()

    async def test_categories_authorized_and_schema_errors_have_common_api_shape(self):
        class AllowedUsers:
            async def get(self, user_id):
                return User(user_id, "А", UserRole.MEMBER, True)
        settings = Settings(bot_token="token", google_sheet_id="fake", dev_auth_enabled=True)
        app = create_app(settings, user_repository=AllowedUsers())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                     headers={"X-Dev-Telegram-User-Id": "1"}) as client:
            with patch("mini_app.backend.sheets.GoogleSheetsCategoryRepository.list", side_effect=RepositorySchemaError()):
                response = await client.get("/api/categories")
                self.assertEqual(response.status_code, 500)
                self.assertEqual(response.json()["error"]["code"], "storage_schema_error")

    async def test_imports_and_bot_construction_make_no_network_calls(self):
        with patch("gspread.service_account", side_effect=AssertionError("network")) as connect:
            import bot.handlers.expenses as expenses_handlers
            import bot.handlers.user as user_handlers
            import bot.keyboards.user as user_keyboards
            import bot.sheet as sheet_module
            from bot.scheduler_bot import AsyncSchedulerBot
            for module in (expenses_handlers, user_handlers, user_keyboards, sheet_module):
                importlib.reload(module)
            bot = AsyncSchedulerBot("123456:" + "x" * 35, settings=SETTINGS)
            await bot.bot.session.close()
            connect.assert_not_called()



class BotBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_save_keeps_fsm_data_and_uses_verified_author(self):
        from unittest.mock import AsyncMock
        from bot.handlers.expenses import process_record_description
        message = Mock(text="Описание")
        message.answer = AsyncMock()
        state = Mock()
        state.get_data = AsyncMock(return_value={"category": "Еда", "amount": "12.50"})
        state.update_data = AsyncMock()
        state.clear = AsyncMock()
        author = CurrentUser(123, "Проверенный автор", UserRole.MEMBER)
        sheet = Mock()
        sheet.add_transaction.side_effect = RepositoryUnavailableError()
        with patch("bot.handlers.expenses.authorize_message", AsyncMock(return_value=author)), patch(
            "bot.handlers.expenses.Sheet", return_value=sheet
        ), patch("bot.handlers.expenses.user.categories_keyboard", AsyncMock(return_value=None)):
            await process_record_description(message, state)
        self.assertEqual(sheet.add_transaction.call_args.kwargs["author"], author)
        state.clear.assert_not_called()
        state.update_data.assert_awaited_once_with(description="Описание")
        message.answer.assert_awaited_once()

    async def test_successful_save_clears_fsm_and_does_not_retry(self):
        from unittest.mock import AsyncMock
        from bot.handlers.expenses import process_record_description
        message = Mock(text="Без описания")
        message.answer = AsyncMock()
        state = Mock()
        state.get_data = AsyncMock(return_value={"category": "Еда", "amount": "12.50"})
        state.update_data = AsyncMock()
        state.clear = AsyncMock()
        author = CurrentUser(123, "А", UserRole.MEMBER)
        sheet = Mock()
        with patch("bot.handlers.expenses.authorize_message", AsyncMock(return_value=author)), patch(
            "bot.handlers.expenses.Sheet", return_value=sheet
        ), patch("bot.handlers.expenses.user.categories_keyboard", AsyncMock(return_value=None)):
            await process_record_description(message, state)
        sheet.add_transaction.assert_called_once()
        self.assertEqual(sheet.add_transaction.call_args.args[0][1], "")
        state.clear.assert_awaited_once()

    async def test_invalid_numeric_input_does_not_change_fsm(self):
        from unittest.mock import AsyncMock
        from bot.handlers.expenses import process_amount
        for text in ("abc", "0", "-2", "NaN", None):
            message = Mock(text=text, answer=AsyncMock())
            state = Mock(update_data=AsyncMock(), set_state=AsyncMock())
            await process_amount(message, state)
            state.update_data.assert_not_called()
            state.set_state.assert_not_called()

    async def test_legacy_shared_delete_requires_admin_and_permanent_id(self):
        from mini_app.backend.errors import ApiError
        from bot.sheet import Sheet
        book = FakeSpreadsheet()
        gateway = SheetsGateway(SETTINGS, spreadsheet=book)
        sheet = Sheet(SETTINGS, gateway=gateway)
        member = CurrentUser(1, "А", UserRole.MEMBER)
        with self.assertRaises(ApiError):
            await asyncio.to_thread(sheet.delete_last_transaction, author=member)
        admin = CurrentUser(2, "Б", UserRole.ADMIN)
        self.assertFalse(await asyncio.to_thread(sheet.delete_last_transaction, author=admin))
        await migrate(gateway, apply=True)
        self.assertTrue(await asyncio.to_thread(sheet.delete_last_transaction, author=admin))


if __name__ == "__main__":
    unittest.main()
