import ssl
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import certifi
from fastapi import Request
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import Settings
from .models import Base


def verified_ssl_context(ca_cert_file: Path | None = None) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=certifi.where())
    if sys.platform == "win32":
        for certificate, encoding, _trust in ssl.enum_certificates("ROOT"):
            if encoding == "x509_asn":
                context.load_verify_locations(cadata=certificate)
    if ca_cert_file is not None:
        context.load_verify_locations(cafile=ca_cert_file)
    return context


def database_connect_args(
    database_url: str,
    ssl_mode: str,
    ca_cert_file: Path | None = None,
) -> dict[str, object]:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    if ssl_mode == "verify-full":
        # Verify both the certificate chain and the database hostname.
        return {"ssl": verified_ssl_context(ca_cert_file)}
    return {"ssl": False}


class Database:
    def __init__(self, settings: Settings) -> None:
        database_url = settings.resolved_database_url
        self.engine: AsyncEngine = create_async_engine(
            database_url,
            connect_args=database_connect_args(
                database_url,
                settings.database_ssl_mode,
                settings.database_ca_cert_file,
            ),
            hide_parameters=True,
            pool_pre_ping=not database_url.startswith("sqlite"),
        )
        if database_url.startswith("sqlite"):
            event.listen(self.engine.sync_engine, "connect", self._enable_sqlite_foreign_keys)
        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
            autoflush=False,
        )

    @staticmethod
    def _enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async def create_schema(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    database: Database = request.app.state.database
    async with database.session_factory() as session:
        yield session
