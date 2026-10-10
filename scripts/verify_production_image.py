"""Offline smoke check. Mount this script read-only into the built Docker image.

No real token, credentials, spreadsheet, polling or external network is used.
"""
from pathlib import Path
import json
import multiprocessing
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class OfflineRuntime:
    def __init__(self, _settings):
        pass

    async def start(self):
        pass

    async def stop(self):
        pass


def serve():
    import uvicorn
    from mini_app.backend.api import create_app
    from config import Settings
    settings = Settings.from_mapping({
        "BOT_TOKEN": "offline-test-token", "GOOGLE_SHEET_ID": "offline-test-sheet",
        "APP_ENV": "production", "MINI_APP_URL": "https://finance.example",
        "DEV_AUTH_ENABLED": "false",
    })
    uvicorn.run(create_app(settings, runtime_factory=OfflineRuntime), host="127.0.0.1", port=8000, log_level="error")


def request(path, *, method="GET", headers=None):
    req = Request("http://127.0.0.1:8000" + path, method=method, headers=headers or {})
    try:
        with urlopen(req, timeout=3) as response:
            return response.status, response.headers, response.read()
    except HTTPError as response:
        return response.code, response.headers, response.read()


def verify():
    assert os.getuid() != 0, "Container must run as non-root"
    root = Path("/app")
    forbidden = [path for path in root.rglob("*") if path.is_file() and (
        path.name == ".env" or path.name.startswith(".env.") or
        path.name in {"google-credentials.json", "token.json"} or
        "credentials" in path.name.lower() and path.suffix == ".json")]
    assert not forbidden, "Secret files found (contents intentionally omitted)"
    assert not (root / "mini_app/frontend/node_modules").exists()
    assert not (root / "mini_app/frontend/src").exists()
    patterns = [re.compile(rb"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b"),
                re.compile(rb"-----BEGIN (?:RSA )?PRIVATE KEY-----"),
                re.compile(rb'"private_key"\s*:')]
    for file in (root / "mini_app/frontend/dist").rglob("*"):
        if file.is_file():
            assert not any(pattern.search(file.read_bytes()) for pattern in patterns), "Secret shape found in public asset"
    from mini_app.backend.reminders import DeliveryLedger
    import tempfile
    with tempfile.TemporaryDirectory(dir=root / "data") as folder:
        path = str(Path(folder) / "delivery.sqlite3")
        assert DeliveryLedger(path).claim(1, "2026-10-04")
        assert not DeliveryLedger(path).claim(1, "2026-10-04")
        assert Path(path).stat().st_mode & 0o777 == 0o600
    print("PASS: non-root, writable private state, durable delivery claim, no secret files/shapes")

    process = multiprocessing.Process(target=serve)
    process.start()
    try:
        for _ in range(100):
            try:
                status, _, body = request("/health")
                assert status == 200
                assert json.loads(body)["status"] == "ok"
                break
            except (URLError, ConnectionError):
                time.sleep(0.1)
        else:
            raise AssertionError("HTTP server did not start")
        status, headers, body = request("/")
        assert status == 200 and b'<div id="root">' in body
        assert headers.get("Cache-Control") == "no-store"
        assets = re.findall(rb'(?:src|href)="(/assets/[^"]+)"', body)
        assert assets
        for asset in assets:
            assert request(asset.decode())[0] == 200
        for path in ["/api/me", "/api/reminders", "/api/home", "/api/statistics"]:
            assert request(path, headers={"X-Dev-Telegram-User-Id": "1"})[0] == 401
        for path in ["/.env", "/google-credentials.json", "/data/delivery.sqlite3", "/config.py"]:
            assert request(path)[0] == 404
        for origin, allowed in [("https://finance.example", True), ("http://localhost:5173", False)]:
            _, headers, _ = request("/api/me", method="OPTIONS", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
            assert (headers.get("Access-Control-Allow-Origin") == origin) is allowed
        # Same HTTP request as Dockerfile's healthcheck.
        assert request("/health")[0] == 200
        print("PASS: Uvicorn HTTP startup, healthcheck, built mini_app/frontend/assets, denied dev auth, CORS, private paths")
    finally:
        process.terminate()
        process.join(timeout=10)
        if process.is_alive():
            process.kill()
            process.join()


if __name__ == "__main__":
    verify()
