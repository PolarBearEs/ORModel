import os
from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from examples.api import app as fastapi_app
from ormodel import (
    get_session,
    init_database,
    metadata,
    shutdown_database,
)


@pytest.fixture(scope="session", autouse=True)
def test_database_url(tmp_path_factory: pytest.TempPathFactory) -> Generator[str, None, None]:
    """Use an isolated database file for the entire test session."""
    previous_database_url = os.environ.get("DATABASE_URL")
    database_path = tmp_path_factory.mktemp("ormodel") / "test.db"
    database_url = f"sqlite+aiosqlite:///{database_path}"
    os.environ["DATABASE_URL"] = database_url
    yield database_url
    if previous_database_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous_database_url


@pytest_asyncio.fixture(scope="session")
async def test_engine(test_database_url: str) -> AsyncGenerator[AsyncEngine, None]:
    """Creates the dedicated TEST async engine for the test session."""
    engine = create_async_engine(
        test_database_url,
        echo=False,
        future=True,
        connect_args={"check_same_thread": False},
    )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function", autouse=True)
async def create_drop_tables(test_engine: AsyncEngine) -> AsyncGenerator[None, None]:
    """
    (Auto-used) Creates tables using the TEST engine and the library's metadata
    before each test function and drops them afterwards.
    """
    expected_tables = {"team", "hero"}
    if not expected_tables.issubset(metadata.tables.keys()):
        pytest.fail("Metadata is not populated correctly. Check model imports in conftest/library init.")

    try:
        async with test_engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
    except Exception as e:
        pytest.fail(f"Failed to create tables: {e}")

    yield

    try:
        async with test_engine.begin() as conn:
            await conn.run_sync(metadata.drop_all)
    except Exception as e:
        pytest.fail(f"Failed to drop tables: {e}")


@pytest_asyncio.fixture(scope="function", autouse=True)
async def init_library_for_test(test_database_url: str) -> AsyncGenerator[None, None]:
    """Initializes ormodel.database to use the TEST database URL."""
    await shutdown_database()
    init_database(test_database_url, echo_sql=False)
    yield


@pytest.fixture(scope="function")
def app() -> Generator[FastAPI, None, None]:
    """Fixture providing the FastAPI app instance."""
    if fastapi_app is None:
        pytest.fail("FastAPI app could not be imported.")
    yield fastapi_app


@pytest_asyncio.fixture(scope="function")
async def async_client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Fixture providing httpx client configured for the app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Provides a direct session for tests that need manual DB access.
    This now correctly wraps the library's own transactional `get_session`
    context manager, ensuring commits and rollbacks are handled consistently.
    """
    async with get_session() as session:
        yield session
