import os

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def env_or_skip(name: str) -> str:
    """
    Возвращает переменную окружения или пропускает тест.

    Так локально можно запускать юнит-тесты без инфраструктуры,
    а интеграционные тесты будут работать в Docker.
    """
    value = os.getenv(name)
    if not value:
        pytest.skip(f"{name} is not set")
    return value


@pytest.fixture
def gateway_url() -> str:
    """
    Адрес шлюза.
    """
    return env_or_skip("GATEWAY_URL")


@pytest.fixture
def orders_internal_url() -> str:
    """
    Внутренний адрес сервиса orders.
    """
    return env_or_skip("ORDERS_INTERNAL_URL")


@pytest.fixture
def database_url() -> str:
    """
    Строка подключения к PostgreSQL.
    """
    return env_or_skip("DATABASE_URL")


@pytest.fixture
def redis_url() -> str:
    """
    Строка подключения к Redis.
    """
    return env_or_skip("REDIS_URL")


@pytest_asyncio.fixture
async def db_engine(database_url: str):
    """
    Асинхронный движок PostgreSQL.
    """
    engine = create_async_engine(database_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """
    Асинхронная сессия PostgreSQL.
    """
    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def redis_client(redis_url: str):
    """
    Асинхронный клиент Redis.
    """
    client = Redis.from_url(redis_url, decode_responses=True)
    yield client
    await client.aclose()