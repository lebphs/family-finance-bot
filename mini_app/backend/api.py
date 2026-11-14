"""FastAPI application factory and HTTP-only concerns."""

from contextlib import asynccontextmanager
from datetime import date
import logging
from typing import Annotated, AsyncIterator, Callable

from fastapi import Depends, FastAPI, Header, Request, Query, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from mini_app.backend.errors import ApiError, RepositoryError, RepositorySchemaError
from mini_app.backend.models import CurrentUser, User
from mini_app.backend.repositories import UserRepository, CategoryRepository, TransactionRepository
from mini_app.backend.database import SQLiteUserRepository, SQLiteCategoryRepository, SQLiteTransactionRepository
from mini_app.backend.runtime import BotRuntime
from mini_app.backend.travel import TripInput, TravelModeInput, TripRepository, TravelService, Scope
from mini_app.backend.exchange import ExchangeService
from mini_app.backend.schemas import (
    CreateUserRequest,
    CurrentUserResponse,
    UpdateUserRequest,
    UserResponse,
    CreateExpenseRequest,
    TransactionResponse,
    HomeResponse,
    TransactionFilters, TransactionPage, TransactionParticipant, UpdateTransactionRequest,
)
from mini_app.backend.reminders import ReminderService, ReminderSettings, ReminderResponse
from mini_app.backend.services import ApplicationStatusService, UserService, ExpenseService
from mini_app.backend.statistics import StatisticsQuery, StatisticsResponse, StatisticsService
from mini_app.backend.telegram_auth import InitDataError, TelegramInitDataVerifier
from config import Settings


logger = logging.getLogger(__name__)
RuntimeFactory = Callable[[Settings], BotRuntime]


def create_app(
    settings: Settings,
    *,
    runtime_factory: RuntimeFactory = BotRuntime,
    user_repository: UserRepository | None = None,
    category_repository: CategoryRepository | None = None,
    transaction_repository: TransactionRepository | None = None,
    exchange_service=None,
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
    user_store = user_repository or SQLiteUserRepository(settings)
    users = UserService(user_store)
    categories = category_repository or SQLiteCategoryRepository(settings)
    app.state.transaction_repository = transaction_repository or SQLiteTransactionRepository(settings)
    trips = TripRepository(settings)
    travel = TravelService(trips, app.state.transaction_repository)
    # Legacy Sheets adapters do not store trip/currency metadata. Keep their
    # existing expense path independent of local SQLite state (also in tests).
    expense_trips = trips if isinstance(app.state.transaction_repository, SQLiteTransactionRepository) else None
    expenses = ExpenseService(app.state.transaction_repository, categories, trips=expense_trips,
                              exchange=exchange_service or ExchangeService(settings))
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

    reminders = ReminderService(user_store)

    @app.get("/api/reminders", response_model=ReminderResponse, tags=["reminders"])
    async def get_reminders(user: Annotated[CurrentUser, Depends(current_user)]):
        return await reminders.get(user)

    @app.put("/api/reminders", response_model=ReminderResponse, tags=["reminders"])
    async def put_reminders(request: ReminderSettings, user: Annotated[CurrentUser, Depends(current_user)]):
        return await reminders.update(user, request)

    @app.get("/api/categories", tags=["categories"])
    async def list_categories(_user: Annotated[CurrentUser, Depends(current_user)], travel: bool = False):
        return [{"name": item.name, "subcategories": list(item.subcategories)}
                for item in (await trips.categories() if travel else await categories.list())]

    @app.get("/api/travel-mode", tags=["trips"])
    async def get_travel_mode(user: Annotated[CurrentUser, Depends(current_user)]):
        return await travel.context(user.telegram_user_id)

    @app.put("/api/travel-mode", tags=["trips"])
    async def set_travel_mode(request: TravelModeInput, user: Annotated[CurrentUser, Depends(current_user)]):
        await trips.set_active(user.telegram_user_id, request.trip_id)
        return await travel.context(user.telegram_user_id)

    @app.get("/api/trips", tags=["trips"])
    async def list_trips(_user: Annotated[CurrentUser, Depends(current_user)]):
        return await trips.list()

    @app.post("/api/trips", status_code=201, tags=["trips"])
    async def create_trip(request: TripInput, user: Annotated[CurrentUser, Depends(current_user)]):
        return await trips.save(request, user)

    @app.put("/api/trips/{trip_id}", tags=["trips"])
    async def edit_trip(trip_id: str, request: TripInput, user: Annotated[CurrentUser, Depends(current_user)]):
        return await trips.save(request, user, trip_id)

    @app.post("/api/trips/{trip_id}/complete", tags=["trips"])
    async def complete_trip(trip_id: str, user: Annotated[CurrentUser, Depends(current_user)]):
        return await trips.save(None, user, trip_id, complete=True)

    @app.get("/api/trips/{trip_id}/report", tags=["trips"])
    async def trip_report(trip_id: str, _user: Annotated[CurrentUser, Depends(current_user)]):
        return await travel.report(trip_id)

    @app.post("/api/transactions", response_model=TransactionResponse, status_code=201, tags=["transactions"])
    async def create_expense(
        request: CreateExpenseRequest,
        user: Annotated[CurrentUser, Depends(current_user)],
    ) -> TransactionResponse:
        return await expenses.create(request, user)

    @app.get("/api/transactions", response_model=TransactionPage, tags=["transactions"])
    async def list_transactions(
        _user: Annotated[CurrentUser, Depends(current_user)],
        filters: Annotated[TransactionFilters, Query()],
    ):
        return await expenses.list(filters)

    @app.get("/api/transactions/categories", response_model=list[str], tags=["transactions"])
    async def transaction_categories(_user: Annotated[CurrentUser, Depends(current_user)]):
        return sorted({item.category for item in await expenses.transactions.list()})

    @app.get("/api/transactions/participants", response_model=list[TransactionParticipant], tags=["transactions"])
    async def list_participants(_user: Annotated[CurrentUser, Depends(current_user)]):
        return await expenses.participants()

    @app.get("/api/transactions/{transaction_id}", response_model=TransactionResponse, tags=["transactions"])
    async def get_transaction(transaction_id: str, _user: Annotated[CurrentUser, Depends(current_user)]):
        return TransactionResponse.from_domain(await expenses.get(transaction_id))

    @app.patch("/api/transactions/{transaction_id}", response_model=TransactionResponse, tags=["transactions"])
    async def update_transaction(transaction_id: str, request: UpdateTransactionRequest,
                                 user: Annotated[CurrentUser, Depends(current_user)]):
        return await expenses.update(transaction_id, request, user)

    @app.delete("/api/transactions/{transaction_id}", status_code=204, tags=["transactions"])
    async def delete_transaction(transaction_id: str, user: Annotated[CurrentUser, Depends(current_user)],
                                 version: Annotated[str, Query(pattern=r"^[a-f0-9]{64}$")]):
        await expenses.delete(transaction_id, version, user)
        return Response(status_code=204)

    @app.get("/api/statistics", response_model=StatisticsResponse, tags=["statistics"])
    async def get_statistics(
        _user: Annotated[CurrentUser, Depends(current_user)],
        query: Annotated[StatisticsQuery, Query()],
    ) -> StatisticsResponse:
        return await StatisticsService(app.state.transaction_repository).get(query)

    @app.get("/api/home", response_model=HomeResponse, tags=["home"])
    async def get_home(
        _user: Annotated[CurrentUser, Depends(current_user)], scope: Scope = 'everyday',
        month: Annotated[str | None, Query(pattern=r"^([1-9][0-9]{3}|0[1-9][0-9]{2}|00[1-9][0-9]|000[1-9])-(0[1-9]|1[0-2])$")] = None,
    ) -> HomeResponse:
        return await expenses.home(today=date.fromisoformat(f"{month}-01") if month else None, scope=scope)

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

    # Only built public assets are served; no repository root or state files.
    from pathlib import Path
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse
    frontend = Path(settings.frontend_dir).resolve()
    if (frontend / "index.html").is_file():
        assets = frontend / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/", include_in_schema=False)
        async def frontend_index():
            return FileResponse(frontend / "index.html", headers={"Cache-Control": "no-store"})

    return app


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )
