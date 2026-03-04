# tests/test_database.py

import os

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

# Import a model to use for testing
from examples.models import Hero

# Import the context manager we are testing
from ormodel import SessionContextError
from ormodel.database import (
    database_context,
    get_engine,
    get_session,
    get_session_from_context,
    init_database,
    shutdown_database,
)

# Mark all tests in this module to use pytest-asyncio


async def test_get_session_commits_on_success(test_engine: AsyncEngine):
    """
    Verify that the get_session context manager commits changes when the
    block finishes without an error.
    """
    hero_name = "Committing Hero"
    created_hero_id = None

    # --- Step 1: Create an object inside the context manager ---
    async with get_session():
        # The session is provided by the context manager and is in our context var
        hero = await Hero.objects.create(name=hero_name, secret_name="Success")
        assert hero.id is not None
        created_hero_id = hero.id

    # The context manager has now exited. The commit should have happened.

    # --- Step 2: Verify the object exists in a new, separate session ---
    # We create a raw session directly from the engine to ensure isolation.
    verifier_session_factory = async_sessionmaker(bind=test_engine, class_=AsyncSession)
    async with verifier_session_factory() as session:
        retrieved_hero = await session.get(Hero, created_hero_id)
        assert retrieved_hero is not None
        assert retrieved_hero.name == hero_name


async def test_get_session_rolls_back_on_error(db_session: AsyncSession, test_engine: AsyncEngine):
    """
    Verify that the get_session context manager rolls back changes when an
    exception is raised inside the block.
    """
    hero_name = "Rolling Back Hero"
    # The `db_session` fixture gives us a clean slate for counting
    initial_count = await Hero.objects.count()

    # --- Step 1: Attempt to create an object but raise an error ---
    with pytest.raises(ValueError, match="Forcing a rollback"):
        async with get_session():
            await Hero.objects.create(name=hero_name, secret_name="Failure")
            # The hero should exist *within* the transaction
            assert await Hero.objects.count() == initial_count + 1
            raise ValueError("Forcing a rollback")

    # The context manager has caught the exception and should have rolled back.

    # --- Step 2: Verify the object does NOT exist in a new session ---
    final_count = await Hero.objects.count()
    assert final_count == initial_count


async def test_get_engine_returns_initialized_engine():
    """get_engine() should return the initialized async engine."""
    engine = get_engine()
    assert isinstance(engine, AsyncEngine)


async def test_get_session_from_context_raises_without_active_session():
    """get_session_from_context() should fail when called outside get_session()."""
    with pytest.raises(SessionContextError):
        get_session_from_context()


async def test_get_session_from_context_returns_current_session():
    """get_session_from_context() should return the active session inside get_session()."""
    async with get_session() as session:
        current = get_session_from_context()
        assert current is session


async def test_shutdown_and_init_database_cycle():
    """shutdown_database() should disable sessions until init_database() is called again."""
    database_url = os.environ["DATABASE_URL"]

    await shutdown_database()

    with pytest.raises(RuntimeError, match="not initialized"):
        async with get_session():
            pass

    init_database(database_url, echo_sql=False)
    async with get_session() as session:
        assert session is not None


async def test_database_context_initializes_and_shuts_down(tmp_path):
    """database_context() should initialize on enter and shutdown on exit."""
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'database_context.db'}"
    default_database_url = os.environ["DATABASE_URL"]

    await shutdown_database()
    with pytest.raises(RuntimeError, match="not initialized"):
        get_engine()

    async with database_context(database_url, echo_sql=False):
        engine = get_engine()
        assert isinstance(engine, AsyncEngine)
        async with get_session() as session:
            assert get_session_from_context() is session

    with pytest.raises(RuntimeError, match="not initialized"):
        get_engine()

    # Restore the default test DB initialization for any in-test follow-up usage.
    init_database(default_database_url, echo_sql=False)


async def test_init_database_skips_if_already_initialized():
    """init_database() should skip initialization if an engine already exists."""
    engine_before = get_engine()
    init_database("sqlite+aiosqlite:///./some_other.db")
    engine_after = get_engine()
    assert engine_before is engine_after


async def test_init_database_raises_on_invalid_url():
    """init_database() should raise RuntimeError on invalid URL."""
    await shutdown_database()
    with pytest.raises(RuntimeError, match="Failed to initialize database"):
        # Use an invalid protocol/URL that create_async_engine might fail on early or during factory setup
        # Note: some drivers only fail on actual connect, but we want to trigger the except block in init_database
        init_database("invalid://protocol")

    # Restore for other tests
    init_database(os.environ["DATABASE_URL"])


async def test_shutdown_database_skips_if_already_shutdown():
    """shutdown_database() should return early if already shut down."""
    await shutdown_database()
    # Calling it again should not raise anything and just return
    await shutdown_database()
    # Restore for other tests
    init_database(os.environ["DATABASE_URL"])


async def test_shutdown_database_logs_error_on_exception(monkeypatch):
    """shutdown_database() should catch and log exceptions during engine.dispose()."""

    # Create a mock engine with a dispose method that raises
    class MockEngine:
        async def dispose(self):
            raise Exception("Dispose error")

    # We need to bypass the read-only nature of the real engine
    # So we replace the global _engine variable in the module
    import ormodel.database

    mock_engine = MockEngine()
    monkeypatch.setattr(ormodel.database, "_engine", mock_engine)
    # Also need to set _is_shutdown to False so it tries to dispose
    monkeypatch.setattr(ormodel.database, "_is_shutdown", False)

    # Should not raise, just log
    await shutdown_database()

    # Restore for other tests (init_database will overwrite the mock)
    init_database(os.environ["DATABASE_URL"])
