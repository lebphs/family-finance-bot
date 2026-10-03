"""Framework-independent application services."""

from backend.errors import ApiError
from backend.models import CurrentUser, User, UserRole
from backend.repositories import UserAlreadyExistsError, UserRepository


class ApplicationStatusService:
    def get_status(self) -> dict[str, str]:
        return {"status": "ok", "service": "family-finance-backend"}


class UserService:
    def __init__(self, repository: UserRepository) -> None:
        self._repository = repository

    async def authorize(self, telegram_user_id: int) -> CurrentUser:
        user = await self._repository.get(telegram_user_id)
        if user is None or not user.active:
            raise ApiError(code="access_denied", message="Нет доступа", status_code=403)
        return CurrentUser.from_user(user)

    @staticmethod
    def require_admin(current_user: CurrentUser) -> None:
        if current_user.role is not UserRole.ADMIN:
            raise ApiError(code="access_denied", message="Недостаточно прав", status_code=403)

    async def list_users(self) -> list[User]:
        return await self._repository.list()

    async def create_user(self, user: User) -> User:
        try:
            return await self._repository.create(user)
        except UserAlreadyExistsError as error:
            raise ApiError(
                code="user_already_exists",
                message="Пользователь уже существует",
                status_code=409,
            ) from error

    async def update_user(self, telegram_user_id: int, changes: dict[str, object]) -> User:
        user = await self._repository.update(telegram_user_id, changes)
        if user is None:
            raise ApiError(code="user_not_found", message="Пользователь не найден", status_code=404)
        return user
