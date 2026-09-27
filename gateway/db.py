import logging
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .config import Settings

logger = logging.getLogger("gateway.db")


class Base(DeclarativeBase):
    """
    Базовый класс для моделей.
    """


class RequestAudit(Base):
    """
    Аудит запросов через шлюз.

    Используется для интеграционных тестов и отладки.
    """

    __tablename__ = "request_audit"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    request_id: Mapped[str] = mapped_column(
        String(64),
        index=True,
    )

    service: Mapped[str] = mapped_column(
        String(32),
        index=True,
    )

    method: Mapped[str] = mapped_column(
        String(10),
    )

    path: Mapped[str] = mapped_column(
        String(2048),
    )

    status_code: Mapped[int] = mapped_column(
        Integer,
    )

    outcome: Mapped[str] = mapped_column(
        String(32),
    )

    duration_ms: Mapped[int] = mapped_column(
        Integer,
    )


def create_engine(settings: Settings) -> AsyncEngine:
    """
    Создаёт асинхронный движок SQLAlchemy.
    """
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """
    Создаёт фабрику сессий.
    """
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )


async def save_audit(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    request_id: str,
    service: str,
    method: str,
    path: str,
    status_code: int,
    outcome: str,
    duration_ms: int,
) -> None:
    """
    Сохраняет аудит запроса.

    Если запись не удалась, логируем ошибку, но не роняем запрос.
    """
    try:
        async with session_factory() as session:
            session.add(
                RequestAudit(
                    request_id=request_id,
                    service=service,
                    method=method,
                    path=path[:2048],
                    status_code=status_code,
                    outcome=outcome,
                    duration_ms=duration_ms,
                )
            )
            await session.commit()
    except Exception:
        logger.exception("Не удалось записать аудит")