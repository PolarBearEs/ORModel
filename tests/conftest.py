# tests/conftest.py
import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

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
    async with AsyncSession(engine) as test_session:  # Use sqlmodel.AsyncSession
        token = db_session_context.set(test_session)
        try:
            yield test_session
            await test_session.commit()  # Commit changes made during the test
        except Exception:
            await test_session.rollback()  # Rollback on error
            raise  # Re-raise the exception
        finally:
            db_session_context.reset(token)  # Reset the context variable