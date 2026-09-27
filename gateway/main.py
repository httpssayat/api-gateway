import logging
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from .circuit import RedisCircuitBreaker
from .config import get_settings
from .context import correlation_id_var
from .db import create_engine, create_session_factory, save_audit
from .errors import GatewayError, error_body
from .limiter import DownstreamLimiter
from .proxy import proxy_request

logger = logging.getLogger("gateway.main")

ALLOWED_METHODS = [
    "GET",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "OPTIONS",
    "HEAD",
]


class CorrelationIdFilter(logging.Filter):
    """
    Добавляет correlation_id в логи.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.cid = correlation_id_var.get()
        return True


def setup_logging(level: str) -> None:
    """
    Настройка логирование
    """
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level.upper())

    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s cid=%(cid)s %(message)s"
    )

    handler.setFormatter(formatter)
    handler.addFilter(CorrelationIdFilter())
    root.addHandler(handler)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Создаёт и освобождает ресурсы приложения.
    """
    settings = get_settings()
    setup_logging(settings.log_level)

    routes = settings.route_configs()

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    redis_client = Redis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )

    circuit = RedisCircuitBreaker(
        redis=redis_client,
        settings=settings,
    )

    limiter = DownstreamLimiter(
        routes=routes,
        default_timeout=settings.limiter_timeout_ms / 1000.0,
    )

    http_client = httpx.AsyncClient(
        limits=httpx.Limits(
            max_connections=settings.http_max_connections,
            max_keepalive_connections=settings.http_max_keepalive_connections,
        ),
        timeout=None,
        follow_redirects=False,
        trust_env=False,
    )

    app.state.settings = settings
    app.state.routes = routes
    app.state.http_client = http_client
    app.state.limiter = limiter
    app.state.circuit = circuit
    app.state.session_factory = session_factory

    logger.info("API Gateway запущен")

    yield

    await redis_client.aclose()
    await http_client.aclose()
    await engine.dispose()

    logger.info("API Gateway остановлен")


app = FastAPI(
    title="API Gateway",
    lifespan=lifespan,
)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    """
    Чтение correlation_id.
    """
    settings = request.app.state.settings

    request_id = request.headers.get(settings.request_id_header)
    if not request_id:
        request_id = uuid.uuid4().hex

    token = correlation_id_var.set(request_id)

    try:
        response = await call_next(request)
        response.headers[settings.request_id_header] = request_id
        return response
    finally:
        correlation_id_var.reset(token)


@app.exception_handler(GatewayError)
async def gateway_error_handler(request: Request, exc: GatewayError):
    """
    Возвращает ошибки шлюза в едином формате.
    """
    request_id = correlation_id_var.get()
    settings = request.app.state.settings

    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(
            code=exc.code,
            message=exc.message,
            request_id=request_id,
        ),
        headers={settings.request_id_header: request_id},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    """
    Обрабатка непредвиденных ошибкок.
    """
    logger.exception("Необработанная ошибка: %s", exc)

    request_id = correlation_id_var.get()
    settings = request.app.state.settings

    return JSONResponse(
        status_code=500,
        content=error_body(
            code="INTERNAL",
            message="Внутренняя ошибка шлюза",
            request_id=request_id,
        ),
        headers={settings.request_id_header: request_id},
    )


@app.get("/health")
async def health():
    """
    Проверка живости шлюза.
    """
    return {"status": "ok"}


def create_proxy_endpoint(service: str):
    """
    Создаёт обработчик для конкретного сервиса.
    """

    async def proxy_endpoint(request: Request) -> Response:
        """
        Обрабатывает запрос и пишет аудит.
        """
        settings = request.app.state.settings
        session_factory = request.app.state.session_factory

        start = time.perf_counter()
        body = await request.body()
        path = request.path_params.get("path", "")
        request_id = correlation_id_var.get()

        try:
            response = await proxy_request(
                service=service,
                route=request.app.state.routes[service],
                client=request.app.state.http_client,
                limiter=request.app.state.limiter,
                settings=settings,
                circuit=request.app.state.circuit,
                method=request.method,
                path=path,
                query=str(request.url.query),
                headers=request.headers,
                body=body,
                request_id=request_id,
            )

            duration_ms = int((time.perf_counter() - start) * 1000)

            if settings.audit_enabled:
                outcome = "success" if response.status_code < 500 else "upstream_error"
                await save_audit(
                    session_factory,
                    request_id=request_id,
                    service=service,
                    method=request.method,
                    path=path,
                    status_code=response.status_code,
                    outcome=outcome,
                    duration_ms=duration_ms,
                )

            return response

        except GatewayError as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)

            if settings.audit_enabled:
                await save_audit(
                    session_factory,
                    request_id=request_id,
                    service=service,
                    method=request.method,
                    path=path,
                    status_code=exc.status_code,
                    outcome="gateway_error",
                    duration_ms=duration_ms,
                )

            raise

    return proxy_endpoint


# Регистрация маршрутов.
for service in ("users", "orders", "payments"):
    endpoint = create_proxy_endpoint(service)

    app.add_api_route(
        f"/api/{service}",
        endpoint,
        methods=ALLOWED_METHODS,
        include_in_schema=False,
    )

    app.add_api_route(
        f"/api/{service}/{{path:path}}",
        endpoint,
        methods=ALLOWED_METHODS,
        include_in_schema=False,
    )