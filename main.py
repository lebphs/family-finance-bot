import uvicorn

from backend.api import create_app
from backend.logging_config import configure_logging
from config import load_settings


def run() -> None:
    settings = load_settings()
    configure_logging()
    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        log_config=None,
    )


if __name__ == "__main__":
    run()
