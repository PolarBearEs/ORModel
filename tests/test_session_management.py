import pytest
from ormodel import get_session
from examples.models import Hero


async def test_manual_session_commits_on_success():
    """
    Verify that when using an explicit `async with get_session()`,
    ORM operations work correctly and are committed upon successful exit.
    """
    manual_hero_name = "Manual Success Hero"
    created_hero_id = None

    # --- Step 1: Create an object inside an explicit session context ---
    async with get_session():
        # The session is provided by the context manager and is in our context var
        hero = await Hero.objects.create(name=manual_hero_name, secret_name="Manual")
        assert hero.id is not None

        # Verify we can fetch the hero within the same transaction
        fetched_hero = await Hero.objects.get(id=hero.id)
        assert fetched_hero.name == manual_hero_name
        created_hero_id = hero.id

    # The context manager has now exited. The commit should have happened.

    # --- Step 2: Verify the object exists in a new, separate session ---
    # This .get() will use its own automatic session.
    retrieved_hero = await Hero.objects.get(id=created_hero_id)
    assert retrieved_hero is not None
    assert retrieved_hero.name == manual_hero_name


async def test_manual_session_rolls_back_on_error():
    """
    Verify that when using an explicit `async with get_session()`,
    ORM operations are rolled back if an exception occurs inside the block.
    """
    rollback_hero_name = "Manual Rollback Hero"
    initial_count = await Hero.objects.count()

    # --- Step 1: Attempt to create an object but raise an error ---
    with pytest.raises(ValueError, match="Forcing a rollback"):
        async with get_session():
            await Hero.objects.create(name=rollback_hero_name, secret_name="Failure")
            # The hero should exist *within* this transaction before the rollback
            assert await Hero.objects.count() == initial_count + 1
            # Raise an exception to trigger the rollback logic in get_session()
            raise ValueError("Forcing a rollback")

    # The context manager has caught the exception and should have rolled back.

    # --- Step 2: Verify the object does NOT exist and the count is unchanged ---
    # This .count() will use its own automatic session.
    final_count = await Hero.objects.count()
    assert final_count == initial_count


async def test_automatic_session_creation_works():
    """
    Verify that calling a manager method outside of an explicit session
    context automatically creates a session for the operation and commits it.
    """
    auto_hero_name = "Auto Hero"

    # --- Step 1: Call .create() with NO explicit session context ---
    # The metaclass wrapper should create and manage the session automatically.
    hero = await Hero.objects.create(name=auto_hero_name, secret_name="Automatic")
    assert hero.id is not None

    # --- Step 2: Verify the object exists by fetching it ---
    # This .get() call will ALSO create its own session automatically.
    retrieved_hero = await Hero.objects.get(id=hero.id)
    assert retrieved_hero is not None
    assert retrieved_hero.name == auto_hero_name
