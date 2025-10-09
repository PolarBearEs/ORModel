# ormodel/database.py
import contextvars
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncEngine
from sqlalchemy import func
from .exceptions import SessionContextError

logger = logging.getLogger(__name__)

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None
_is_shutdown: bool = False

db_session_context: contextvars.ContextVar[Optional[AsyncSession]] = contextvars.ContextVar(
    "db_session_context", default=None
)


def init_database(database_url: str, echo_sql: bool = False):
    global _engine, _session_factory
    if _engine is not None:
        logger.debug("Database already initialized. Skipping.")
        return
    logger.debug("Initializing database with URL: %s", database_url)
    try:
        _engine = create_async_engine(database_url, echo=echo_sql, future=True, pool_pre_ping=True)
        _session_factory = async_sessionmaker(bind=_engine, class_=AsyncSession, expire_on_commit=False)
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
    token: Optional[contextvars.Token] = None
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
