import asyncio
import os
import random
from collections import deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ControlPayload(BaseModel):
    """
    Настройки поведения заглушки.
    """

    delay_ms: int | None = None
    error_status_code: int | None = None
    error_probability: float | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Инициализация состояние заглушки
    """
    app.state.config = {
        "delay_ms": int(os.getenv("DEFAULT_DELAY_MS", "0")),
        "error_status_code": int(os.getenv("DEFAULT_ERROR_STATUS_CODE", "500")),
        "error_probability": float(os.getenv("ERROR_PROBABILITY", "0.0")),
    }

    # Храним последние запросы для тестов.
    app.state.requests = deque(maxlen=5000)

    yield


app = FastAPI(lifespan=lifespan)

service_name = os.getenv("SERVICE_NAME", "unknown")


@app.get("/_health")
async def health():
    """
    Проверка живости заглушки
    """
    return {"status": "ok", "service": service_name}


@app.post("/_control")
async def control(payload: ControlPayload, request: Request):
    """
    поведение заглушки без перезапуска
    """
    config = request.app.state.config

    if payload.delay_ms is not None:
        config["delay_ms"] = payload.delay_ms

    if payload.error_status_code is not None:
        config["error_status_code"] = payload.error_status_code

    if payload.error_probability is not None:
        config["error_probability"] = payload.error_probability

    return config


@app.get("/_requests")
async def get_requests(request: Request, request_id: str | None = None):
    """
    Возвращение посл запросов.

    Используется в тестах идемпотентности.
    """
    items = list(request.app.state.requests)

    if request_id:
        items = [item for item in items if item["request_id"] == request_id]

    return {
        "service": service_name,
        "requests": items,
    }


@app.api_route(
    "/{path:path}",
    methods=[
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
        "HEAD",
    ],
)
async def catch_all(request: Request, path: str):
    """
    Основной обработчик

    Запись запроса делается до задержки, чтобы даже при таймауте
    можно было проверить, сколько раз запрос дошёл до сервиса.
    """
    config = request.app.state.config

    body = await request.body()
    request_id = request.headers.get("X-Request-Id", "-")

    request.app.state.requests.append(
        {
            "method": request.method,
            "path": path,
            "request_id": request_id,
            "body_size": len(body),
        }
    )

    delay_ms = config["delay_ms"]
    if delay_ms > 0:
        await asyncio.sleep(delay_ms / 1000.0)

    if random.random() < config["error_probability"]:
        return JSONResponse(
            status_code=config["error_status_code"],
            content={
                "service": service_name,
                "error": "simulated_error",
                "request_id": request_id,
            },
        )

    return JSONResponse(
        status_code=200,
        content={
            "service": service_name,
            "method": request.method,
            "path": path,
            "request_id": request_id,
        },
    )