# ormodel/database.py
import contextvars
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel.ext.asyncio.session import AsyncSession

from .exceptions import SessionContextError

logger = logging.getLogger(__name__)

DEFAULT_SQLITE_BUSY_TIMEOUT_MS = 30_000

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_is_shutdown: bool = False

db_session_context: contextvars.ContextVar[AsyncSession | None] = contextvars.ContextVar(
    "db_session_context", default=None
)


def _is_sqlite_file_database(url: URL) -> bool:
    database = url.database
    return bool(database and database != ":memory:")


def _set_sqlite_pragmas(dbapi_connection: Any, url: URL, busy_timeout_ms: int) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
        cursor.execute("PRAGMA foreign_keys = ON")

        if _is_sqlite_file_database(url):
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.fetchone()
            cursor.execute("PRAGMA synchronous = NORMAL")
    finally:
        cursor.close()


def _configure_sqlite_engine(engine: AsyncEngine, url: URL, busy_timeout_ms: int) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas_on_connect(dbapi_connection: Any, connection_record: Any) -> None:
        del connection_record
        _set_sqlite_pragmas(dbapi_connection, url, busy_timeout_ms)


def init_database(database_url: str, echo_sql: bool = False):
    global _engine, _session_factory, _is_shutdown
    if _engine is not None:
        logger.debug("Database already initialized. Skipping.")
        return
    logger.debug("Initializing database with URL: %s", database_url)
    try:
        url = make_url(database_url)
        is_sqlite = url.get_backend_name() == "sqlite"
        engine_kwargs: dict[str, Any] = {
            "echo": echo_sql,
            "future": True,
            "pool_pre_ping": True,
        }

        if is_sqlite:
            engine_kwargs["connect_args"] = {"timeout": DEFAULT_SQLITE_BUSY_TIMEOUT_MS / 1000}
            if _is_sqlite_file_database(url):
                engine_kwargs["poolclass"] = NullPool

        _engine = create_async_engine(database_url, **engine_kwargs)

        if is_sqlite:
            _configure_sqlite_engine(_engine, url, DEFAULT_SQLITE_BUSY_TIMEOUT_MS)

        _session_factory = async_sessionmaker(bind=_engine, class_=AsyncSession, expire_on_commit=False)
        _is_shutdown = False
        logger.debug("Database initialized successfully (Engine ID: %s)", id(_engine))
    except Exception as e:
        logger.error("Error initializing database: %s", e, exc_info=True)
        _engine = None
        _session_factory = None
        raise RuntimeError(f"Failed to initialize database: {e}") from e


async def shutdown_database():
    global _engine, _session_factory, _is_shutdown
    if _is_shutdown or _engine is None:
        logger.debug("Shutdown: Engine not initialized or already shut down.")
        return
    logger.debug("Shutting down database (disposing Engine ID: %s)", id(_engine))
    try:
        await _engine.dispose()
        logger.debug("Engine disposed successfully.")
    except Exception as e:
        logger.error("Error disposing engine: %s", e, exc_info=True)
    finally:
        _engine = None
        _session_factory = None
        _is_shutdown = True


@asynccontextmanager
async def database_context(database_url: str, echo_sql: bool = False) -> AsyncGenerator[None, None]:
    try:
        init_database(database_url, echo_sql)
        logger.debug("Entered database_context, DB initialized.")
        yield
    finally:
        logger.debug("Exiting database_context, ensuring database shutdown...")
        await shutdown_database()
        logger.debug("Database shutdown process complete.")


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Provides a session that automatically commits on successful completion
    or rolls back on any exception.
    """
    if _session_factory is None or _engine is None:
        raise RuntimeError("ormodel.database not initialized. Call ormodel.init_database(...) first.")
    session: AsyncSession = _session_factory()
    token: contextvars.Token | None = None
    try:
        token = db_session_context.set(session)
        yield session
        # If the `yield` completes without any exceptions, we commit.
        if session.is_active:
            await session.commit()
    except Exception:
        # If any exception occurs in the `with` block, we roll back.
        logger.debug("Exception detected, rolling back session.")
        await session.rollback()
        raise
    finally:
        if token:
            db_session_context.reset(token)
        await session.close()


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("ormodel.database not initialized.")
    return _engine


def get_session_from_context() -> AsyncSession:
    session = db_session_context.get()
    if session is None:
        raise SessionContextError("No database session found in context.")
    return session
