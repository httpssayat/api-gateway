import logging
import time

from redis.asyncio import Redis
from redis.exceptions import RedisError

from .config import Settings
from .errors import CircuitOpenError

logger = logging.getLogger("gateway.circuit")


class RedisCircuitBreaker:
    """
    Минимальный circuit breaker на Redis.

    Если Redis недоступен, шлюз продолжает пропускать запросы.
    Это сознательное решение: лучше временно потерять защиту,
    чем полностью остановить маршрутизацию.
    """

    def __init__(self, redis: Redis, settings: Settings) -> None:
        """
        Сохраняет клиент Redis и настройки.
        """
        self._redis = redis
        self._enabled = settings.circuit_enabled
        self._threshold = settings.circuit_failure_threshold
        self._cooldown = settings.circuit_cooldown_ms / 1000.0

    def _keys(self, service: str) -> tuple[str, str, str]:
        """
        Возвращает ключи для сервиса.
        """
        return (
            f"cb:{service}:failures",
            f"cb:{service}:state",
            f"cb:{service}:opened_at",
        )

    async def ensure_allowed(self, service: str) -> None:
        """
        Проверяет, можно ли выполнять запрос.
        """
        if not self._enabled:
            return

        failures_key, state_key, opened_at_key = self._keys(service)

        try:
            state = await self._redis.get(state_key)

            if state == "OPEN":
                opened_at_raw = await self._redis.get(opened_at_key)
                opened_at = float(opened_at_raw) if opened_at_raw else 0.0

                if time.time() - opened_at < self._cooldown:
                    raise CircuitOpenError(
                        f"Circuit breaker открыт для сервиса {service}",
                    )

                # После cooldown разрешаем пробный запрос.
                await self._redis.set(state_key, "HALF_OPEN")

        except CircuitOpenError:
            raise
        except RedisError:
            logger.warning("Redis недоступен, пропускаем запрос", exc_info=True)

    async def record_success(self, service: str) -> None:
        """
        Фиксирует успешный запрос.
        """
        if not self._enabled:
            return

        failures_key, state_key, opened_at_key = self._keys(service)

        try:
            pipe = self._redis.pipeline()
            pipe.delete(failures_key)
            pipe.delete(opened_at_key)
            pipe.set(state_key, "CLOSED")
            await pipe.execute()
        except RedisError:
            logger.warning("Redis недоступен при записи успеха", exc_info=True)

    async def record_failure(self, service: str) -> None:
        """
        Фиксирует ошибку запроса.
        """
        if not self._enabled:
            return

        failures_key, state_key, opened_at_key = self._keys(service)

        try:
            state = await self._redis.get(state_key)

            # Если были в HALF_OPEN и получили ошибку, снова открываем цепь.
            if state == "HALF_OPEN":
                await self._open(service, state_key, opened_at_key)
                return

            failures = await self._redis.incr(failures_key)
            await self._redis.expire(failures_key, 10)

            if failures >= self._threshold:
                await self._open(service, state_key, opened_at_key)

        except RedisError:
            logger.warning("Redis недоступен при записи ошибки", exc_info=True)

    async def _open(self, service: str, state_key: str, opened_at_key: str) -> None:
        """
        Открывает цепь.
        """
        pipe = self._redis.pipeline()
        pipe.set(state_key, "OPEN")
        pipe.set(opened_at_key, str(time.time()))
        await pipe.execute()

        logger.warning("Circuit breaker открыт для сервиса %s", service)