class AppError(Exception):
    """Base for all expected, client-facing errors."""

    status_code = 500
    code = "INTERNAL_ERROR"
    headers: dict[str, str] | None = None

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"


class UnprocessableError(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"


class PreconditionRequiredError(AppError):
    status_code = 428
    code = "PRECONDITION_REQUIRED"


class UnauthorizedError(AppError):
    status_code = 401
    code = "NOT_AUTHENTICATED"
    headers = {"WWW-Authenticate": "Bearer"}


class ForbiddenError(AppError):
    status_code = 403
    code = "FORBIDDEN"
