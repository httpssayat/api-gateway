from functools import lru_cache

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class RouteConfig(BaseModel):
    """
    Конфигурация одного маршрута.

    Все таймауты уже переведены в секунды.
    """

    base_url: str
    connect_timeout: float
    read_timeout: float
    total_timeout: float
    max_concurrency: int


class Settings(BaseSettings):
    """
    Настройки приложения.

    Читаются из переменных окружения и .env файла.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Общие настройки
    log_level: str = "INFO"
    request_id_header: str = "X-Request-Id"

    # Повторы
    max_retries: int = 2
    retry_backoff_ms: int = 50

    # Пул соединений
    http_max_connections: int = 200
    http_max_keepalive_connections: int = 50

    # Сколько ждать слот лимитера
    limiter_timeout_ms: int = 200

    # PostgreSQL и Redis
    database_url: str = "postgresql+asyncpg://gateway:gateway@localhost:5432/gateway"
    redis_url: str = "redis://localhost:6379/0"

    # Аудит запросов в PostgreSQL.
    # На нагрузке лучше выключать.
    audit_enabled: bool = False

    # Circuit breaker
    circuit_enabled: bool = True
    circuit_failure_threshold: int = 100
    circuit_cooldown_ms: int = 1000

    # Сервисы
    users_base_url: str = "http://127.0.0.1:8001"
    orders_base_url: str = "http://127.0.0.1:8002"
    payments_base_url: str = "http://127.0.0.1:8003"

    # users
    users_connect_timeout_ms: int = 200
    users_read_timeout_ms: int = 1000
    users_total_timeout_ms: int = 2000
    users_max_concurrency: int = 100

    # orders
    orders_connect_timeout_ms: int = 200
    orders_read_timeout_ms: int = 800
    orders_total_timeout_ms: int = 1000
    orders_max_concurrency: int = 100

    # payments
    payments_connect_timeout_ms: int = 200
    payments_read_timeout_ms: int = 1000
    payments_total_timeout_ms: int = 2000
    payments_max_concurrency: int = 100

    def route_configs(self) -> dict[str, RouteConfig]:
        """
        Собирает конфигурацию всех маршрутов.
        """

        def seconds(milliseconds: int) -> float:
            """
            Переводит миллисекунды в секунды.
            """
            return milliseconds / 1000.0

        return {
            "users": RouteConfig(
                base_url=self.users_base_url,
                connect_timeout=seconds(self.users_connect_timeout_ms),
                read_timeout=seconds(self.users_read_timeout_ms),
                total_timeout=seconds(self.users_total_timeout_ms),
                max_concurrency=self.users_max_concurrency,
            ),
            "orders": RouteConfig(
                base_url=self.orders_base_url,
                connect_timeout=seconds(self.orders_connect_timeout_ms),
                read_timeout=seconds(self.orders_read_timeout_ms),
                total_timeout=seconds(self.orders_total_timeout_ms),
                max_concurrency=self.orders_max_concurrency,
            ),
            "payments": RouteConfig(
                base_url=self.payments_base_url,
                connect_timeout=seconds(self.payments_connect_timeout_ms),
                read_timeout=seconds(self.payments_read_timeout_ms),
                total_timeout=seconds(self.payments_total_timeout_ms),
                max_concurrency=self.payments_max_concurrency,
            ),
        }


@lru_cache
def get_settings() -> Settings:
    """
    Возвращает единственный экземпляр настроек.
    """
    return Settings()