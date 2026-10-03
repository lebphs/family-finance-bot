import asyncio
import hashlib
import hmac
import json
import time
import unittest
from urllib.parse import urlencode

import httpx

from backend.api import create_app
from backend.models import User, UserRole
from backend.repositories import UserAlreadyExistsError
from config import Settings


class FakeUserRepository:
    def __init__(self, users: list[User]) -> None:
        self.users = {user.telegram_user_id: user for user in users}

    async def get(self, telegram_user_id: int) -> User | None:
        return self.users.get(telegram_user_id)

    async def list(self) -> list[User]:
        return list(self.users.values())

    async def create(self, user: User) -> User:
        if user.telegram_user_id in self.users:
            raise UserAlreadyExistsError
        self.users[user.telegram_user_id] = user
        return user

    async def update(self, telegram_user_id: int, changes: dict[str, object]) -> User | None:
        from dataclasses import replace

        user = self.users.get(telegram_user_id)
        if user is None:
            return None
        user = replace(user, **changes)
        self.users[telegram_user_id] = user
        return user


class UsersApiTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakeUserRepository(
            [
                User(1, "Администратор", UserRole.ADMIN, True),
                User(2, "Участник", UserRole.MEMBER, True),
                User(3, "Отключён", UserRole.MEMBER, False),
            ]
        )
        self.app = create_app(
            Settings(
                bot_token="token",
                google_sheet_id="sheet",
                environment="test",
                dev_auth_enabled=True,
            ),
            user_repository=self.repository,
        )

    def request(self, method: str, path: str, *, user_id: int | None = None, **kwargs):
        headers = dict(kwargs.pop("headers", {}))
        if user_id is not None:
            headers["X-Dev-Telegram-User-Id"] = str(user_id)

        async def send():
            transport = httpx.ASGITransport(app=self.app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, path, headers=headers, **kwargs)

        return asyncio.run(send())

    def test_missing_auth_is_rejected(self):
        response = self.request("GET", "/api/me")

        self.assertEqual(response.status_code, 401)

    def test_valid_telegram_init_data_authenticates_user(self):
        values = {
            "auth_date": str(int(time.time())),
            "user": json.dumps({"id": 2}, separators=(",", ":")),
        }
        check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
        secret = hmac.new(b"WebAppData", b"token", hashlib.sha256).digest()
        values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()

        response = self.request(
            "GET",
            "/api/me",
            headers={"Authorization": f"tma {urlencode(values)}"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["telegram_user_id"], 2)

    def test_allowed_user_gets_identity_and_role_from_repository(self):
        response = self.request("GET", "/api/me", user_id=2)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"telegram_user_id": 2, "display_name": "Участник", "role": "member"},
        )

    def test_unknown_user_is_denied(self):
        response = self.request("GET", "/api/me", user_id=999)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "access_denied")

    def test_inactive_user_is_denied(self):
        response = self.request("GET", "/api/me", user_id=3)

        self.assertEqual(response.status_code, 403)

    def test_member_cannot_manage_users(self):
        response = self.request("GET", "/api/admin/users", user_id=2)

        self.assertEqual(response.status_code, 403)

    def test_admin_can_list_create_and_disable_users(self):
        listed = self.request("GET", "/api/admin/users", user_id=1)
        created = self.request(
            "POST",
            "/api/admin/users",
            user_id=1,
            json={
                "telegram_user_id": 4,
                "display_name": "Новый участник",
                "role": "member",
            },
        )
        updated = self.request(
            "PATCH",
            "/api/admin/users/4",
            user_id=1,
            json={"active": False, "role": "admin"},
        )

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 3)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(updated.status_code, 200)
        self.assertFalse(updated.json()["active"])
        self.assertEqual(updated.json()["role"], "admin")

    def test_client_cannot_supply_identity_or_role_to_me_endpoint(self):
        response = self.request(
            "GET",
            "/api/me?telegram_user_id=1&role=admin",
            user_id=2,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["telegram_user_id"], 2)
        self.assertEqual(response.json()["role"], "member")

    def test_dev_header_is_ignored_in_production_even_for_direct_settings(self):
        app = create_app(
            Settings(
                bot_token="token",
                google_sheet_id="sheet",
                environment="production",
                mini_app_url="https://finance.example",
                dev_auth_enabled=True,
            ),
            user_repository=self.repository,
        )

        async def send():
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get(
                    "/api/me",
                    headers={"X-Dev-Telegram-User-Id": "1"},
                )

        response = asyncio.run(send())
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
