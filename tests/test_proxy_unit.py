import httpx
import pytest
from starlette.datastructures import Headers

from gateway.config import RouteConfig, Settings
from gateway.errors import UpstreamConnectionError, UpstreamTimeoutError
from gateway.limiter import DownstreamLimiter
from gateway.proxy import proxy_request


def make_route() -> RouteConfig:
    """
    Создаёт тестовую конфигурацию маршрута.
    """
    return RouteConfig(
        base_url="http://stub",
        connect_timeout=0.05,
        read_timeout=0.05,
        total_timeout=0.2,
        max_concurrency=10,
    )


def make_settings() -> Settings:
    """
    Создаёт тестовые настройки.
    """
    return Settings(
        _env_file=None,
        max_retries=2,
        retry_backoff_ms=1,
        circuit_enabled=False,
    )


@pytest.mark.asyncio
async def test_post_is_never_retried_on_connect_error():
    """
    POST не повторяется при ошибке соединения.
    """
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("boom", request=request)

    route = make_route()
    limiter = DownstreamLimiter({"users": route}, default_timeout=0.05)
    settings = make_settings()

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(UpstreamConnectionError):
            await proxy_request(
                service="users",
                route=route,
                client=client,
                limiter=limiter,
                settings=settings,
                circuit=None,
                method="POST",
                path="orders",
                query="",
                headers=Headers({}),
                body=b'{"amount": 100}',
                request_id="test-post-connect",
            )

    assert calls == 1


@pytest.mark.asyncio
async def test_post_is_not_retried_on_503():
    """
    POST не повторяется даже при 503.
    """
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, text="busy")

    route = make_route()
    limiter = DownstreamLimiter({"users": route}, default_timeout=0.05)
    settings = make_settings()

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        response = await proxy_request(
            service="users",
            route=route,
            client=client,
            limiter=limiter,
            settings=settings,
            circuit=None,
            method="POST",
            path="orders",
            query="",
            headers=Headers({}),
            body=b'{"amount": 100}',
            request_id="test-post-503",
        )

    assert response.status_code == 503
    assert calls == 1


@pytest.mark.asyncio
async def test_get_can_retry_on_503():
    """
    GET можно повторить при 503.
    """
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1

        if calls == 1:
            return httpx.Response(503, text="busy")

        return httpx.Response(200, json={"ok": True})

    route = make_route()
    limiter = DownstreamLimiter({"users": route}, default_timeout=0.05)
    settings = make_settings()

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        response = await proxy_request(
            service="users",
            route=route,
            client=client,
            limiter=limiter,
            settings=settings,
            circuit=None,
            method="GET",
            path="me",
            query="",
            headers=Headers({}),
            body=b"",
            request_id="test-get-503",
        )

    assert response.status_code == 200
    assert calls == 2


@pytest.mark.asyncio
async def test_read_timeout_is_not_retried():
    """
    Таймаут чтения не повторяется и возвращает 504.
    """
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("read timeout", request=request)

    route = make_route()
    limiter = DownstreamLimiter({"users": route}, default_timeout=0.05)
    settings = make_settings()

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(UpstreamTimeoutError):
            await proxy_request(
                service="users",
                route=route,
                client=client,
                limiter=limiter,
                settings=settings,
                circuit=None,
                method="GET",
                path="me",
                query="",
                headers=Headers({}),
                body=b"",
                request_id="test-read-timeout",
            )

    assert calls == 1