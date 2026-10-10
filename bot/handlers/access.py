"""Access checks for bot calls using the same allowlist as the API."""
from mini_app.backend.errors import ApiError, RepositoryError
from mini_app.backend.repositories import GoogleSheetsUserRepository
from mini_app.backend.services import UserService
from config import load_settings


async def authorize_message(message):
    target = message.message if hasattr(message, "message") else message
    if target is None:
        return None
    if message.from_user is None:
        await target.answer("Нет доступа")
        return None
    try:
        return await UserService(GoogleSheetsUserRepository(load_settings())).authorize(message.from_user.id)
    except (ApiError, RepositoryError) as error:
        await target.answer(str(error))
        return None
