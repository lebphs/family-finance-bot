"""Application configuration loaded from environment variables."""

from __future__ import annotations

from dataclasses import dataclass
from os import PathLike
from typing import Mapping
import os
from urllib.parse import urlsplit


class ConfigurationError(RuntimeError):
    """Raised when required application configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    google_sheet_id: str
    environment: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    mini_app_url: str | None = None
    telegram_auth_max_age_seconds: int = 86400
    dev_auth_enabled: bool = False
    google_credentials_path: str = "google-credentials.json"
    state_dir: str = "data"
    frontend_dir: str = "mini_app/frontend/dist"
    backup_enabled: bool = True

    @property
    def cors_origins(self) -> tuple[str, ...]:
        if self.environment == "production":
            assert self.mini_app_url is not None
            return (self.mini_app_url,)
        return ("http://localhost:5173", "http://127.0.0.1:5173")

    @classmethod
    def from_mapping(cls, values: Mapping[str, str | None]) -> "Settings":
        required = ("BOT_TOKEN", "GOOGLE_SHEET_ID")
        normalized = {name: (values.get(name) or "").strip() for name in required}
        missing = [name for name in required if not normalized[name]]
        if missing:
            names = ", ".join(missing)
            raise ConfigurationError(f"Не заданы обязательные переменные окружения: {names}")

        environment = (values.get("APP_ENV") or "development").strip().lower()
        if environment not in {"development", "test", "production"}:
            raise ConfigurationError("APP_ENV должен быть development, test или production")

        port_value = (values.get("PORT") or values.get("API_PORT") or "8000").strip()
        try:
            api_port = int(port_value)
        except ValueError as error:
            raise ConfigurationError("API_PORT должен быть целым числом") from error
        if not 1 <= api_port <= 65535:
            raise ConfigurationError("API_PORT должен быть в диапазоне 1..65535")

        mini_app_url = (values.get("MINI_APP_URL") or "").strip() or None
        if environment == "production":
            if mini_app_url is None:
                raise ConfigurationError("В production необходимо задать MINI_APP_URL")
            parsed_url = urlsplit(mini_app_url)
            if (parsed_url.scheme != "https" or not parsed_url.hostname
                    or parsed_url.username or parsed_url.password):
                raise ConfigurationError("MINI_APP_URL в production должен быть HTTPS-адресом")
            mini_app_url = f"{parsed_url.scheme}://{parsed_url.netloc}"

        max_age_value = (values.get("TELEGRAM_AUTH_MAX_AGE_SECONDS") or "86400").strip()
        try:
            telegram_auth_max_age_seconds = int(max_age_value)
        except ValueError as error:
            raise ConfigurationError(
                "TELEGRAM_AUTH_MAX_AGE_SECONDS должен быть целым числом"
            ) from error
        if telegram_auth_max_age_seconds <= 0:
            raise ConfigurationError("TELEGRAM_AUTH_MAX_AGE_SECONDS должен быть больше нуля")

        dev_auth_value = (values.get("DEV_AUTH_ENABLED") or "false").strip().lower()
        if dev_auth_value not in {"true", "false"}:
            raise ConfigurationError("DEV_AUTH_ENABLED должен быть true или false")
        dev_auth_enabled = dev_auth_value == "true"
        if environment == "production" and dev_auth_enabled:
            raise ConfigurationError("Dev-авторизация запрещена в production")

        backup_value = (values.get("BACKUP_ENABLED") or "true").strip().lower()
        if backup_value not in {"true", "false"}:
            raise ConfigurationError("BACKUP_ENABLED должен быть true или false")

        return cls(
            bot_token=normalized["BOT_TOKEN"],
            google_sheet_id=normalized["GOOGLE_SHEET_ID"],
            environment=environment,
            api_host=(values.get("API_HOST") or "0.0.0.0").strip(),
            api_port=api_port,
            mini_app_url=mini_app_url,
            telegram_auth_max_age_seconds=telegram_auth_max_age_seconds,
            dev_auth_enabled=dev_auth_enabled,
            google_credentials_path=(values.get("GOOGLE_APPLICATION_CREDENTIALS") or "google-credentials.json"),
            state_dir=(values.get("STATE_DIR") or "data"),
            frontend_dir=(values.get("FRONTEND_DIR") or "mini_app/frontend/dist"),
            backup_enabled=backup_value == "true",
        )


def load_settings(
    *,
    dotenv_path: str | PathLike[str] | None = None,
    environ: Mapping[str, str | None] | None = None,
) -> Settings:
    """Load .env (when requested) and validate all required settings."""

    if environ is None:
        from dotenv import load_dotenv

        load_dotenv(dotenv_path=dotenv_path)
        environ = os.environ

    return Settings.from_mapping(environ)
