import asyncio
import sys
from pathlib import Path

# Добавляем корень проекта в sys.path, чтобы импорты вида
# "from gateway.config import ..." работали независимо от способа запуска.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from gateway.config import get_settings


async def main() -> None:
    """
    SQL-миграции
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url)

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS request_audit (
                    id SERIAL PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    request_id VARCHAR(64) NOT NULL,
                    service VARCHAR(32) NOT NULL,
                    method VARCHAR(10) NOT NULL,
                    path VARCHAR(2048) NOT NULL,
                    status_code INTEGER NOT NULL,
                    outcome VARCHAR(32) NOT NULL,
                    duration_ms INTEGER NOT NULL
                );
                """
            )
        )

        await conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_request_audit_request_id
                ON request_audit (request_id);
                """
            )
        )

        await conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_request_audit_service
                ON request_audit (service);
                """
            )
        )

    await engine.dispose()
    print("Migration completed")


if __name__ == "__main__":
    asyncio.run(main())