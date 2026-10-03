import unittest

from config import ConfigurationError, Settings, load_settings


class SettingsTests(unittest.TestCase):
    def test_loads_required_values_from_explicit_environment(self):
        settings = load_settings(
            environ={
                "BOT_TOKEN": "  test-bot-token  ",
                "GOOGLE_SHEET_ID": "  test-sheet-id  ",
            }
        )

        self.assertEqual(settings.bot_token, "test-bot-token")
        self.assertEqual(settings.google_sheet_id, "test-sheet-id")

    def test_reports_all_missing_required_values_without_secret_values(self):
        with self.assertRaises(ConfigurationError) as raised:
            Settings.from_mapping({"BOT_TOKEN": "", "GOOGLE_SHEET_ID": "   "})

        message = str(raised.exception)
        self.assertIn("BOT_TOKEN", message)
        self.assertIn("GOOGLE_SHEET_ID", message)

    def test_does_not_read_dotenv_when_environment_is_explicit(self):
        settings = load_settings(
            dotenv_path="file-that-must-not-be-read.env",
            environ={"BOT_TOKEN": "token", "GOOGLE_SHEET_ID": "sheet"},
        )

        self.assertEqual(settings, Settings(bot_token="token", google_sheet_id="sheet"))

    def test_development_cors_is_limited_to_local_vite(self):
        settings = Settings.from_mapping({"BOT_TOKEN": "token", "GOOGLE_SHEET_ID": "sheet"})

        self.assertEqual(
            settings.cors_origins,
            ("http://localhost:5173", "http://127.0.0.1:5173"),
        )

    def test_production_requires_https_mini_app_url(self):
        values = {
            "BOT_TOKEN": "token",
            "GOOGLE_SHEET_ID": "sheet",
            "APP_ENV": "production",
        }
        with self.assertRaises(ConfigurationError):
            Settings.from_mapping(values)

        values["MINI_APP_URL"] = "http://example.com"
        with self.assertRaises(ConfigurationError):
            Settings.from_mapping(values)

    def test_production_cors_uses_only_mini_app_origin(self):
        settings = Settings.from_mapping(
            {
                "BOT_TOKEN": "token",
                "GOOGLE_SHEET_ID": "sheet",
                "APP_ENV": "production",
                "MINI_APP_URL": "https://finance.example/app?ignored=yes",
            }
        )

        self.assertEqual(settings.cors_origins, ("https://finance.example",))

    def test_production_rejects_dev_auth(self):
        with self.assertRaises(ConfigurationError):
            Settings.from_mapping(
                {
                    "BOT_TOKEN": "token",
                    "GOOGLE_SHEET_ID": "sheet",
                    "APP_ENV": "production",
                    "MINI_APP_URL": "https://finance.example",
                    "DEV_AUTH_ENABLED": "true",
                }
            )

    def test_development_can_explicitly_enable_dev_auth(self):
        settings = Settings.from_mapping(
            {
                "BOT_TOKEN": "token",
                "GOOGLE_SHEET_ID": "sheet",
                "DEV_AUTH_ENABLED": "true",
            }
        )

        self.assertTrue(settings.dev_auth_enabled)


if __name__ == "__main__":
    unittest.main()
