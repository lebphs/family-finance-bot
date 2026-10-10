"""Validation of Telegram Mini App initialization data."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Callable
from urllib.parse import parse_qsl

from mini_app.backend.models import VerifiedTelegramIdentity


class InitDataError(ValueError):
    """Raised when Mini App initialization data cannot be trusted."""


class TelegramInitDataVerifier:
    def __init__(
        self,
        bot_token: str,
        *,
        max_age_seconds: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._bot_token = bot_token
        self._max_age_seconds = max_age_seconds
        self._clock = clock

    def verify(self, init_data: str) -> VerifiedTelegramIdentity:
        if not init_data:
            raise InitDataError("Отсутствуют данные Telegram")

        try:
            pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
        except ValueError as error:
            raise InitDataError("Некорректные данные Telegram") from error

        if len({key for key, _value in pairs}) != len(pairs):
            raise InitDataError("Параметры Telegram не должны повторяться")
        values = dict(pairs)
        received_hash = values.pop("hash", "")
        if not received_hash:
            raise InitDataError("Отсутствует подпись Telegram")

        data_check_string = "\n".join(
            f"{key}={value}" for key, value in sorted(values.items())
        )
        secret_key = hmac.new(
            b"WebAppData",
            self._bot_token.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        expected_hash = hmac.new(
            secret_key,
            data_check_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected_hash, received_hash):
            raise InitDataError("Неверная подпись Telegram")

        try:
            auth_date = int(values["auth_date"])
        except (KeyError, TypeError, ValueError) as error:
            raise InitDataError("Некорректная дата авторизации Telegram") from error

        age = int(self._clock()) - auth_date
        if age < -30 or age > self._max_age_seconds:
            raise InitDataError("Данные авторизации Telegram просрочены")

        try:
            user_data = json.loads(values["user"])
            telegram_user_id = int(user_data["id"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise InitDataError("Некорректный пользователь Telegram") from error
        if telegram_user_id <= 0:
            raise InitDataError("Некорректный пользователь Telegram")

        return VerifiedTelegramIdentity(telegram_user_id=telegram_user_id)
