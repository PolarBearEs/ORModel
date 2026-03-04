# tests/test_manager.py
from enum import StrEnum

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import DetachedInstanceError

from examples.models import Hero, Team
from ormodel import DoesNotExist, MultipleObjectsReturned, get_session, get_session_from_context

# Mark all tests in this module to use pytest-asyncio


class SessionMode(StrEnum):
    WITH_SESSION = "with_session"
    AUTO_SESSION = "auto_session"


@pytest.fixture(
    params=list(SessionMode),
    ids=[mode.value.replace("_", "-") for mode in SessionMode],
)
def session_mode(request: pytest.FixtureRequest) -> SessionMode:
    """Runs each manager test in both explicit-session and auto-session modes."""
    return request.param


@pytest_asyncio.fixture(scope="function", autouse=True)
async def maybe_session(session_mode: SessionMode):
    """Provide a request-scoped session only for the explicit-session test mode."""
    if session_mode is SessionMode.WITH_SESSION:
        async with get_session():
            yield
    else:
        yield


async def test_create_hero():
    """Test creating a single Hero object."""
    hero_data = {"name": "Test Hero", "secret_name": "Tester", "age": 30}
    hero = await Hero.objects.create(**hero_data)

    assert hero.id is not None
    assert hero.name == hero_data["name"]
    assert hero.secret_name == hero_data["secret_name"]
    assert hero.age == hero_data["age"]

    # Verify it's in the DB using a separate query
    retrieved_hero = await Hero.objects.get(id=hero.id)
    assert retrieved_hero == hero


async def test_get_existing_hero():
    """Test retrieving an existing Hero."""
    hero = await Hero.objects.create(name="Getter", secret_name="Fetcher", age=40)
    retrieved_hero = await Hero.objects.get(id=hero.id)
    assert retrieved_hero is not None
    assert retrieved_hero.id == hero.id
    assert retrieved_hero.name == "Getter"


async def test_get_nonexistent_hero():
    """Test that getting a non-existent Hero raises DoesNotExist."""
    with pytest.raises(DoesNotExist):
        await Hero.objects.get(id=999)


async def test_get_multiple_results_raises_exception():
    """Test that get() raises MultipleObjectsReturned if >1 match."""
    await Hero.objects.create(name="SameName", secret_name="One", age=20)
    await Hero.objects.create(name="SameName", secret_name="Two", age=21)

    with pytest.raises(MultipleObjectsReturned):
        await Hero.objects.get(name="SameName")


async def test_filter_and_all():
    """Test filtering heroes and retrieving all matches."""
    await Hero.objects.create(name="Hero A", secret_name="A1", age=25)
    await Hero.objects.create(name="Hero B", secret_name="B1", age=35)
    await Hero.objects.create(name="Hero C", secret_name="C1", age=25)

    # Filter by age
    heroes_age_25 = await Hero.objects.filter(age=25).all()
    assert len(heroes_age_25) == 2
    names = sorted([h.name for h in heroes_age_25])
    assert names == ["Hero A", "Hero C"]

    # Filter by name
    hero_b = await Hero.objects.filter(name="Hero B").all()
    assert len(hero_b) == 1
    assert hero_b[0].secret_name == "B1"

    # Filter with no results
    no_heroes = await Hero.objects.filter(name="NonExistent").all()
    assert len(no_heroes) == 0


async def test_filter_chaining():
    """Test chaining multiple filters."""
    await Hero.objects.create(name="Chain", secret_name="One", age=30)
    await Hero.objects.create(name="Chain", secret_name="Two", age=40)
    await Hero.objects.create(name="Link", secret_name="Three", age=30)

    result = await Hero.objects.filter(name="Chain").filter(age=30).all()
    assert len(result) == 1
    assert result[0].secret_name == "One"


async def test_filter_with_greater_than_expression():
    """Comparison filters should use SQL expression arguments."""
    await Hero.objects.create(name="Junior", secret_name="J", age=17)
    await Hero.objects.create(name="Senior", secret_name="S", age=30)
    await Hero.objects.create(name="Veteran", secret_name="V", age=45)

    heroes = await Hero.objects.filter(Hero.age > 18).order_by(Hero.age).all()
    assert [hero.name for hero in heroes] == ["Senior", "Veteran"]


async def test_manager_first_returns_none_then_object():
    """Manager.first() returns None on empty tables and an object when rows exist."""
    assert await Hero.objects.first() is None

    hero_a = await Hero.objects.create(name="First A", secret_name="FA", age=21)
    hero_b = await Hero.objects.create(name="First B", secret_name="FB", age=22)

    first = await Hero.objects.first()
    assert first is not None
    assert first.id in {hero_a.id, hero_b.id}


async def test_manager_one_behavior():
    """Manager.one() handles empty, single-row, and multi-row result sets."""
    with pytest.raises(DoesNotExist):
        await Hero.objects.one()

    only_hero = await Hero.objects.create(name="Only Hero", secret_name="OH", age=31)
    result = await Hero.objects.one()
    assert result.id == only_hero.id

    await Hero.objects.create(name="Another Hero", secret_name="AH", age=32)
    with pytest.raises(MultipleObjectsReturned):
        await Hero.objects.one()


async def test_manager_one_or_none_behavior():
    """Manager.one_or_none() returns None/row and raises on multi-row result sets."""
    assert await Hero.objects.one_or_none() is None

    only_hero = await Hero.objects.create(name="Only For OON", secret_name="OON", age=27)
    result = await Hero.objects.one_or_none()
    assert result is not None
    assert result.id == only_hero.id

    await Hero.objects.create(name="Second For OON", secret_name="SOON", age=28)
    with pytest.raises(MultipleObjectsReturned):
        await Hero.objects.one_or_none()


async def test_manager_limit_and_offset():
    """Manager.limit()/offset() produce bounded result sets."""
    await Hero.objects.create(name="Limit 1", secret_name="L1", age=10)
    await Hero.objects.create(name="Limit 2", secret_name="L2", age=20)
    await Hero.objects.create(name="Limit 3", secret_name="L3", age=30)

    limited = await Hero.objects.limit(2).all()
    offset = await Hero.objects.offset(1).all()

    assert len(limited) == 2
    assert len(offset) == 2


async def test_query_first_limit_offset_with_ordering():
    """Query.first()/limit()/offset() work predictably when ordered."""
    await Hero.objects.create(name="Ordered 1", secret_name="O1", age=40)
    await Hero.objects.create(name="Ordered 2", secret_name="O2", age=20)
    await Hero.objects.create(name="Ordered 3", secret_name="O3", age=30)

    ordered_query = Hero.objects.filter().order_by(Hero.age)
    first = await ordered_query.first()
    limited = await ordered_query.limit(2).all()
    offset = await ordered_query.offset(1).all()

    assert first is not None
    assert first.age == 20
    assert [hero.age for hero in limited] == [20, 30]
    assert [hero.age for hero in offset] == [30, 40]


async def test_query_one_one_or_none_and_get():
    """Query.one()/one_or_none()/get() follow documented single-row semantics."""
    await Hero.objects.create(name="Query Solo", secret_name="QS", age=35)
    await Hero.objects.create(name="Query Multi", secret_name="QM1", age=50)
    await Hero.objects.create(name="Query Multi", secret_name="QM2", age=51)

    one = await Hero.objects.filter(name="Query Solo").one()
    assert one.secret_name == "QS"

    maybe_one = await Hero.objects.filter(name="Query Solo").one_or_none()
    assert maybe_one is not None
    assert maybe_one.id == one.id

    none_result = await Hero.objects.filter(name="Missing Query Hero").one_or_none()
    assert none_result is None

    with pytest.raises(DoesNotExist):
        await Hero.objects.filter(name="Missing Query Hero").one()

    with pytest.raises(MultipleObjectsReturned):
        await Hero.objects.filter(name="Query Multi").one()

    with pytest.raises(MultipleObjectsReturned):
        await Hero.objects.filter(name="Query Multi").one_or_none()

    fetched = await Hero.objects.filter(Hero.age >= 35).get(name="Query Solo")
    assert fetched.id == one.id


async def test_count_heroes():
    """Test counting heroes."""
    assert await Hero.objects.count() == 0

    await Hero.objects.create(name="Count 1", secret_name="C1", age=10)
    await Hero.objects.create(name="Count 2", secret_name="C2", age=20)
    await Hero.objects.create(name="Count 3", secret_name="C3", age=10)

    assert await Hero.objects.count() == 3
    assert await Hero.objects.filter(age=10).count() == 2
    assert await Hero.objects.filter(age=30).count() == 0


async def test_get_or_create_does_not_exist():
    """Test get_or_create when the object doesn't exist."""
    hero, created = await Hero.objects.get_or_create(name="New Hero", defaults={"secret_name": "Secret", "age": 22})
    assert created is True
    assert hero.id is not None
    assert hero.name == "New Hero"
    assert hero.secret_name == "Secret"
    assert hero.age == 22
    # Verify count
    assert await Hero.objects.count() == 1


async def test_get_or_create_exists():
    """Test get_or_create when the object already exists."""
    # Create initial hero
    initial_hero = await Hero.objects.create(name="Existing Hero", secret_name="Original", age=50)
    initial_id = initial_hero.id

    # Attempt get_or_create with the same name
    hero, created = await Hero.objects.get_or_create(
        name="Existing Hero",
        defaults={"secret_name": "Should Not Be Used", "age": 55},  # Defaults ignored
    )
    assert created is False
    assert hero.id == initial_id
    assert hero.name == "Existing Hero"
    assert hero.secret_name == "Original"  # Check it wasn't updated
    assert hero.age == 50
    # Verify count hasn't increased
    assert await Hero.objects.count() == 1


async def test_update_or_create_creates_new():
    """Test update_or_create when the object doesn't exist."""
    hero, created = await Hero.objects.update_or_create(
        name="UpdateOrCreate New", defaults={"secret_name": "UOC Secret", "age": 44}
    )
    assert created is True
    assert hero.id is not None
    assert hero.name == "UpdateOrCreate New"
    assert hero.secret_name == "UOC Secret"
    assert hero.age == 44
    assert await Hero.objects.count() == 1


async def test_update_or_create_updates_existing():
    """Test update_or_create when the object already exists."""
    initial_hero = await Hero.objects.create(name="UpdateMe", secret_name="Before", age=60)
    initial_id = initial_hero.id

    hero, created = await Hero.objects.update_or_create(
        name="UpdateMe",  # Match criteria
        defaults={"secret_name": "After", "age": 61},  # Values to update
    )

    assert created is False
    assert hero.id == initial_id
    assert hero.name == "UpdateMe"
    assert hero.secret_name == "After"  # Check secret_name was updated
    assert hero.age == 61  # Check age was updated
    assert await Hero.objects.count() == 1

    # Verify directly from DB
    refreshed_hero = await Hero.objects.get(id=initial_id)
    assert refreshed_hero.secret_name == "After"
    assert refreshed_hero.age == 61


async def test_delete_hero():
    """Test deleting a hero instance."""
    hero_to_delete = await Hero.objects.create(name="Deleter", secret_name="Temp", age=1)
    hero_id = hero_to_delete.id

    assert await Hero.objects.count() == 1

    # Delete the instance
    await hero_to_delete.delete()

    assert await Hero.objects.count() == 0

    # Verify it cannot be retrieved
    with pytest.raises(DoesNotExist):
        await Hero.objects.get(id=hero_id)


async def test_update_instance():
    """Test updating a hero instance directly."""
    hero = await Hero.objects.create(name="Updater", secret_name="Original", age=10)

    hero.name = "Updated Updater"
    hero.age = 11
    await hero.save()

    updated_hero = await Hero.objects.get(id=hero.id)
    assert updated_hero.name == "Updated Updater"
    assert updated_hero.age == 11
    assert updated_hero.secret_name == "Original"  # Should remain unchanged
    assert await Hero.objects.count() == 1


async def test_update_single_field():
    """Test updating a single field for multiple objects matching a filter."""
    await Hero.objects.create(name="Update Target 1", secret_name="Before", age=25)
    await Hero.objects.create(name="Update Target 2", secret_name="Before", age=25)
    await Hero.objects.create(name="Ignore Me", secret_name="Before", age=30)

    updated_count = await Hero.objects.filter(age=25).update(secret_name="After")

    assert updated_count == 2
    updated_heroes = await Hero.objects.filter(secret_name="After").all()
    assert len(updated_heroes) == 2
    for hero in updated_heroes:
        assert hero.age == 25

    ignored_hero = await Hero.objects.get(name="Ignore Me")
    assert ignored_hero.secret_name == "Before"


async def test_update_multiple_fields():
    """Test updating multiple fields at once."""
    await Hero.objects.create(name="Multi-Update", secret_name="Original", age=50)

    updated_count = await Hero.objects.filter(name="Multi-Update").update(secret_name="Updated Secret", age=51)

    assert updated_count == 1
    updated_hero = await Hero.objects.get(name="Multi-Update")
    assert updated_hero.secret_name == "Updated Secret"
    assert updated_hero.age == 51


async def test_update_with_no_matches():
    """Test that update returns 0 when no objects match the filter."""
    await Hero.objects.create(name="Existing Hero", secret_name="Exists", age=40)

    updated_count = await Hero.objects.filter(name="Non-Existent").update(age=99)

    assert updated_count == 0
    hero = await Hero.objects.get(name="Existing Hero")
    assert hero.age == 40


async def test_update_all_records():
    """Test updating all records by using an empty filter."""
    await Hero.objects.create(name="Hero 1", secret_name="A", age=10)
    await Hero.objects.create(name="Hero 2", secret_name="B", age=20)
    await Hero.objects.create(name="Hero 3", secret_name="C", age=30)

    total_heroes = await Hero.objects.count()
    assert total_heroes == 3

    updated_count = await Hero.objects.filter().update(age=100)

    assert updated_count == total_heroes
    final_count = await Hero.objects.filter(age=100).count()
    assert final_count == total_heroes


async def test_delete_with_filter():
    """Test deleting records matching a filter."""
    await Hero.objects.create(name="Delete A", secret_name="DA", age=10)
    await Hero.objects.create(name="Delete B", secret_name="DB", age=10)
    await Hero.objects.create(name="Keep C", secret_name="KC", age=30)

    deleted_count = await Hero.objects.filter(age=10).delete()

    assert deleted_count == 2
    assert await Hero.objects.count() == 1
    survivor = await Hero.objects.get(name="Keep C")
    assert survivor.age == 30


async def test_delete_all_records_via_manager():
    """Test deleting all records through manager delete()."""
    await Hero.objects.create(name="Delete All 1", secret_name="D1", age=10)
    await Hero.objects.create(name="Delete All 2", secret_name="D2", age=20)

    deleted_count = await Hero.objects.delete()

    assert deleted_count == 2
    assert await Hero.objects.count() == 0


async def test_bulk_create():
    """Manager.bulk_create() inserts all provided model instances."""
    heroes = [
        Hero(name="Bulk 1", secret_name="B1", age=18),
        Hero(name="Bulk 2", secret_name="B2", age=19),
        Hero(name="Bulk 3", secret_name="B3", age=20),
    ]

    created = await Hero.objects.bulk_create(heroes)

    assert len(created) == 3
    assert all(hero.id is not None for hero in created)
    assert await Hero.objects.count() == 3


async def test_create_with_relationship(session_mode: SessionMode):
    """Test creating objects with relationships."""
    team = await Team.objects.create(name="Test Team", headquarters="Test HQ")
    assert team.id is not None

    hero = await Hero.objects.create(name="Team Player", secret_name="TP", age=28, team_id=team.id)
    assert hero.id is not None
    assert hero.team_id == team.id

    retrieved_hero = await Hero.objects.get(id=hero.id)
    if session_mode is SessionMode.AUTO_SESSION:
        with pytest.raises(DetachedInstanceError):
            _ = retrieved_hero.team
    else:
        retrieved_team = retrieved_hero.team
        assert retrieved_team is not None
        assert retrieved_team.id == team.id
        assert retrieved_team.name == "Test Team"


async def test_filter_by_relationship():
    """Test filtering based on related model attributes."""
    team1 = await Team.objects.create(name="Team One", headquarters="HQ1")
    team2 = await Team.objects.create(name="Team Two", headquarters="HQ2")
    await Hero.objects.create(name="Hero 1", secret_name="H1", age=20, team_id=team1.id)
    await Hero.objects.create(name="Hero 2", secret_name="H2", age=30, team_id=team2.id)
    await Hero.objects.create(name="Hero 3", secret_name="H3", age=40, team_id=team1.id)

    team_one_heroes = await Hero.objects.filter(team_id=team1.id).order_by(Hero.name).all()
    assert len(team_one_heroes) == 2
    assert team_one_heroes[0].name == "Hero 1"
    assert team_one_heroes[1].name == "Hero 3"


async def test_join_with_relationship(session_mode: SessionMode):
    """Test joining models and filtering across relationships."""
    team_alpha = await Team.objects.create(name="Team Alpha", headquarters="Alpha HQ")
    team_beta = await Team.objects.create(name="Team Beta", headquarters="Beta HQ")

    await Hero.objects.create(name="Hero A", secret_name="SA", age=20, team_id=team_alpha.id)
    await Hero.objects.create(name="Hero B", secret_name="SB", age=30, team_id=team_beta.id)
    await Hero.objects.create(name="Hero C", secret_name="SC", age=25, team_id=team_alpha.id)

    # Join Hero with Team and filter by Team name
    heroes_from_alpha_team = await Hero.objects.join(Team).filter(Team.name == "Team Alpha").all()

    assert len(heroes_from_alpha_team) == 2
    names = sorted([h.name for h in heroes_from_alpha_team])
    assert names == ["Hero A", "Hero C"]

    if session_mode is SessionMode.AUTO_SESSION:
        with pytest.raises(DetachedInstanceError):
            for hero in heroes_from_alpha_team:
                assert hero.team.name == "Team Alpha"
    else:
        for hero in heroes_from_alpha_team:
            assert hero.team.name == "Team Alpha"


@pytest.mark.parametrize("commit", [True, False])
async def test_unique_constraint(session_mode: SessionMode, commit: bool):
    """Test that unique constraints are enforced (e.g., Team name)."""
    await Team.objects.create(name="UniqueTeam", headquarters="HQ Unique")
    assert await Team.objects.count() == 1
    if commit and session_mode is SessionMode.WITH_SESSION:
        await get_session_from_context().commit()

    with pytest.raises(IntegrityError):
        await Team.objects.create(name="UniqueTeam", headquarters="HQ Duplicate Attempt")

    expected_count = 1 if (session_mode is SessionMode.AUTO_SESSION or commit) else 0
    assert await Team.objects.count() == expected_count

@pytest.mark.asyncio
async def test_create_hero_and_save():
    """
    Test that a Hero can be created and saved to the database using the .save() method.
    """
    # 1. Create a Hero instance
    hero_name = "Test Hero"
    secret_identity = "Secret Test"
    await Hero(name=hero_name, secret_name=secret_identity, age=30).save()

    # 3. Verify the hero was saved by querying the database
    saved_hero = await Hero.objects.get(Hero.name == hero_name)

    assert saved_hero is not None
    assert saved_hero.name == hero_name
    assert saved_hero.secret_name == secret_identity
    assert saved_hero.id is not None
    assert saved_hero.age == 30


async def test_filter_raises_attribute_error_on_invalid_field():
    """Test that filter raises AttributeError when filtering by a non-existent field."""
    with pytest.raises(AttributeError, match="has no attribute 'invalid_field'"):
        await Hero.objects.filter(invalid_field="value")


async def test_one_raises_multiple_objects_returned_when_count_greater_than_one():
    """Test that one() raises MultipleObjectsReturned when more than one object is found."""
    await Hero.objects.create(name="Duplicate", secret_name="D1", age=20)
    await Hero.objects.create(name="Duplicate", secret_name="D2", age=20)

    # one() calls limit(2), so if 2 come back, it raises
    with pytest.raises(MultipleObjectsReturned, match="Expected one result for Hero, but found 2"):
        await Hero.objects.filter(name="Duplicate").one()


async def test_create_rolls_back_on_error(session_mode: SessionMode):
    """Test that create() rolls back the session on error."""
    # We can simulate an error by trying to create a duplicate if there's a unique constraint
    # Team name is unique
    await Team.objects.create(name="Unique Team", headquarters="HQ")
    
    # In WITH_SESSION mode, the first create is part of the current transaction.
    # The subsequent failing create will trigger a rollback on the session,
    # which would rollback the first create too if we don't commit it now.
    if session_mode == SessionMode.WITH_SESSION:
        await get_session_from_context().commit()

    with pytest.raises(IntegrityError):
        await Team.objects.create(name="Unique Team", headquarters="Another HQ")

    # Verify that the session is still usable or at least the DB is consistent
    assert await Team.objects.count() == 1


async def test_get_or_create_race_condition(monkeypatch):
    """
    Test the race condition where an object is created between get() and create() in get_or_create().
    """
    # 1. First get() raises DoesNotExist
    # 2. create() raises IntegrityError (simulating concurrent creation)
    # 3. Second get() succeeds

    original_get = Hero.objects.get
    original_create = Hero.objects.create
    
    call_count_get = 0

    async def mock_get(*args, **kwargs):
        nonlocal call_count_get
        call_count_get += 1
        if call_count_get == 1:
            raise DoesNotExist("Mock DoesNotExist")
        return await original_get(*args, **kwargs)

    async def mock_create(*args, **kwargs):
        # Create the object properly so the next get succeeds
        await original_create(*args, **kwargs)
        # But raise IntegrityError to simulate it was created by "someone else"
        raise IntegrityError("Mock IntegrityError", params={}, orig=Exception())

    monkeypatch.setattr(Hero.objects, "get", mock_get)
    monkeypatch.setattr(Hero.objects, "create", mock_create)

    # Use a unique name to ensure clean state
    hero, created = await Hero.objects.get_or_create(name="Race Hero", secret_name="Racer", age=25)

    assert created is False
    assert hero.name == "Race Hero"
    assert call_count_get == 2


async def test_update_or_create_race_condition(monkeypatch):
    """
    Test the race condition where an object is created between get() and create() in update_or_create().
    """
    # 1. First get() raises DoesNotExist
    # 2. create() raises IntegrityError
    # 3. Second get() succeeds

    original_get = Hero.objects.get
    original_create = Hero.objects.create
    
    call_count_get = 0

    async def mock_get(*args, **kwargs):
        nonlocal call_count_get
        call_count_get += 1
        if call_count_get == 1:
            raise DoesNotExist("Mock DoesNotExist")
        return await original_get(*args, **kwargs)

    async def mock_create(*args, **kwargs):
        # Create it so the retry get finds it
        await original_create(*args, **kwargs)
        raise IntegrityError("Mock IntegrityError", params={}, orig=Exception())

    monkeypatch.setattr(Hero.objects, "get", mock_get)
    monkeypatch.setattr(Hero.objects, "create", mock_create)

    hero, created = await Hero.objects.update_or_create(
        name="Race Update", 
        defaults={"secret_name": "Racer", "age": 30}
    )

    assert created is False
    assert hero.name == "Race Update"
    assert call_count_get == 2


async def test_get_or_create_integrity_error_persistent(monkeypatch):
    """
    Test get_or_create where create raises IntegrityError but the object is still not found.
    (e.g. constraint violation other than uniqueness, or instant deletion)
    """
    async def mock_get(*args, **kwargs):
        raise DoesNotExist("Mock DoesNotExist")

    async def mock_create(*args, **kwargs):
        raise IntegrityError("Mock IntegrityError", params={}, orig=Exception())

    monkeypatch.setattr(Hero.objects, "get", mock_get)
    monkeypatch.setattr(Hero.objects, "create", mock_create)

    with pytest.raises(IntegrityError, match="Mock IntegrityError"):
        await Hero.objects.get_or_create(name="Fail Hero", defaults={"age": 20})


async def test_update_or_create_integrity_error_persistent(monkeypatch):
    """
    Test update_or_create where create raises IntegrityError but the object is still not found.
    """
    async def mock_get(*args, **kwargs):
        raise DoesNotExist("Mock DoesNotExist")

    async def mock_create(*args, **kwargs):
        raise IntegrityError("Mock IntegrityError", params={}, orig=Exception())

    monkeypatch.setattr(Hero.objects, "get", mock_get)
    monkeypatch.setattr(Hero.objects, "create", mock_create)

    with pytest.raises(IntegrityError, match="Mock IntegrityError"):
        await Hero.objects.update_or_create(name="Fail Update", defaults={"age": 20})
