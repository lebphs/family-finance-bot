import logging
import unittest

from mini_app.backend.logging_config import SensitiveDataFilter


class LoggingTests(unittest.TestCase):
    def test_exception_and_authorization_private_key_are_not_logged(self):
        try:
            raise RuntimeError("private-exception-value")
        except RuntimeError:
            import sys
            record = logging.LogRecord("test", logging.ERROR, __file__, 1,
                "Authorization=tma signed-secret\n-----BEGIN PRIVATE KEY-----private-secret-----END PRIVATE KEY-----", (), sys.exc_info())
        SensitiveDataFilter().filter(record)
        rendered = logging.Formatter().format(record)
        for secret in ["signed-secret", "private-secret", "private-exception-value"]:
            self.assertNotIn(secret, rendered)

    def test_sensitive_values_are_redacted(self):
        record = logging.LogRecord(
            "test",
            logging.INFO,
            __file__,
            1,
            "BOT_TOKEN=%s initData=%s",
            (
                "123456789:abcdefghijklmnopqrstuvwxyzABCDE",
                "query_id=secret&user=private&hash=signed",
            ),
            None,
        )

        SensitiveDataFilter().filter(record)
        message = record.getMessage()

        self.assertNotIn("abcdefghijklmnopqrstuvwxyzABCDE", message)
        self.assertNotIn("query_id", message)
        self.assertNotIn("private", message)
        self.assertEqual(message, "BOT_TOKEN=[REDACTED] initData=[REDACTED]")


if __name__ == "__main__":
    unittest.main()
