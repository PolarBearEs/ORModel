# tests/test_manager.py
import pytest
from sqlalchemy.exc import IntegrityError # To test unique constraints

# Import your library's exceptions and base model
from ormodel import DoesNotExist, MultipleObjectsReturned, ORModel

# Import models used for testing
from examples.models import Hero, Team # Adjust import path if needed

# Mark all tests in this module to use pytest-asyncio
pytestmark = pytest.mark.asyncio


async def test_create_hero(db_session):
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

async def test_get_existing_hero(db_session):
    """Test retrieving an existing Hero."""
    hero = await Hero.objects.create(name="Getter", secret_name="Fetcher", age=40)
    retrieved_hero = await Hero.objects.get(id=hero.id)
    assert retrieved_hero is not None
    assert retrieved_hero.id == hero.id
    assert retrieved_hero.name == "Getter"

async def test_get_nonexistent_hero(db_session):
    """Test that getting a non-existent Hero raises DoesNotExist."""
    with pytest.raises(DoesNotExist):
        await Hero.objects.get(id=999)

async def test_get_multiple_results_raises_exception(db_session):
    """Test that get() raises MultipleObjectsReturned if >1 match."""
    await Hero.objects.create(name="SameName", secret_name="One", age=20)
    await Hero.objects.create(name="SameName", secret_name="Two", age=21)

    with pytest.raises(MultipleObjectsReturned):
        await Hero.objects.get(name="SameName")

async def test_filter_and_all(db_session):
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

async def test_filter_chaining(db_session):
    """Test chaining multiple filters."""
    await Hero.objects.create(name="Chain", secret_name="One", age=30)
    await Hero.objects.create(name="Chain", secret_name="Two", age=40)
    await Hero.objects.create(name="Link", secret_name="Three", age=30)

    result = await Hero.objects.filter(name="Chain").filter(age=30).all()
    assert len(result) == 1
    assert result[0].secret_name == "One"

async def test_count_heroes(db_session):
    """Test counting heroes."""
    assert await Hero.objects.count() == 0

    await Hero.objects.create(name="Count 1", secret_name="C1", age=10)
    await Hero.objects.create(name="Count 2", secret_name="C2", age=20)
    await Hero.objects.create(name="Count 3", secret_name="C3", age=10)

    assert await Hero.objects.count() == 3
    assert await Hero.objects.filter(age=10).count() == 2
    assert await Hero.objects.filter(age=30).count() == 0

async def test_get_or_create_does_not_exist(db_session):
    """Test get_or_create when the object doesn't exist."""
    hero, created = await Hero.objects.get_or_create(
        name="New Hero",
        defaults={"secret_name": "Secret", "age": 22}
    )
    assert created is True
    assert hero.id is not None
    assert hero.name == "New Hero"
    assert hero.secret_name == "Secret"
    assert hero.age == 22
    # Verify count
    assert await Hero.objects.count() == 1

async def test_get_or_create_exists(db_session):
    """Test get_or_create when the object already exists."""
    # Create initial hero
    initial_hero = await Hero.objects.create(name="Existing Hero", secret_name="Original", age=50)
    initial_id = initial_hero.id

    # Attempt get_or_create with the same name
    hero, created = await Hero.objects.get_or_create(
        name="Existing Hero",
        defaults={"secret_name": "Should Not Be Used", "age": 55} # Defaults ignored
    )
    assert created is False
    assert hero.id == initial_id
    assert hero.name == "Existing Hero"
    assert hero.secret_name == "Original" # Check it wasn't updated
    assert hero.age == 50
    # Verify count hasn't increased
    assert await Hero.objects.count() == 1

async def test_update_or_create_creates_new(db_session):
    """Test update_or_create when the object doesn't exist."""
    hero, created = await Hero.objects.update_or_create(
        name="UpdateOrCreate New",
        defaults={"secret_name": "UOC Secret", "age": 44}
    )
    assert created is True
    assert hero.id is not None
    assert hero.name == "UpdateOrCreate New"
    assert hero.secret_name == "UOC Secret"
    assert hero.age == 44
    assert await Hero.objects.count() == 1

async def test_update_or_create_updates_existing(db_session):
    """Test update_or_create when the object already exists."""
    initial_hero = await Hero.objects.create(name="UpdateMe", secret_name="Before", age=60)
    initial_id = initial_hero.id

    hero, created = await Hero.objects.update_or_create(
        name="UpdateMe", # Match criteria
        defaults={"secret_name": "After", "age": 61} # Values to update
    )

    assert created is False
    assert hero.id == initial_id
    assert hero.name == "UpdateMe"
    assert hero.secret_name == "After" # Check secret_name was updated
    assert hero.age == 61 # Check age was updated
    assert await Hero.objects.count() == 1

    # Verify directly from DB
    refreshed_hero = await Hero.objects.get(id=initial_id)
    assert refreshed_hero.secret_name == "After"
    assert refreshed_hero.age == 61

async def test_delete_hero(db_session):
    """Test deleting a hero instance."""
    hero_to_delete = await Hero.objects.create(name="Deleter", secret_name="Temp", age=1)
    hero_id = hero_to_delete.id

    assert await Hero.objects.count() == 1

    # Delete the instance
    await Hero.objects.delete(hero_to_delete)

    assert await Hero.objects.count() == 0

    # Verify it cannot be retrieved
    with pytest.raises(DoesNotExist):
        await Hero.objects.get(id=hero_id)

# --- Relationship Tests (Example) ---

async def test_create_with_relationship(db_session):
    """Test creating objects with relationships."""
    team = await Team.objects.create(name="Test Team", headquarters="Test HQ")
    assert team.id is not None

    hero = await Hero.objects.create(
        name="Team Player",
        secret_name="TP",
        age=28,
        team_id=team.id # Assign foreign key
    )
    assert hero.id is not None
    assert hero.team_id == team.id

    # Verify relationship access (may require refresh or eager loading setup if complex)
    # A simple refresh after retrieval should work here
    retrieved_hero = await Hero.objects.get(id=hero.id)
    # ORModel might automatically fetch simple relationships, or need explicit loading
    # Let's try accessing directly
    # Note: Accessing relationship might trigger another query if not eager loaded
    retrieved_team = retrieved_hero.team # Use awaitable_attrs for async relationships
    assert retrieved_team is not None
    assert retrieved_team.id == team.id
    assert retrieved_team.name == "Test Team"

async def test_filter_by_relationship(db_session):
    """Test filtering based on related model attributes."""
    team1 = await Team.objects.create(name="Team One", headquarters="HQ1")
    team2 = await Team.objects.create(name="Team Two", headquarters="HQ2")
    await Hero.objects.create(name="Hero 1", secret_name="H1", age=20, team_id=team1.id)
    await Hero.objects.create(name="Hero 2", secret_name="H2", age=30, team_id=team2.id)
    await Hero.objects.create(name="Hero 3", secret_name="H3", age=40, team_id=team1.id)

    # Find heroes belonging to "Team One"
    # Requires a JOIN - ensure Manager/Query supports this or use SQLAlchemy join syntax
    # Let's assume a simple filter on team_id works directly for now
    team_one_heroes = await Hero.objects.filter(team_id=team1.id).order_by(Hero.name).all()
    assert len(team_one_heroes) == 2
    assert team_one_heroes[0].name == "Hero 1"
    assert team_one_heroes[1].name == "Hero 3"

    # More advanced: Filter Hero based on Team's name (requires JOIN)
    # This might need enhancements to the filter method or direct SQLAlchemy use
    # query = Hero.objects.filter(Team.name == "Team Two").join(Team) # Example of explicit join
    # team_two_heroes = await query.all()
    # assert len(team_two_heroes) == 1
    # assert team_two_heroes[0].name == "Hero 2"

# --- Constraint Tests (Example) ---

@pytest.mark.parametrize("commit,team_count", [(True, 1), (False, 0)])
async def test_unique_constraint(db_session,commit,team_count):
    """Test that unique constraints are enforced (e.g., Team name)."""
    await Team.objects.create(name="UniqueTeam", headquarters="HQ Unique")
    assert await Team.objects.count() == 1
    if commit:
        await db_session.commit()

    # Try creating another team with the same name
    with pytest.raises(IntegrityError): # SQLAlchemy raises IntegrityError for constraint violations
        await Team.objects.create(name="UniqueTeam", headquarters="HQ Duplicate Attempt")
        # Note: The actual commit (or flush) triggers the error.
        # The fixture db_session handles commit/rollback. If create itself flushes,
        # the error might occur within the create call.

    # Verify count hasn't changed and rollback occurred (implicitly by fixture)
    assert await Team.objects.count() == team_count