"""Stage 8: no real Telegram, Google Sheets or production configuration."""
import asyncio
from dataclasses import replace
from datetime import date, datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from backend.api import create_app
from backend.backups import SheetsBackup
from backend.models import User, UserRole
from backend.reminders import DeliveryLedger, ReminderDispatcher
from backend.repositories import GoogleSheetsUserRepository, USERS_HEADERS, _user_to_row
from backend.sheets import SheetsGateway
from config import Settings
from scheduler_bot import AsyncSchedulerBot
from tests.test_users_api import FakeUserRepository
from tests.test_sheets_stage3 import FakeWorksheet

SETTINGS = Settings(bot_token="123456789:abcdefghijklmnopqrstuvwxyzABCDE", google_sheet_id="fake8", environment="test", dev_auth_enabled=True)


class RemindersApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.users = FakeUserRepository([User(1, "Первый", UserRole.MEMBER, True), User(2, "Второй", UserRole.MEMBER, True), User(3, "Отключён", UserRole.MEMBER, False)])
        self.app = create_app(SETTINGS, user_repository=self.users)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app, raise_app_exceptions=False), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_defaults_and_individual_settings_survive_new_app(self):
        headers = {"X-Dev-Telegram-User-Id": "1"}
        defaults = (await self.client.get('/api/reminders', headers=headers)).json()
        self.assertEqual(defaults, dict(reminder_enabled=False, reminder_time='22:00', reminder_days=list(range(7)), timezone='Europe/Minsk', chat_connected=False))
        payload = dict(reminder_enabled=True, reminder_time='09:15', reminder_days=[4, 0], timezone='Europe/Berlin')
        response = await self.client.put('/api/reminders', headers=headers, json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['reminder_days'], [0, 4])
        self.assertFalse(self.users.users[2].reminder_enabled)
        new_app = create_app(SETTINGS, user_repository=self.users)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=new_app), base_url='http://test') as client:
            read = await client.get('/api/reminders', headers=headers)
        self.assertEqual(read.json(), response.json())
        payload['reminder_enabled'] = False
        self.assertEqual((await self.client.put('/api/reminders', headers=headers, json=payload)).status_code, 200)
        self.assertFalse(self.users.users[1].reminder_enabled)

    async def test_validation_never_changes_settings_or_chat(self):
        payload = dict(reminder_enabled=True, reminder_time='22:00', reminder_days=[0], timezone='Europe/Minsk')
        original = self.users.users[1]
        for changes in [dict(reminder_time='24:00'), dict(reminder_time='9:00'), dict(reminder_days=[]), dict(reminder_days=[7]), dict(reminder_days=[0,0]), dict(reminder_days=[True]), dict(timezone='invalid/zone'), dict(reminder_enabled='yes'), dict(chat_id=55), dict(telegram_user_id=2), dict(role='admin')]:
            response = await self.client.put('/api/reminders', headers={'X-Dev-Telegram-User-Id':'1'}, json={**payload, **changes})
            self.assertEqual(response.status_code, 422, changes)
            self.assertEqual(self.users.users[1], original)

    async def test_unknown_inactive_and_unauthenticated_cannot_read_or_write(self):
        for headers in [{}, {'X-Dev-Telegram-User-Id':'3'}, {'X-Dev-Telegram-User-Id':'999'}]:
            for method in ['GET', 'PUT']:
                response = await self.client.request(method, '/api/reminders', headers=headers, **({'json':{}} if method == 'PUT' else {}))
                self.assertIn(response.status_code, [401,403])


class DispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = str(Path(self.directory.name)/'deliveries.sqlite3')
        self.user = User(1, 'Участник', UserRole.MEMBER, True, True, '22:00', '0,1,2,3,4,5,6', 'Europe/Minsk', 1)
        self.users = FakeUserRepository([self.user])
        self.bot = AsyncMock()
        self.now = datetime(2026,10,4,19,0,tzinfo=timezone.utc)

    def dispatcher(self):
        return ReminderDispatcher(self.users, DeliveryLedger(self.path), self.bot)

    async def test_restart_catchup_and_concurrent_ticks_do_not_duplicate(self):
        await asyncio.gather(self.dispatcher().tick(self.now), self.dispatcher().tick(self.now))
        await self.dispatcher().tick(self.now.replace(hour=20))
        self.bot.send_message.assert_awaited_once()
        await self.dispatcher().tick(self.now.replace(day=5))
        self.assertEqual(self.bot.send_message.await_count, 2)

    async def test_timezone_weekdays_and_inactive_disabled_unconnected(self):
        for changes in [dict(active=False), dict(reminder_enabled=False), dict(chat_id=None), dict(reminder_days='0'), dict(timezone='America/New_York'), dict(reminder_time='23:00')]:
            self.users.users[1] = replace(self.user, **changes)
            await self.dispatcher().tick(self.now)
        self.bot.send_message.assert_not_awaited()
        self.users.users[1] = self.user
        await self.dispatcher().tick(self.now)
        self.bot.send_message.assert_awaited_once()

    async def test_failure_keeps_subscription_and_next_day_is_attempted(self):
        self.bot.send_message.side_effect = TimeoutError('BOT_TOKEN=do-not-log')
        with self.assertLogs('backend.reminders', level='ERROR') as logs:
            await self.dispatcher().tick(self.now)
        self.assertNotIn('do-not-log', str(logs.output))
        self.assertEqual(self.users.users[1], self.user)
        self.bot.send_message.side_effect = None
        await self.dispatcher().tick(self.now)
        self.assertEqual(self.bot.send_message.await_count, 1)
        await self.dispatcher().tick(self.now.replace(day=5))
        self.assertEqual(self.bot.send_message.await_count, 2)

    async def test_dst_fallback_does_not_duplicate_local_day(self):
        self.users.users[1] = replace(self.user, timezone='Europe/Berlin', reminder_time='02:30')
        await self.dispatcher().tick(datetime(2026,10,25,0,30,tzinfo=timezone.utc))
        await self.dispatcher().tick(datetime(2026,10,25,1,30,tzinfo=timezone.utc))
        self.bot.send_message.assert_awaited_once()

    async def test_invalid_schedule_does_not_stop_other_users(self):
        self.users.users[2] = replace(self.user, telegram_user_id=2, timezone='invalid')
        await self.dispatcher().tick(self.now)
        self.bot.send_message.assert_awaited_once()


class BotCommandsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.users = FakeUserRepository([User(1,'Участник',UserRole.MEMBER,True), User(2,'Отключён',UserRole.MEMBER,False)])
        self.bot = AsyncSchedulerBot.__new__(AsyncSchedulerBot)
        self.bot.users = self.users
        self.bot.settings = SETTINGS
        self.message = AsyncMock()
        self.message.from_user.id = 1
        self.message.chat.id = 1
        self.message.chat.type = 'private'

    async def test_router_initialization_has_no_external_io(self):
        with tempfile.TemporaryDirectory() as folder:
            configured = AsyncSchedulerBot(SETTINGS.bot_token, settings=replace(SETTINGS, state_dir=folder), users=self.users)
            self.assertIs(configured.users, self.users)
            self.assertFalse((Path(folder) / "reminders.sqlite3").exists())
            self.assertGreaterEqual(len(configured.dp.message.handlers), 3)
            await configured.bot.session.close()

    async def test_connect_and_subscribe_only_self_private_chat(self):
        await self.bot.connect_chat(self.message)
        self.assertEqual(self.users.users[1].chat_id, 1)
        self.message.text = '/subscribe 09:30'
        await self.bot.subscribe_chat(self.message)
        self.assertTrue(self.users.users[1].reminder_enabled)
        self.assertEqual(self.users.users[1].reminder_time, '09:30')
        await self.bot.unsubscribe_chat(self.message)
        self.assertFalse(self.users.users[1].reminder_enabled)

    async def test_invalid_commands_unknown_inactive_and_groups_never_write(self):
        for text in ['/subscribe 24:00','/subscribe invalid','/subscribe 10:00 extra']:
            self.message.text = text
            await self.bot.subscribe_chat(self.message)
        self.assertIsNone(self.users.users[1].chat_id)
        for identity in [2,999]:
            self.message.from_user.id = identity
            await self.bot.connect_chat(self.message)
        self.message.from_user.id = 1
        self.message.chat.type = 'group'
        await self.bot.connect_chat(self.message)
        self.assertIsNone(self.users.users[1].chat_id)


class ProductionTests(unittest.IsolatedAsyncioTestCase):
    async def test_static_assets_without_exposing_state_and_production_auth_cors(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'index.html').write_text('<html>Mini App</html>')
            (root/'assets').mkdir()
            (root/'assets'/'app.js').write_text('public')
            settings = replace(SETTINGS, environment='production', dev_auth_enabled=False, mini_app_url='https://finance.example', frontend_dir=folder)
            app = create_app(settings, user_repository=FakeUserRepository([]))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                self.assertEqual((await client.get('/')).status_code,200)
                self.assertEqual((await client.get('/assets/app.js')).text,'public')
                for path in ['/api/reminders','/api/me']:
                    self.assertEqual((await client.get(path,headers={'X-Dev-Telegram-User-Id':'1'})).status_code,401)
                for path in ['/.env','/google-credentials.json','/data/reminders.sqlite3','/assets/../config.py','/api/unknown']:
                    self.assertEqual((await client.get(path)).status_code,404)
                for origin, expected in [('https://finance.example',True),('http://localhost:5173',False),('https://attacker.example',False)]:
                    result = await client.options('/api/me',headers={'Origin':origin,'Access-Control-Request-Method':'GET'})
                    self.assertEqual('access-control-allow-origin' in result.headers, expected)

    async def test_backup_is_daily_atomic_retained_and_preserves_formulas(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            sheet = FakeWorksheet('Main', [['=SUM(D2:D9)']], 1)
            gateway = SheetsGateway(SETTINGS,spreadsheet=SimpleNamespace(worksheets=lambda:[sheet]))
            backup = SheetsBackup(gateway,folder,retention=2)
            for day in [1,2,3,3]:
                await backup.run(date(2026,10,day))
            files = sorted((Path(folder)/'backups').glob('*.json'))
            self.assertEqual(len(files),2)
            data = json.loads(files[-1].read_text())
            self.assertEqual(data['worksheets'][0]['formulas'],[['=SUM(D2:D9)']])
            self.assertEqual(len(sheet.threads),6) # two reads per daily backup
            self.assertFalse(list((Path(folder)/'backups').glob('*.tmp')))

    async def test_production_docker_copies_only_public_frontend_inputs(self):
        root = Path(__file__).resolve().parents[1]
        dockerfile = (root / "Dockerfile").read_text()
        self.assertIn("npm ci", dockerfile)
        self.assertIn("npm run build", dockerfile)
        self.assertIn("COPY --from=frontend /build/dist ./frontend/dist", dockerfile)
        self.assertNotIn("COPY . .", dockerfile)
        self.assertNotIn("COPY frontend/ ./", dockerfile)
        self.assertIn("USER appuser", dockerfile)
        self.assertIn("finance-data:/app/data", (root / "docker-compose.yaml").read_text())

    async def test_platform_port_and_backup_configuration_are_validated(self):
        from config import ConfigurationError
        values = {"BOT_TOKEN":"test", "GOOGLE_SHEET_ID":"test", "API_PORT":"8000", "PORT":"9000", "BACKUP_ENABLED":"false"}
        settings = Settings.from_mapping(values)
        self.assertEqual(settings.api_port, 9000)
        self.assertFalse(settings.backup_enabled)
        with self.assertRaises(ConfigurationError):
            Settings.from_mapping({**values, "BACKUP_ENABLED":"maybe"})
        with self.assertRaises(ConfigurationError):
            Settings.from_mapping({**values, "APP_ENV":"production", "MINI_APP_URL":"https://name:password@finance.example"})

    async def test_credentials_path_is_loaded_without_reading_secret_at_import(self):
        settings = Settings.from_mapping({"BOT_TOKEN":"test", "GOOGLE_SHEET_ID":"test",
            "GOOGLE_APPLICATION_CREDENTIALS":"/run/secrets/google.json", "STATE_DIR":"/data"})
        self.assertEqual(settings.state_dir, "/data")
        with patch("gspread.service_account") as account:
            gateway = SheetsGateway(settings)
            account.assert_not_called()
            gateway.spreadsheet
            account.assert_called_once_with(filename="/run/secrets/google.json")

    async def test_gspread_numericising_never_corrupts_comma_separated_weekdays(self):
        from types import SimpleNamespace
        from gspread.utils import numericise

        class NumericisingWorksheet(FakeWorksheet):
            def get_all_records(self, **kwargs):
                records = super().get_all_records(**kwargs)
                if kwargs.get("numericise_ignore") != ["all"]:
                    return [{key: numericise(str(value)) for key, value in record.items()} for record in records]
                return records

        user = User(1, "Участник", UserRole.MEMBER, True)
        sheet = NumericisingWorksheet("Users", [list(USERS_HEADERS), _user_to_row(user)], 1)
        book = SimpleNamespace(worksheet=lambda _: sheet)
        repo = GoogleSheetsUserRepository(SETTINGS, gateway=SheetsGateway(SETTINGS, spreadsheet=book))
        self.assertEqual(sheet.get_all_records()[0]["reminder_days"], 123456)
        self.assertEqual((await repo.get(1)).reminder_days, "0,1,2,3,4,5,6")
        updated = await repo.update(1, {"display_name": "Новое имя"})
        self.assertEqual(updated.reminder_days, "0,1,2,3,4,5,6")
        await repo.create(User(2, "Второй", UserRole.MEMBER, True))
        self.assertEqual((await repo.get(2)).reminder_days, "0,1,2,3,4,5,6")

    async def test_users_sheet_settings_are_persistent_without_schema_change(self):
        from types import SimpleNamespace
        sheet = FakeWorksheet('Users',[list(USERS_HEADERS),_user_to_row(User(1,'Участник',UserRole.MEMBER,True))],1)
        book = SimpleNamespace(worksheet=lambda _:sheet)
        repo = GoogleSheetsUserRepository(SETTINGS,gateway=SheetsGateway(SETTINGS,spreadsheet=book))
        await repo.update(1,dict(reminder_enabled=True,reminder_time='08:00',reminder_days='0,4',timezone='Europe/Berlin',chat_id=1))
        restarted = GoogleSheetsUserRepository(SETTINGS,gateway=SheetsGateway(SETTINGS,spreadsheet=book))
        user = await restarted.get(1)
        self.assertTrue(user.reminder_enabled)
        self.assertEqual((user.reminder_time,user.reminder_days,user.timezone,user.chat_id),('08:00','0,4','Europe/Berlin',1))
        self.assertEqual(tuple(sheet.rows[0]),USERS_HEADERS)
