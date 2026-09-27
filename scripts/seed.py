import asyncio
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway.config import get_settings
from gateway.db import RequestAudit


async def main() -> None:
    """
    Наполнение базы демонстрационными данными.

    Сид идемпотентный: если данные уже есть, повторная вставка не выполняется.
    """
    settings = get_settings()

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with session_factory() as session:
        result = await session.execute(
            select(func.count()).select_from(RequestAudit)
        )
        count = result.scalar_one()

        if count > 0:
            print("Database already seeded")
            await engine.dispose()
            return

        for index in range(20):
            session.add(
                RequestAudit(
                    request_id=uuid.uuid4().hex,
                    service="users",
                    method="GET",
                    path=f"/seed/{index}",
                    status_code=200,
                    outcome="success",
                    duration_ms=5,
                )
            )

        await session.commit()

    await engine.dispose()
    print("Seed completed")


if __name__ == "__main__":
    asyncio.run(main())