"""Application errors safe to expose through the HTTP API."""


class ApiError(Exception):
    def __init__(self, *, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code




class RepositoryError(Exception):
    def __init__(self):
        super().__init__("Не удалось обратиться к Google Sheets. Проверьте результат операции перед повтором.")


class RepositoryUnavailableError(RepositoryError):
    pass


class RepositorySchemaError(RepositoryError):
    def __init__(self):
        Exception.__init__(self, "Структура Google Sheets не соответствует ожидаемой. Требуется проверка миграции.")


class UserAlreadyExistsError(ValueError):
    pass
