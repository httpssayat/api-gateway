import asyncio
import logging
import time
from collections.abc import Mapping

import httpx
from fastapi import Response

from .circuit import RedisCircuitBreaker
from .config import RouteConfig, Settings
from .errors import (
    CircuitOpenError,
    GatewayError,
    LimiterTimeoutError,
    UpstreamConnectionError,
    UpstreamTimeoutError,
)
from .limiter import DownstreamLimiter

logger = logging.getLogger("gateway.proxy")

# Технические заголовки, которые не нужно пробрасывать дальше.
HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "upgrade",
        "transfer-encoding",
    }
)

# Методы, для которых разрешены повторы.
IDEMPOTENT_METHODS = frozenset(
    {
        "GET",
        "HEAD",
        "OPTIONS",
        "PUT",
        "DELETE",
    }
)


def filter_request_headers(
    headers: Mapping[str, str],
    request_id_header: str,
    request_id: str,
) -> dict[str, str]:
    """
    Готовит заголовки для отправки в сервис.
    """
    result: dict[str, str] = {}

    for name, value in headers.items():
        lower_name = name.lower()

        if lower_name in HOP_BY_HOP_HEADERS:
            continue

        # Эти заголовки должен выставить сам клиент.
        if lower_name in {"host", "content-length"}:
            continue

        result[name] = value

    result[request_id_header] = request_id
    return result


def build_downstream_url(base_url: str, path: str, query: str) -> str:
    """
    Собирает итоговый адрес сервиса.
    """
    target = base_url.rstrip("/")

    if path:
        target = f"{target}/{path.lstrip('/')}"

    if query:
        target = f"{target}?{query}"

    return target


async def sleep_before_retry(retry_backoff_ms: int, deadline: float) -> None:
    """
    Небольшая пауза перед повтором.
    """
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return

    await asyncio.sleep(min(retry_backoff_ms / 1000.0, remaining))


def build_fastapi_response(upstream_response: httpx.Response) -> Response:
    """
    Преобразует ответ сервиса в ответ шлюза.
    """
    content_type = upstream_response.headers.get("content-type")
    headers: dict[str, str] = {}

    for name, value in upstream_response.headers.multi_items():
        lower_name = name.lower()

        if lower_name in HOP_BY_HOP_HEADERS:
            continue

        if lower_name in {
            "content-length",
            "content-encoding",
            "transfer-encoding",
        }:
            continue

        headers[name] = value

    headers.pop("content-type", None)

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=headers,
        media_type=content_type,
    )


async def proxy_request(
    *,
    service: str,
    route: RouteConfig,
    client: httpx.AsyncClient,
    limiter: DownstreamLimiter,
    settings: Settings,
    circuit: RedisCircuitBreaker | None,
    method: str,
    path: str,
    query: str,
    headers: Mapping[str, str],
    body: bytes,
    request_id: str,
) -> Response:
    """
    Проксирует запрос в сервис.

    Здесь реализованы:
    - таймауты;
    - общий бюджет времени;
    - повторы только для идемпотентных методов;
    - лимит одновременных запросов;
    - circuit breaker.
    """
    downstream_url = build_downstream_url(
        base_url=route.base_url,
        path=path,
        query=query,
    )

    downstream_headers = filter_request_headers(
        headers=headers,
        request_id_header=settings.request_id_header,
        request_id=request_id,
    )

    timeout = httpx.Timeout(
        connect=route.connect_timeout,
        read=route.read_timeout,
        write=route.read_timeout,
        pool=route.connect_timeout,
    )

    deadline = time.monotonic() + route.total_timeout
    method_upper = method.upper()
    is_idempotent = method_upper in IDEMPOTENT_METHODS

    if is_idempotent:
        attempts = 1 + settings.max_retries
    else:
        attempts = 1

    if circuit:
        await circuit.ensure_allowed(service)

    try:
        for attempt in range(1, attempts + 1):
            remaining = deadline - time.monotonic()

            if remaining <= 0:
                raise UpstreamTimeoutError(
                    "Превышен общий бюджет времени запроса",
                )

            try:
                async with limiter.acquire(service, timeout=remaining):
                    try:
                        upstream_response = await asyncio.wait_for(
                            client.request(
                                method=method_upper,
                                url=downstream_url,
                                content=body,
                                headers=downstream_headers,
                                timeout=timeout,
                            ),
                            timeout=remaining,
                        )
                    except asyncio.TimeoutError as exc:
                        raise UpstreamTimeoutError(
                            "Превышен общий бюджет времени запроса",
                        ) from exc

            except httpx.ConnectTimeout as exc:
                if is_idempotent and attempt < attempts:
                    logger.warning(
                        "Таймаут соединения с %s, повтор %s/%s",
                        service,
                        attempt,
                        settings.max_retries,
                    )
                    await sleep_before_retry(settings.retry_backoff_ms, deadline)
                    continue

                raise UpstreamTimeoutError(
                    f"Таймаут соединения с сервисом {service}",
                ) from exc

            except httpx.ConnectError as exc:
                if is_idempotent and attempt < attempts:
                    logger.warning(
                        "Ошибка соединения с %s, повтор %s/%s",
                        service,
                        attempt,
                        settings.max_retries,
                    )
                    await sleep_before_retry(settings.retry_backoff_ms, deadline)
                    continue

                raise UpstreamConnectionError(
                    f"Не удалось подключиться к сервису {service}",
                ) from exc

            except httpx.ReadTimeout as exc:
                raise UpstreamTimeoutError(
                    f"Таймаут чтения ответа от сервиса {service}",
                ) from exc

            except httpx.WriteTimeout as exc:
                raise UpstreamTimeoutError(
                    f"Таймаут отправки тела запроса в сервис {service}",
                ) from exc

            except httpx.PoolTimeout as exc:
                raise UpstreamTimeoutError(
                    f"Таймаут ожидания соединения из пула для сервиса {service}",
                ) from exc

            except httpx.HTTPError as exc:
                raise UpstreamConnectionError(
                    f"Ошибка при обращении к сервису {service}",
                ) from exc

            # 503 можно повторять только для идемпотентных методов.
            if (
                upstream_response.status_code == 503
                and is_idempotent
                and attempt < attempts
            ):
                logger.warning(
                    "Сервис %s вернул 503, повтор %s/%s",
                    service,
                    attempt,
                    settings.max_retries,
                )
                await sleep_before_retry(settings.retry_backoff_ms, deadline)
                continue

            # Фиксируем результат для circuit breaker.
            if circuit:
                if upstream_response.status_code >= 500:
                    await circuit.record_failure(service)
                else:
                    await circuit.record_success(service)

            return build_fastapi_response(upstream_response)

    except CircuitOpenError:
        raise

    except LimiterTimeoutError:
        raise

    except GatewayError:
        if circuit:
            await circuit.record_failure(service)
        raise

    # Сюда попадать не должны, но оставляем явную ошибку.
    if circuit:
        await circuit.record_failure(service)

    raise UpstreamConnectionError(
        f"Не удалось выполнить запрос к сервису {service}",
    )