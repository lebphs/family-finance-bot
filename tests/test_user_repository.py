import asyncio
import unittest
from unittest.mock import patch

from backend.models import User, UserRole
from backend.repositories import GoogleSheetsUserRepository
from config import Settings


class FakeWorksheet:
    def __init__(self):
        self.records = [
            {
                "telegram_user_id": 10,
                "display_name": "Пользователь",
                "role": "member",
                "active": "TRUE",
                "reminder_enabled": "FALSE",
                "reminder_time": "22:00",
                "reminder_days": "0,1,2,3,4,5,6",
                "timezone": "Europe/Minsk",
                "chat_id": "",
            }
        ]
        self.appended = None
        self.updated = None

    def get_all_records(self, **kwargs):
        return self.records

    def append_row(self, row, **_kwargs):
        self.appended = row

    def update(self, range_name, values, **_kwargs):
        self.updated = (range_name, values)


class UserRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_operations_use_worker_thread_and_map_users_sheet(self):
        repository = GoogleSheetsUserRepository(Settings(bot_token="token", google_sheet_id="sheet"))
        worksheet = FakeWorksheet()
        repository._worksheet = lambda: worksheet

        original_to_thread = asyncio.to_thread
        calls = []

        async def tracked_to_thread(function, *args, **kwargs):
            calls.append(args[0].__name__)
            return await original_to_thread(function, *args, **kwargs)

        with patch("backend.sheets.asyncio.to_thread", side_effect=tracked_to_thread):
            user = await repository.get(10)
            created = await repository.create(User(20, "Новый", UserRole.ADMIN, True))
            updated = await repository.update(10, {"active": False})

        self.assertEqual(user.telegram_user_id, 10)
        self.assertEqual(user.role, UserRole.MEMBER)
        self.assertEqual(created.telegram_user_id, 20)
        self.assertFalse(updated.active)
        self.assertEqual(worksheet.appended[:4], [20, "Новый", "admin", True])
        self.assertEqual(worksheet.updated[0], "A2:I2")
        self.assertEqual(calls, ["_get_sync", "_create_sync", "_update_sync"])


if __name__ == "__main__":
    unittest.main()
