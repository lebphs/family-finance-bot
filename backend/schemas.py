"""HTTP request and response schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.models import CurrentUser, User, UserRole


class CurrentUserResponse(BaseModel):
    telegram_user_id: int
    display_name: str
    role: UserRole

    @classmethod
    def from_domain(cls, user: CurrentUser) -> "CurrentUserResponse":
        return cls(
            telegram_user_id=user.telegram_user_id,
            display_name=user.display_name,
            role=user.role,
        )


class UserResponse(BaseModel):
    telegram_user_id: int
    display_name: str
    role: UserRole
    active: bool
    reminder_enabled: bool
    reminder_time: str
    reminder_days: str
    timezone: str
    chat_id: int | None

    @classmethod
    def from_domain(cls, user: User) -> "UserResponse":
        return cls(
            telegram_user_id=user.telegram_user_id,
            display_name=user.display_name,
            role=user.role,
            active=user.active,
            reminder_enabled=user.reminder_enabled,
            reminder_time=user.reminder_time,
            reminder_days=user.reminder_days,
            timezone=user.timezone,
            chat_id=user.chat_id,
        )


class CreateUserRequest(BaseModel):
    telegram_user_id: int = Field(gt=0)
    display_name: str = Field(min_length=1, max_length=100)
    role: UserRole = UserRole.MEMBER
    active: bool = True


class UpdateUserRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    role: UserRole | None = None
    active: bool | None = None

    def changes(self) -> dict[str, object]:
        return {
            name: value
            for name, value in (
                ("display_name", self.display_name),
                ("role", self.role),
                ("active", self.active),
            )
            if value is not None
        }
