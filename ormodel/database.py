# ormodel/database.py
import contextvars
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

# --- Use AsyncSession from sqlmodel ---
from sqlmodel.ext.asyncio.session import AsyncSession
# --------------------------------------
from sqlalchemy.ext.asyncio import (
    async_sessionmaker, create_async_engine, AsyncEngine
)
# Keep func for count method later
from sqlalchemy import func

# Global variables
_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None
_is_shutdown: bool = False # Flag to prevent re-init after shutdown

# Context variable remains the same
db_session_context: contextvars.ContextVar[Optional[AsyncSession]] = \
    contextvars.ContextVar("db_session_context", default=None)

def init_database(database_url: str, echo_sql: bool = False):
    """Initializes the database engine and session factory."""
    global _engine, _session_factory
    if _engine is not None: return

    print(f"--- [ormodel.database] Initializing database with URL: {database_url} ---")
    try:
        _engine = create_async_engine(database_url, echo=echo_sql, future=True, pool_pre_ping=True)
        # --- Ensure sessionmaker uses the sqlmodel AsyncSession ---
        _session_factory = async_sessionmaker(
            bind=_engine,
            class_=AsyncSession, # Now correctly uses sqlmodel's AsyncSession
            expire_on_commit=False
        )
        # -----------------------------------------------------
        print(f"--- [ormodel.database] Database initialized successfully (Engine ID: {id(_engine)}) ---")
    except Exception as e:
        print(f"--- [ormodel.database] Error initializing database: {e} ---")
        _engine = None
        _session_factory = None
        raise RuntimeError(f"Failed to initialize database: {e}") from e

async def shutdown_database():
    """Disposes the database engine pool and marks as shutdown."""
    global _engine, _session_factory, _is_shutdown
    if _is_shutdown or _engine is None:
        print("--- [ormodel.database] Shutdown: Engine not initialized or already shut down. ---")
        return

    print(f"--- [ormodel.database] Shutting down database (disposing Engine ID: {id(_engine)}) ---")
    try:
        await _engine.dispose()
        print("--- [ormodel.database] Engine disposed successfully. ---")
    except Exception as e:
        print(f"--- [ormodel.database] Error disposing engine: {type(e).__name__}: {e} ---")
        # Decide if this should raise an error or just log
    finally:
        # Clear globals and mark as shutdown
        _engine = None
        _session_factory = None
        _is_shutdown = True

@asynccontextmanager
async def database_context(database_url: str, echo_sql: bool = False) -> AsyncGenerator[None, None]:
    """
    Async context manager to initialize and shut down the ORModel database.

    Handles calling init_database on entry and shutdown_database on exit.

    Args:
        database_url: The database connection URL.
        echo_sql: Whether to echo SQL statements (default: False).

    Yields:
        None
    """
    try:
        # init_database handles skipping if already initialized, but will raise
        # if called after shutdown.
        init_database(database_url, echo_sql)
        print("--- [database_context] Entered context, DB initialized. ---")
        yield # Code within the 'async with' block runs here
    finally:
        # shutdown_database handles skipping if already shutdown or not initialized
        print("--- [database_context] Exiting context, ensuring database shutdown... ---")
        await shutdown_database()
        print("--- [database_context] Database shutdown process complete. ---")

@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Provides a session from the initialized factory and manages context var."""
    if _session_factory is None or _engine is None:
        raise RuntimeError("ormodel.database not initialized. Call ormodel.init_database(...) first.")

    # Type hint now refers to sqlmodel's AsyncSession
    session: AsyncSession = _session_factory()
    token: Optional[contextvars.Token] = None
    try:
        token = db_session_context.set(session)
        yield session
    except Exception as e:
        await session.rollback()
        raise
    finally:
        if token:
            db_session_context.reset(token)
        await session.close()

def get_engine() -> AsyncEngine:
    """Returns the initialized database engine."""
    if _engine is None: raise RuntimeError("ormodel.database not initialized.")
    return _engine

def get_session_from_context() -> AsyncSession: # Type hint uses sqlmodel's AsyncSession
    """Retrieves the session from the context variable."""
    session = db_session_context.get()
    if session is None:
        raise RuntimeError("No database session found in context.")
    return session