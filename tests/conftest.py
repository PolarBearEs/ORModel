# tests/conftest.py

import asyncio
import contextvars
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Generator, Optional

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine, create_async_engine, async_sessionmaker
)
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

# --- Import library components INCLUDING METADATA ---
from ormodel import (
    ORModel, db_session_context, metadata, # <-- IMPORT METADATA HERE
    # Import based on which refactor you chose:
    # "Move config out" version:
    init_database, get_session as original_get_session, get_engine as library_get_engine
    # "Move config/db out" version would just be db_session_context, get_session_from_context
)
# --- Import original engine for comparison if needed ---
# from ormodel.database import engine as original_engine # Only if using "move config out"

from examples.api import app as fastapi_app


# --- Test Database URL ---
TEST_DATABASE_URL = "sqlite+aiosqlite:////app/data/default.db"

# --- Fixtures ---

@pytest.fixture(scope="session")
def event_loop():
    """Creates an instance of the default event loop for the session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest_asyncio.fixture(scope="session")
async def test_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Creates the dedicated TEST async engine for the test session."""
    print(f"\n--- Creating Test Engine (ID: {id(test_engine)}) for URL: {TEST_DATABASE_URL} ---")
    engine = create_async_engine(
        TEST_DATABASE_URL, echo=False, future=True, connect_args={"check_same_thread": False}
    )
    print(f"--- Test Engine created (instance ID: {id(engine)}) ---")
    yield engine
    print("\n--- Disposing Test Engine ---")
    await engine.dispose()


# --- CORRECTED create_drop_tables FIXTURE ---
@pytest_asyncio.fixture(scope="function", autouse=True)
async def create_drop_tables(test_engine: AsyncEngine) -> AsyncGenerator[None, None]:
    """
    (Auto-used) Creates tables using the TEST engine and the library's metadata
    before each test function and drops them afterwards.
    """
    print(f"\n---> [create_drop_tables] START (using Test Engine ID: {id(test_engine)})")
    # Uses the 'metadata' object imported from the 'ormodel' library package
    print(f"---> [create_drop_tables] Current metadata tables: {list(metadata.tables.keys())}")

    expected_tables = {'team', 'hero'}
    if not expected_tables.issubset(metadata.tables.keys()):
        print("!!!!!!!!!! ERROR: METADATA MISSING EXPECTED TABLES !!!!!!!!!!!")
        print(f"Expected: {expected_tables}")
        print(f"Found: {metadata.tables.keys()}")
        pytest.fail("Metadata is not populated correctly. Check model imports in conftest/library init.")

    try:
        async with test_engine.begin() as conn:
            print("---> [create_drop_tables] Running metadata.create_all...")
            # Ensure we use the correctly imported metadata
            await conn.run_sync(metadata.create_all)
            print("---> [create_drop_tables] metadata.create_all FINISHED.")
        print("---> [create_drop_tables] Tables CREATED successfully.")
    except Exception as e:
        print(f"!!!!!! ERROR during table creation: {type(e).__name__}: {e} !!!!!!")
        import traceback
        traceback.print_exc()
        pytest.fail(f"Failed to create tables: {e}")

    yield # Run the test

    print(f"\n---> [create_drop_tables] FINISH: Dropping tables (using Test Engine ID: {id(test_engine)})")
    try:
        async with test_engine.begin() as conn:
            print("---> [create_drop_tables] Running metadata.drop_all...")
            # Ensure we use the correctly imported metadata
            await conn.run_sync(metadata.drop_all)
            print("---> [create_drop_tables] metadata.drop_all FINISHED.")
        print("---> [create_drop_tables] Tables DROPPED successfully.")
    except Exception as e:
        print(f"!!!!!! WARNING: Error during table dropping: {type(e).__name__}: {e} !!!!!!")
# --- END OF CORRECTED FIXTURE ---


# --- Fixture to initialize the LIBRARY'S DB module (Only needed for "move config out" refactor) ---
@pytest.fixture(scope="function", autouse=True)
def init_library_for_test(test_engine: AsyncEngine):
    """Initializes ormodel.database to use the TEST database URL."""
    # This check prevents errors if init_database wasn't exported (e.g., "move config/db out")
    if callable(globals().get("init_database")):
        print(f"--- [init_library_for_test] Initializing library DB with test URL ({TEST_DATABASE_URL}) ---")
        try:
            # Initialize the library's internal engine/factory to use the TEST DB URL
            init_database(TEST_DATABASE_URL, echo_sql=False)
        except Exception as e:
            pytest.fail(f"Failed to initialize library database for test: {e}")
    else:
        print("--- [init_library_for_test] init_database not found in library, skipping library init. ---")

# --- Fixture providing the FastAPI app ---
@pytest.fixture(scope="function")
def app() -> FastAPI:
    """Fixture providing the FastAPI app instance."""
    if fastapi_app is None:
        pytest.fail("FastAPI app could not be imported.")
    # If using "move config out", the app relies on init_library_for_test (autouse=True)
    # If using "move config/db out", the app uses its own setup which needs to correctly use db_session_context
    print("--- [app fixture] Providing app instance ---")
    yield fastapi_app


@pytest_asyncio.fixture(scope="function")
async def async_client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Fixture providing httpx client configured for the app."""
    print("\n--- Creating HTTPX AsyncClient ---")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    print("--- HTTPX AsyncClient closed ---")


# --- Fixture for DIRECT DB access in tests (e.g., test_manager.py) ---
@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Provides a direct session fixture using the TEST engine."""
    DirectTestSessionFactory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    session: AsyncSession = DirectTestSessionFactory()
    token: Optional[contextvars.Token] = None
    # print(f"\n--- [db_session fixture] Creating direct session {id(session)} ---") # Debug
    try:
        token = db_session_context.set(session)
        yield session
        if session.is_active:
            try: await session.commit()
            except Exception: await session.rollback()
    except Exception:
        await session.rollback()
        raise
    finally:
        if token: db_session_context.reset(token)
        await session.close()