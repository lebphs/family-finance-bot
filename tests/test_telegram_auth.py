import hashlib
import hmac
import json
import unittest
from urllib.parse import urlencode

from mini_app.backend.telegram_auth import InitDataError, TelegramInitDataVerifier


BOT_TOKEN = "123456:test-token"
NOW = 2_000_000_000


def signed_init_data(*, user_id: int = 42, auth_date: int = NOW) -> str:
    values = {
        "auth_date": str(auth_date),
        "query_id": "query-1",
        "user": json.dumps({"id": user_id, "first_name": "Тест"}, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


class TelegramInitDataVerifierTests(unittest.TestCase):
    def setUp(self):
        self.verifier = TelegramInitDataVerifier(
            BOT_TOKEN,
            max_age_seconds=3600,
            clock=lambda: NOW,
        )

    def test_accepts_valid_signature_and_returns_verified_user_id(self):
        identity = self.verifier.verify(signed_init_data(user_id=777))

        self.assertEqual(identity.telegram_user_id, 777)

    def test_rejects_invalid_signature(self):
        data = signed_init_data().replace("query-1", "query-2")

        with self.assertRaises(InitDataError):
            self.verifier.verify(data)

    def test_rejects_missing_signature(self):
        with self.assertRaises(InitDataError):
            self.verifier.verify("auth_date=2000000000&user=%7B%22id%22%3A42%7D")

    def test_rejects_expired_auth_date(self):
        with self.assertRaises(InitDataError):
            self.verifier.verify(signed_init_data(auth_date=NOW - 3601))

    def test_rejects_duplicate_parameters(self):
        with self.assertRaises(InitDataError):
            self.verifier.verify(signed_init_data() + "&auth_date=2000000000")


if __name__ == "__main__":
    unittest.main()
