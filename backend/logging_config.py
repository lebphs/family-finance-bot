"""Logging configuration which removes common credential shapes."""

from __future__ import annotations

import logging
import re


_SECRET_PATTERNS = (
    re.compile(r"(?i)(BOT_TOKEN|GOOGLE_SHEET_ID)(\s*[=:]\s*)([^\s&]+)"),
    re.compile(r"(?is)-----BEGIN PRIVATE KEY-----.*?-----END PRIVATE KEY-----"),
    re.compile(r"(?i)(Authorization)(\s*[=:]\s*)([^\r\n]+)"),
    re.compile(r"(?i)(initData)(\s*[=:]\s*)(\S+)"),
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b"),
)


class SensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for pattern in _SECRET_PATTERNS:
            if pattern.groups >= 3:
                message = pattern.sub(r"\1\2[REDACTED]", message)
            else:
                message = pattern.sub("[REDACTED]", message)
        # Third-party tracebacks can contain URLs, credentials or request bodies.
        # Keep the sanitized event; never format arbitrary exception text.
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        record.msg = message
        record.args = ()
        return True


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(SensitiveDataFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)
