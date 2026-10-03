import logging
import unittest

from backend.logging_config import SensitiveDataFilter


class LoggingTests(unittest.TestCase):
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
