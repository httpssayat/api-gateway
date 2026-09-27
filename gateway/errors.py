from typing import Any


class GatewayError(Exception):
    """
    Базовая ошибка шлюза.

    Позволяет возвращать ошибки в едином формате.
    """

    status_code: int = 500
    code: str = "INTERNAL"

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        code: str | None = None,
    ) -> None:
        """
        Создаёт ошибку.
        """
        super().__init__(message)
        self.message = message

        if status_code is not None:
            self.status_code = status_code

        if code is not None:
            self.code = code


class UpstreamTimeoutError(GatewayError):
    """
    Таймаут при обращении к сервису.
    """

    status_code = 504
    code = "UPSTREAM_TIMEOUT"


class UpstreamConnectionError(GatewayError):
    """
    Ошибка соединения с сервисом.
    """

    status_code = 502
    code = "UPSTREAM_CONNECTION_ERROR"


class LimiterTimeoutError(GatewayError):
    """
    Не получили слот лимитера.
    """

    status_code = 503
    code = "GATEWAY_OVERLOAD"


class CircuitOpenError(GatewayError):
    """
    Circuit breaker открыт.
    """

    status_code = 503
    code = "CIRCUIT_OPEN"


def error_body(code: str, message: str, request_id: str) -> dict[str, Any]:
    """
    Единый формат ошибки.
    """
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
        }
    }