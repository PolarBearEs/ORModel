import contextvars
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlmodel import SQLModel # Needed for metadata later

from .config import get_settings

settings = get_settings()

# Create the async engine
try:
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.ECHO_SQL,
        future=True, # Use SQLAlchemy 2.0 style
        pool_pre_ping=True, # Good practice for checking connections
    )
except Exception as e:
    print(f"Error creating async engine with URL {settings.DATABASE_URL}: {e}")
    # Depending on the application, you might want to raise this
    # or handle it to allow configuration checks without a running DB
    raise

# Create a session factory
AsyncSessionFactory = async_sessionmaker(
    bind=engine, # Bind the factory to the engine
    class_=AsyncSession,
    expire_on_commit=False, # Recommended for async/FastAPI usage
)

# Context variable to hold the current session
# This is key to making the manager work without explicitly passing the session
db_session_context: contextvars.ContextVar[Optional[AsyncSession]] = \
    contextvars.ContextVar("db_session_context", default=None)

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency/Context manager to get a database session.
    Ensures the session is set in the context variable and closed properly.
    """
    session = db_session_context.get()
    token = None
    if session is not None and session.is_active:
        # Session already exists in context and is active, yield it directly
        # This can happen with nested dependencies/calls using the same context
        yield session
    else:
        # Create a new session and set it in the context
        # print("Creating new session") # Debug print
        async with AsyncSessionFactory() as new_session:
            token = db_session_context.set(new_session)
            try:
                yield new_session
                # Commit is typically handled by middleware or calling code
            except Exception:
                # print("Rolling back session due to exception") # Debug print
                await new_session.rollback()
                raise
            finally:
                # print("Closing session / Resetting context") # Debug print
                # Reset the context variable to its previous state if we set it
                if token:
                    db_session_context.reset(token)

def get_session_from_context() -> AsyncSession:
    """
    Retrieves the session from the context variable.
    Raises RuntimeError if the session is not set or inactive.
    """
    session = db_session_context.get()
    if session is None:
        raise RuntimeError(
            "No database session found in context. "
            "Ensure 'get_session' context manager/dependency is used "
            "before accessing the manager."
        )
    # Optional: Check if session is active
    # if not session.is_active:
    #    raise RuntimeError("Database session in context is not active.")
    return session

# This metadata object is needed by Alembic
# Models defined using SQLModel's subclass (from .base) will automatically register here
# IF the modules containing the model definitions are imported before Alembic needs the metadata.
metadata = SQLModel.metadata