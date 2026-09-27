import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from .config import RouteConfig
from .errors import LimiterTimeoutError


class DownstreamLimiter:
    """
    Ограничивает число одновременных запросов к каждому сервису.
    """

    def __init__(
        self,
        routes: dict[str, RouteConfig],
        default_timeout: float,
    ) -> None:
        """
        Создаёт семафоры для маршрутов.
        """
        self._semaphores = {
            name: asyncio.Semaphore(config.max_concurrency)
            for name, config in routes.items()
        }
        self._default_timeout = default_timeout

    @asynccontextmanager
    async def acquire(
        self,
        service: str,
        timeout: float | None = None,
    ) -> AsyncIterator[None]:
        """
        Занимает слот.

        Если слот не получен вовремя, возвращаем 503.
        """
        semaphore = self._semaphores[service]

        if timeout is None:
            effective_timeout = self._default_timeout
        else:
            effective_timeout = min(timeout, self._default_timeout)

        try:
            await asyncio.wait_for(
                semaphore.acquire(),
                timeout=effective_timeout,
            )
        except asyncio.TimeoutError as exc:
            raise LimiterTimeoutError(
                f"Слишком много запросов к сервису {service}",
            ) from exc

        try:
            yield
        finally:
            semaphore.release()