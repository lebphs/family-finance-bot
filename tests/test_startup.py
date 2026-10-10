import unittest
from unittest.mock import patch

from config import ConfigurationError, Settings
from mini_app import __main__ as main


class StartupTests(unittest.TestCase):
    def test_invalid_configuration_stops_before_app_is_created(self):
        with (
            patch.object(main, "load_settings", side_effect=ConfigurationError("invalid")),
            patch.object(main, "create_app") as create_app,
        ):
            with self.assertRaises(ConfigurationError):
                main.run()

        create_app.assert_not_called()

    def test_valid_configuration_runs_asgi_server_without_external_services(self):
        settings = Settings(bot_token="test-token", google_sheet_id="test-sheet")
        app = object()
        with (
            patch.object(main, "load_settings", return_value=settings),
            patch.object(main, "configure_logging") as configure_logging,
            patch.object(main, "create_app", return_value=app) as create_app,
            patch.object(main.uvicorn, "run") as uvicorn_run,
        ):
            main.run()

        configure_logging.assert_called_once_with()
        create_app.assert_called_once_with(settings)
        uvicorn_run.assert_called_once_with(
            app,
            host="0.0.0.0",
            port=8000,
            log_config=None,
        )


if __name__ == "__main__":
    unittest.main()
