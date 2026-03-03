import pytest
from sqlmodel import select

from examples.models import Hero
from ormodel import SessionContextError, get_session
from ormodel.manager import with_auto_session


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


@pytest.mark.asyncio
async def test_with_auto_session_wrapper():
    """
    Tests the _with_auto_session wrapper by calling a Manager method
    without an explicit session in context.
    """
    # Ensure no session is active in the context before calling the wrapped method
    # This is implicitly true if the test doesn't use db_session fixture
    # and doesn't explicitly call get_session().

    # Call a Manager method that is wrapped by _with_auto_session
    # Hero.objects.create() is a good candidate.
    hero = await Hero.objects.create(name="Auto Session Hero", secret_name="Auto Secret")

    assert hero.id is not None
    assert hero.name == "Auto Session Hero"

    # Verify the hero exists in the database using a separate, explicit session
    # to ensure the auto-session committed the changes.
    async with get_session() as session:
        retrieved_heroes_result = await session.exec(select(Hero))
        retrieved_heroes = retrieved_heroes_result.all()
        assert len(retrieved_heroes) == 1
        assert hero in retrieved_heroes


@pytest.mark.asyncio
async def test_manager_all_no_fixture():
    """
    Tests Manager.all() method by explicitly managing the session.
    """
    async with get_session() as session:  # noqa: F841
        # Ensure the database is empty initially
        assert await Hero.objects.count() == 0

        # Create a few heroes
        hero1 = await Hero.objects.create(name="No Fixture Hero 1", secret_name="NF Secret 1")
        hero2 = await Hero.objects.create(name="No Fixture Hero 2", secret_name="NF Secret 2")

        # Retrieve all heroes using Manager.all()
        all_heroes = await Hero.objects.all()

        assert len(all_heroes) == 2
        assert hero1 in all_heroes
        assert hero2 in all_heroes


@pytest.mark.asyncio
async def test_manager_all_with_auto_session_wrapper():
    """
    Tests the _with_auto_session wrapper by calling Manager.all()
    without an explicit session in context.
    """
    # Ensure no session is active in the context
    # Create a few heroes
    hero1 = await Hero.objects.create(name="Auto All Hero 1", secret_name="AA Secret 1")
    hero2 = await Hero.objects.create(name="Auto All Hero 2", secret_name="AA Secret 2")

    # Retrieve all heroes using Manager.all()
    all_heroes = await Hero.objects.all()

    assert len(all_heroes) == 2
    assert hero1 in all_heroes
    assert hero2 in all_heroes

    # Verify the heroes exist in the database using a separate, explicit session
    async with get_session() as session:
        retrieved_heroes_result = await session.exec(select(Hero))
        retrieved_heroes = retrieved_heroes_result.all()
        assert len(retrieved_heroes) == 2
        assert hero1 in retrieved_heroes
        assert hero2 in retrieved_heroes


@pytest.mark.asyncio
async def test_query_all_direct_no_fixture():
    # Create a few heroes using the manager (which will use this explicit session)
    hero1 = await Hero.objects.create(name="Direct Query No Fixture Hero 1", secret_name="DQNF Secret 1")
    hero2 = await Hero.objects.create(name="Direct Query No Fixture Hero 2", secret_name="DQNF Secret 2")

    # Retrieve all heroes using this direct Query object
    all_heroes = await Hero.objects.all()

    assert len(all_heroes) == 2
    assert hero1 in all_heroes
    assert hero2 in all_heroes


@pytest.mark.asyncio
async def test_query_filter_all_direct_no_fixture():
    # Create a few heroes using the manager (which will use this explicit session)
    hero1 = await Hero.objects.create(name="Direct Query No Fixture Hero 1", secret_name="DQNF Secret 1")
    hero2 = await Hero.objects.create(name="Direct Query No Fixture Hero 2", secret_name="DQNF Secret 2")

    # Retrieve all heroes using this direct Query object
    all_heroes = await Hero.objects.filter(Hero.secret_name == "DQNF Secret 1").order_by(Hero.name).all()

    assert len(all_heroes) == 1
    assert hero1 in all_heroes
    assert hero2 not in all_heroes


@pytest.mark.asyncio
async def test_with_auto_session_does_not_retry_internal_session_context_errors():
    """SessionContextError raised by method logic should not trigger a second execution."""

    class Probe:
        def __init__(self) -> None:
            self.calls = 0

        @with_auto_session
        async def run(self) -> None:
            self.calls += 1
            raise SessionContextError("internal error")

    probe = Probe()
    with pytest.raises(SessionContextError, match="internal error"):
        await probe.run()

    assert probe.calls == 1
