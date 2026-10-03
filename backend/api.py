"""FastAPI application factory and HTTP-only concerns."""

from contextlib import asynccontextmanager
import logging
from typing import Annotated, AsyncIterator, Callable

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.errors import ApiError, RepositoryError, RepositorySchemaError
from backend.models import CurrentUser, User
from backend.repositories import GoogleSheetsUserRepository, UserRepository
from backend.sheets import SheetsGateway, GoogleSheetsCategoryRepository, GoogleSheetsTransactionRepository
from backend.runtime import BotRuntime
from backend.schemas import (
    CreateUserRequest,
    CurrentUserResponse,
    UpdateUserRequest,
    UserResponse,
)
from backend.services import ApplicationStatusService, UserService
from backend.telegram_auth import InitDataError, TelegramInitDataVerifier
from config import Settings


logger = logging.getLogger(__name__)
RuntimeFactory = Callable[[Settings], BotRuntime]


def create_app(
    settings: Settings,
    *,
    runtime_factory: RuntimeFactory = BotRuntime,
    user_repository: UserRepository | None = None,
) -> FastAPI:
    """Build the app without contacting Telegram or Google Sheets."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime = runtime_factory(settings)
        app.state.bot_runtime = runtime
        await runtime.start()
        try:
            yield
        finally:
            await runtime.stop()

    app = FastAPI(
        title="Family Finance API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            *(
                ["X-Dev-Telegram-User-Id"]
                if settings.environment != "production" and settings.dev_auth_enabled
                else []
            ),
        ],
    )

    status_service = ApplicationStatusService()
    gateway = SheetsGateway(settings)
    users = UserService(user_repository or GoogleSheetsUserRepository(settings, gateway=gateway))
    categories = GoogleSheetsCategoryRepository(settings, gateway=gateway)
    app.state.transaction_repository = GoogleSheetsTransactionRepository(settings, gateway=gateway)
    init_data_verifier = TelegramInitDataVerifier(
        settings.bot_token,
        max_age_seconds=settings.telegram_auth_max_age_seconds,
    )

    async def current_user(
        authorization: Annotated[str | None, Header()] = None,
        dev_user_id: Annotated[str | None, Header(alias="X-Dev-Telegram-User-Id")] = None,
    ) -> CurrentUser:
        telegram_user_id: int
        if settings.environment != "production" and settings.dev_auth_enabled and dev_user_id:
            try:
                telegram_user_id = int(dev_user_id)
            except ValueError as error:
                raise ApiError(
                    code="invalid_auth",
                    message="Некорректные данные авторизации",
                    status_code=401,
                ) from error
        else:
            scheme, separator, init_data = (authorization or "").partition(" ")
            if not separator or scheme.lower() != "tma":
                raise ApiError(
                    code="invalid_auth",
                    message="Требуется авторизация Telegram",
                    status_code=401,
                )
            try:
                identity = init_data_verifier.verify(init_data)
            except InitDataError as error:
                raise ApiError(
                    code="invalid_auth",
                    message="Некорректные данные авторизации",
                    status_code=401,
                ) from error
            telegram_user_id = identity.telegram_user_id
        return await users.authorize(telegram_user_id)

    async def admin_user(
        user: Annotated[CurrentUser, Depends(current_user)],
    ) -> CurrentUser:
        users.require_admin(user)
        return user

    @app.get("/health", tags=["system"])
    async def healthcheck() -> dict[str, str]:
        return status_service.get_status()

    @app.get("/api/me", response_model=CurrentUserResponse, tags=["users"])
    async def get_me(
        user: Annotated[CurrentUser, Depends(current_user)],
    ) -> CurrentUserResponse:
        return CurrentUserResponse.from_domain(user)

    @app.get("/api/admin/users", response_model=list[UserResponse], tags=["admin"])
    async def list_users(
        _admin: Annotated[CurrentUser, Depends(admin_user)],
    ) -> list[UserResponse]:
        return [UserResponse.from_domain(user) for user in await users.list_users()]

    @app.post(
        "/api/admin/users",
        response_model=UserResponse,
        status_code=201,
        tags=["admin"],
    )
    async def create_user(
        request: CreateUserRequest,
        _admin: Annotated[CurrentUser, Depends(admin_user)],
    ) -> UserResponse:
        display_name = request.display_name.strip()
        if not display_name:
            raise ApiError(
                code="validation_error",
                message="Имя пользователя не должно быть пустым",
                status_code=422,
            )
        user = User(
            telegram_user_id=request.telegram_user_id,
            display_name=display_name,
            role=request.role,
            active=request.active,
        )
        return UserResponse.from_domain(await users.create_user(user))

    @app.patch(
        "/api/admin/users/{telegram_user_id}",
        response_model=UserResponse,
        tags=["admin"],
    )
    async def update_user(
        telegram_user_id: int,
        request: UpdateUserRequest,
        _admin: Annotated[CurrentUser, Depends(admin_user)],
    ) -> UserResponse:
        changes = request.changes()
        if "display_name" in changes:
            changes["display_name"] = str(changes["display_name"]).strip()
            if not changes["display_name"]:
                raise ApiError(
                    code="validation_error",
                    message="Имя пользователя не должно быть пустым",
                    status_code=422,
                )
        return UserResponse.from_domain(await users.update_user(telegram_user_id, changes))

    @app.get("/api/categories", tags=["categories"])
    async def list_categories(_user: Annotated[CurrentUser, Depends(current_user)]):
        return [{"name": item.name, "subcategories": list(item.subcategories)}
                for item in await categories.list()]

    @app.exception_handler(RepositoryError)
    async def handle_repository_error(_request: Request, error: RepositoryError):
        schema = isinstance(error, RepositorySchemaError)
        return _error_response(
            500 if schema else 503,
            "storage_schema_error" if schema else "storage_unavailable",
            str(error),
        )

    @app.exception_handler(ApiError)
    async def handle_api_error(_request: Request, error: ApiError) -> JSONResponse:
        return _error_response(error.status_code, error.code, error.message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request,
        _error: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(422, "validation_error", "Некорректные данные запроса")

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_request: Request, error: StarletteHTTPException) -> JSONResponse:
        messages = {404: "Ресурс не найден", 405: "Метод не поддерживается"}
        return _error_response(
            error.status_code,
            "http_error",
            messages.get(error.status_code, "Ошибка HTTP-запроса"),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, _error: Exception) -> JSONResponse:
        logger.error("Необработанная ошибка API: %s %s", request.method, request.url.path)
        return _error_response(500, "internal_error", "Внутренняя ошибка сервера")

    return app


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )
