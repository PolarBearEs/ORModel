# tests/conftest.py
import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

# Import your library's base components
from ormodel import ORModel, get_session, metadata, db_session_context

# Import models used for testing (reusing example models for simplicity)
# Make sure examples/models.py is importable
from examples.models import Hero, Team # Adjust import path if needed

# Use an in-memory SQLite database for testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest.fixture(scope="session")
def event_loop():
    """Creates an instance of the default event loop for the session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest_asyncio.fixture(scope="session")
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    """Creates an async engine for the test session."""
    # Connect_args are specific to SQLite for concurrent access in tests
    test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, future=True, connect_args={"check_same_thread": False})
    yield test_engine
    await test_engine.dispose()

@pytest_asyncio.fixture(scope="function", autouse=True)
async def create_drop_tables(engine: AsyncEngine) -> AsyncGenerator[None, None]:
    """Creates tables before each test function and drops them after."""
    # print("\n--- Creating tables ---") # Debug print
    async with engine.begin() as conn:
        # Ensure all models imported are reflected in the metadata
        # print(f"Metadata tables before create: {metadata.tables.keys()}") # Debug
        await conn.run_sync(metadata.create_all)
    # print("--- Tables created ---") # Debug print
    yield
    # print("\n--- Dropping tables ---") # Debug print
    async with engine.begin() as conn:
        await conn.run_sync(metadata.drop_all)
    # print("--- Tables dropped ---") # Debug print

@pytest_asyncio.fixture(scope="function")
async def db_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """
    Provides a database session fixture that also manages the context variable.
    This is crucial for the Manager to work correctly in tests.
    """
    # Create a session factory bound to the test engine
    from sqlalchemy.ext.asyncio import async_sessionmaker
    TestSessionFactory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Use the get_session context manager from your library
    # It will use the TestSessionFactory implicitly if engine is mocked/patched,
    # or we can ensure it uses the correct engine context.
    # For simplicity here, we assume get_session will work if the engine
    # used internally by ormodel.database is the test_engine.
    # A more robust way might involve patching or providing the engine.

    # Let's explicitly use the TestSessionFactory with the context manager pattern
    # Ensure the ormodel context var is set correctly.
    token = None
    session: AsyncSession | None = None
    try:
        async with TestSessionFactory() as test_session:
            session = test_session # Keep ref
            # Set the context variable for the duration of the test
            token = db_session_context.set(test_session)
            # print(f"--- DB Session {id(test_session)} acquired ---") # Debug
            yield test_session
            # print(f"--- DB Session {id(test_session)} committing ---") # Debug
            await test_session.commit() # Commit changes made during the test
            # print(f"--- DB Session {id(test_session)} committed ---") # Debug
    except Exception:
        # print(f"--- DB Session {id(session) if session else 'N/A'} rolling back ---") # Debug
        if session:
            await session.rollback()
        raise # Re-raise the test exception
    finally:
        if token:
            db_session_context.reset(token)
            # print(f"--- DB Session context reset ---") # Debug