import asyncio
import unittest

import httpx

from mini_app.backend.api import create_app
from mini_app.backend.errors import ApiError
from config import Settings


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(Settings(bot_token="token", google_sheet_id="sheet"))

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(app=self.app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(send())

    def test_healthcheck_does_not_start_external_services(self):
        response = self.request("GET", "/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"status": "ok", "service": "family-finance-backend"},
        )
        self.assertFalse(hasattr(self.app.state, "bot_runtime"))

    def test_not_found_uses_common_error_shape(self):
        response = self.request("GET", "/missing")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {"error": {"code": "http_error", "message": "Ресурс не найден"}},
        )

    def test_application_error_uses_common_error_shape(self):
        async def rejected_request() -> None:
            raise ApiError(code="access_denied", message="Нет доступа", status_code=403)

        self.app.get("/rejected")(rejected_request)
        response = self.request("GET", "/rejected")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(),
            {"error": {"code": "access_denied", "message": "Нет доступа"}},
        )

    def test_internal_error_does_not_expose_exception(self):
        async def broken_request() -> None:
            raise RuntimeError("BOT_TOKEN=must-not-leak")

        self.app.get("/broken")(broken_request)
        response = self.request("GET", "/broken")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json(),
            {"error": {"code": "internal_error", "message": "Внутренняя ошибка сервера"}},
        )
        self.assertNotIn("must-not-leak", response.text)

    def test_lifespan_starts_and_stops_bot_runtime(self):
        class FakeRuntime:
            def __init__(self, _settings: Settings) -> None:
                self.started = False
                self.stopped = False

            async def start(self) -> None:
                self.started = True

            async def stop(self) -> None:
                self.stopped = True

        instances = []

        def runtime_factory(settings: Settings) -> FakeRuntime:
            runtime = FakeRuntime(settings)
            instances.append(runtime)
            return runtime

        app = create_app(
            Settings(bot_token="token", google_sheet_id="sheet"),
            runtime_factory=runtime_factory,
        )

        async def exercise_lifespan() -> None:
            async with app.router.lifespan_context(app):
                self.assertTrue(instances[0].started)
                self.assertFalse(instances[0].stopped)

        asyncio.run(exercise_lifespan())
        self.assertTrue(instances[0].stopped)

    def test_cors_allows_local_frontend(self):
        response = self.request(
            "OPTIONS",
            "/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:5173")

    def test_cors_does_not_allow_unknown_origin(self):
        response = self.request(
            "OPTIONS",
            "/health",
            headers={
                "Origin": "https://attacker.example",
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertNotIn("access-control-allow-origin", response.headers)


if __name__ == "__main__":
    unittest.main()
