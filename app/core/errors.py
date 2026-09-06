"""Safe domain errors; never carry passwords, tokens, SQL, or connection URLs."""


class AppError(Exception):
    def __init__(self, status_code: int, detail: str, headers: dict | None = None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.headers = headers or {}


def unauthorized():
    return AppError(
        401, "Could not validate credentials", {"WWW-Authenticate": "Bearer"}
    )


class HardDeleteDisabled(AppError):
    def __init__(self):
        super().__init__(
            409, "Account deletion is disabled. Deactivate the account instead."
        )
