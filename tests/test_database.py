# tests/test_database.py

import asyncio
import os

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlalchemy.pool import NullPool, StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession

# Import a model to use for testing
from examples.models import Hero

# Import the context manager we are testing
from ormodel import SessionContextError
from ormodel.database import (
    DEFAULT_SQLITE_BUSY_TIMEOUT_MS,
    _is_sqlite_file_database,
    _set_sqlite_pragmas,
    database_context,
    get_engine,
    get_session,
    get_session_from_context,
    init_database,
    shutdown_database,
)

# Mark all tests in this module to use pytest-asyncio


class FakeCursor:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.fetchone_calls = 0
        self.closed = False

    def execute(self, statement: str) -> None:
        self.statements.append(statement)

    def fetchone(self) -> tuple[str]:
        self.fetchone_calls += 1
        return ("wal",)

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> FakeCursor:
        return self._cursor


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


async def test_database_context_rejects_nested_usage(tmp_path):
    """A nested database context should fail without shutting down the outer context."""
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'nested_database_context.db'}"
    default_database_url = os.environ["DATABASE_URL"]

    await shutdown_database()
    async with database_context(database_url, echo_sql=False):
        outer_engine = get_engine()

        with pytest.raises(RuntimeError, match="Nested database_context usage is not supported"):
            async with database_context(database_url, echo_sql=False):
                pass

        assert get_engine() is outer_engine

    with pytest.raises(RuntimeError, match="not initialized"):
        get_engine()

    # Restore the default test DB initialization for any in-test follow-up usage.
    init_database(default_database_url, echo_sql=False)


async def test_database_context_reuses_existing_context_when_requested(tmp_path):
    """An opted-in nested context should reuse the engine without owning its lifecycle."""
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'reused_database_context.db'}"
    default_database_url = os.environ["DATABASE_URL"]

    await shutdown_database()
    async with database_context(database_url, echo_sql=False):
        outer_engine = get_engine()

        async with database_context(database_url, echo_sql=False, reuse_existing=True):
            assert get_engine() is outer_engine

        assert get_engine() is outer_engine

    with pytest.raises(RuntimeError, match="not initialized"):
        get_engine()

    # Restore the default test DB initialization for any in-test follow-up usage.
    init_database(default_database_url, echo_sql=False)


async def test_database_context_rejects_reusing_different_database(tmp_path):
    """An opted-in nested context should not silently ignore a different URL."""
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'outer_database_context.db'}"
    other_database_url = f"sqlite+aiosqlite:///{tmp_path / 'other_database_context.db'}"
    default_database_url = os.environ["DATABASE_URL"]

    await shutdown_database()
    async with database_context(database_url, echo_sql=False):
        outer_engine = get_engine()

        with pytest.raises(RuntimeError, match="different database URL"):
            async with database_context(other_database_url, echo_sql=False, reuse_existing=True):
                pass

        assert get_engine() is outer_engine

    # Restore the default test DB initialization for any in-test follow-up usage.
    init_database(default_database_url, echo_sql=False)


async def test_database_context_rejects_reusing_different_echo_setting(tmp_path):
    """An opted-in nested context should not silently ignore a different echo setting."""
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'echo_database_context.db'}"
    default_database_url = os.environ["DATABASE_URL"]

    await shutdown_database()
    async with database_context(database_url, echo_sql=False):
        outer_engine = get_engine()

        with pytest.raises(RuntimeError, match="different echo_sql setting"):
            async with database_context(database_url, echo_sql=True, reuse_existing=True):
                pass

        assert get_engine() is outer_engine

    # Restore the default test DB initialization for any in-test follow-up usage.
    init_database(default_database_url, echo_sql=False)


async def test_database_context_rejects_reuse_from_different_task(tmp_path):
    """An unrelated task should not borrow an active context with an unsafe lifetime."""
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'task_database_context.db'}"
    default_database_url = os.environ["DATABASE_URL"]

    async def reuse_database_context() -> None:
        async with database_context(database_url, echo_sql=False, reuse_existing=True):
            pass

    await shutdown_database()
    async with database_context(database_url, echo_sql=False):
        outer_engine = get_engine()

        with pytest.raises(RuntimeError, match="different task"):
            await asyncio.create_task(reuse_database_context())

        assert get_engine() is outer_engine

    # Restore the default test DB initialization for any in-test follow-up usage.
    init_database(default_database_url, echo_sql=False)


def test_set_sqlite_pragmas_for_file_database():
    """File-backed SQLite should get lock-friendly and WAL PRAGMAs."""
    cursor = FakeCursor()

    _set_sqlite_pragmas(FakeConnection(cursor), make_url("sqlite+aiosqlite:///example.db"), 1234)

    assert cursor.statements == [
        "PRAGMA busy_timeout = 1234",
        "PRAGMA foreign_keys = ON",
        "PRAGMA journal_mode = WAL",
        "PRAGMA synchronous = NORMAL",
    ]
    assert cursor.fetchone_calls == 1
    assert cursor.closed is True


def test_set_sqlite_pragmas_for_memory_database_skips_wal():
    """In-memory SQLite should not attempt file-backed WAL configuration."""
    cursor = FakeCursor()

    _set_sqlite_pragmas(FakeConnection(cursor), make_url("sqlite+aiosqlite:///:memory:"), 1234)

    assert cursor.statements == [
        "PRAGMA busy_timeout = 1234",
        "PRAGMA foreign_keys = ON",
    ]
    assert cursor.fetchone_calls == 0
    assert cursor.closed is True


@pytest.mark.parametrize(
    ("database_url", "expected"),
    [
        ("sqlite+aiosqlite:///:memory:", False),
        ("sqlite+aiosqlite:///file::memory:?cache=shared&uri=true", False),
        ("sqlite+aiosqlite:///file:memdb1?mode=memory&cache=shared&uri=true", False),
        ("sqlite+aiosqlite:///example.db", True),
    ],
)
def test_is_sqlite_file_database_handles_memory_uri_forms(database_url: str, expected: bool):
    assert _is_sqlite_file_database(make_url(database_url)) is expected


async def test_init_database_configures_sqlite_pragmas(tmp_path):
    """SQLite engines should enable lock-friendly defaults for concurrent access."""
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'sqlite_pragmas.db'}"
    default_database_url = os.environ["DATABASE_URL"]

    await shutdown_database()
    init_database(database_url, echo_sql=False)

    try:
        engine = get_engine()
        assert isinstance(engine.sync_engine.pool, NullPool)
        assert engine.sync_engine.pool._pre_ping is False

        async with engine.connect() as conn:
            busy_timeout = await conn.exec_driver_sql("PRAGMA busy_timeout")
            foreign_keys = await conn.exec_driver_sql("PRAGMA foreign_keys")
            journal_mode = await conn.exec_driver_sql("PRAGMA journal_mode")
            synchronous = await conn.exec_driver_sql("PRAGMA synchronous")

            assert busy_timeout.scalar_one() == DEFAULT_SQLITE_BUSY_TIMEOUT_MS
            assert foreign_keys.scalar_one() == 1
            assert journal_mode.scalar_one().lower() == "wal"
            assert synchronous.scalar_one() == 1
    finally:
        await shutdown_database()
        init_database(default_database_url, echo_sql=False)


async def test_init_database_keeps_plain_in_memory_sqlite_on_static_pool():
    """Plain in-memory SQLite should keep SQLAlchemy's StaticPool default."""
    default_database_url = os.environ["DATABASE_URL"]

    await shutdown_database()
    init_database("sqlite+aiosqlite:///:memory:", echo_sql=False)

    try:
        engine = get_engine()
        assert isinstance(engine.sync_engine.pool, StaticPool)

        async with engine.begin() as conn:
            await conn.exec_driver_sql("CREATE TABLE example (id INTEGER PRIMARY KEY)")

        async with engine.connect() as conn:
            result = await conn.exec_driver_sql(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'example'"
            )
            assert result.scalar_one() == 1
    finally:
        await shutdown_database()
        init_database(default_database_url, echo_sql=False)


async def test_init_database_keeps_shared_memory_sqlite_across_simultaneous_connections():
    """Shared-cache in-memory SQLite should remain visible across simultaneous connections."""
    default_database_url = os.environ["DATABASE_URL"]

    await shutdown_database()
    init_database("sqlite+aiosqlite:///file::memory:?cache=shared&uri=true", echo_sql=False)

    try:
        engine = get_engine()
        async with engine.connect() as writer:
            async with engine.connect() as reader:
                await writer.exec_driver_sql("CREATE TABLE example (id INTEGER PRIMARY KEY)")
                await writer.commit()

                result = await reader.exec_driver_sql(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'example'"
                )
            assert result.scalar_one() == 1
    finally:
        await shutdown_database()
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
