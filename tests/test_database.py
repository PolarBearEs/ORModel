# tests/test_database.py

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

# Import a model to use for testing
from examples.models import Hero

# Import the context manager we are testing
from ormodel.database import get_session

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
