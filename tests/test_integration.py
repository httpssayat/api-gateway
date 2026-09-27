import asyncio
import uuid

import httpx
import pytest
from sqlalchemy import select

from gateway.circuit import RedisCircuitBreaker
from gateway.config import Settings
from gateway.db import RequestAudit
from gateway.errors import CircuitOpenError

pytestmark = pytest.mark.integration


async def wait_for_audit(db_session, request_id: str) -> bool:
    """
    Ждёт запись аудита в PostgreSQL.
    """
    for _ in range(30):
        result = await db_session.execute(
            select(RequestAudit).where(RequestAudit.request_id == request_id)
        )
        row = result.scalar_one_or_none()

        if row is not None:
            return True

        await asyncio.sleep(0.2)

    return False


@pytest.mark.asyncio
async def test_health_and_correlation_header(gateway_url):
    """
    Проверяет /health и возврат X-Request-Id.
    """
    request_id = uuid.uuid4().hex

    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(
            f"{gateway_url}/health",
            headers={"X-Request-Id": request_id},
        )

    assert response.status_code == 200
    assert response.headers.get("X-Request-Id") == request_id


@pytest.mark.asyncio
async def test_gateway_proxies_users_and_writes_audit(gateway_url, db_session):
    """
    Проверяет проксирование и запись аудита в PostgreSQL.
    """
    request_id = uuid.uuid4().hex

    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(
            f"{gateway_url}/api/users/profile",
            headers={"X-Request-Id": request_id},
        )

    assert response.status_code == 200
    assert response.headers.get("X-Request-Id") == request_id

    assert await wait_for_audit(db_session, request_id)


@pytest.mark.asyncio
async def test_post_is_not_duplicated_on_timeout(
    gateway_url,
    orders_internal_url,
):
    """
    Проверяет, что POST не дублируется при таймауте.
    """
    request_id = uuid.uuid4().hex

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Делаем orders медленным.
        control = await client.post(
            f"{gateway_url}/api/orders/_control",
            json={"delay_ms": 3000},
        )
        assert control.status_code == 200

        # Отправляем POST.
        response = await client.post(
            f"{gateway_url}/api/orders/items",
            headers={"X-Request-Id": request_id},
            json={"item": "phone"},
        )

        assert response.status_code == 504

        # Даём заглушке время сохранить запрос.
        await asyncio.sleep(0.3)

        requests_response = await client.get(
            f"{orders_internal_url}/_requests",
            params={"request_id": request_id},
        )

        items = requests_response.json()["requests"]
        assert len(items) == 1

        # Возвращаем нормальное поведение.
        reset = await client.post(
            f"{gateway_url}/api/orders/_control",
            json={"delay_ms": 10},
        )
        assert reset.status_code == 200


@pytest.mark.asyncio
async def test_post_is_not_duplicated_on_503(
    gateway_url,
    orders_internal_url,
):
    """
    Проверяет, что POST не повторяется при 503.
    """
    request_id = uuid.uuid4().hex

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Настраиваем orders возвращать 503.
        control = await client.post(
            f"{gateway_url}/api/orders/_control",
            json={
                "delay_ms": 0,
                "error_status_code": 503,
                "error_probability": 1.0,
            },
        )
        assert control.status_code == 200

        response = await client.post(
            f"{gateway_url}/api/orders/items",
            headers={"X-Request-Id": request_id},
            json={"item": "phone"},
        )

        assert response.status_code == 503

        requests_response = await client.get(
            f"{orders_internal_url}/_requests",
            params={"request_id": request_id},
        )

        items = requests_response.json()["requests"]
        assert len(items) == 1

        # Возвращаем нормальное поведение.
        reset = await client.post(
            f"{gateway_url}/api/orders/_control",
            json={
                "delay_ms": 10,
                "error_status_code": 500,
                "error_probability": 0.0,
            },
        )
        assert reset.status_code == 200


@pytest.mark.asyncio
async def test_redis_circuit_breaker(redis_client):
    """
    Проверяет работу circuit breaker на реальном Redis.
    """
    settings = Settings(
        _env_file=None,
        circuit_enabled=True,
        circuit_failure_threshold=2,
        circuit_cooldown_ms=5000,
    )

    circuit = RedisCircuitBreaker(redis_client, settings)
    service = f"cb-test-{uuid.uuid4().hex}"

    await circuit.record_failure(service)
    await circuit.ensure_allowed(service)

    await circuit.record_failure(service)

    with pytest.raises(CircuitOpenError):
        await circuit.ensure_allowed(service)

    await circuit.record_success(service)

    # После успеха цепь должна закрыться.
    await circuit.ensure_allowed(service)