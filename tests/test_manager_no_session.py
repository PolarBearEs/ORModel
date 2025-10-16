# tests/test_manager_no_session.py
import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from examples.models import Hero, Team
from ormodel import DoesNotExist, MultipleObjectsReturned
from ormodel.manager import Query as ORModelQuery


# Mark all tests in this module to use pytest-asyncio
async def test_get_session_isnot_imported() -> None:
    with pytest.raises(NameError):
        get_session()

async def test_create_hero_no_session():
    """Test creating a single Hero object without db_session fixture."""
    hero_data = {"name": "Test Hero No Session", "secret_name": "Tester NS", "age": 30}
    hero = await Hero.objects.create(**hero_data)

    assert hero.id is not None
    assert hero.name == hero_data["name"]
    assert hero.secret_name == hero_data["secret_name"]
    assert hero.age == hero_data["age"]

    # Verify it's in the DB using a separate query
    retrieved_hero = await Hero.objects.get(id=hero.id)
    assert retrieved_hero == hero


async def test_get_existing_hero_no_session():
    """Test retrieving an existing Hero without db_session fixture."""
    hero = await Hero.objects.create(name="Getter NS", secret_name="Fetcher NS", age=40)
    retrieved_hero = await Hero.objects.get(id=hero.id)
    assert retrieved_hero is not None
    assert retrieved_hero.id == hero.id
    assert retrieved_hero.name == "Getter NS"


async def test_get_nonexistent_hero_no_session():
    """Test that getting a non-existent Hero raises DoesNotExist without db_session fixture."""
    with pytest.raises(DoesNotExist):
        await Hero.objects.get(id=999)


async def test_get_multiple_results_raises_exception_no_session():
    """Test that get() raises MultipleObjectsReturned if >1 match without db_session fixture."""
    await Hero.objects.create(name="SameName NS", secret_name="One NS", age=20)
    await Hero.objects.create(name="SameName NS", secret_name="Two NS", age=21)

    with pytest.raises(MultipleObjectsReturned):
        await Hero.objects.get(name="SameName NS")


async def test_filter_and_all_no_session():
    """Test filtering heroes and retrieving all matches without db_session fixture."""
    await Hero.objects.create(name="Hero A NS", secret_name="A1 NS", age=25)
    await Hero.objects.create(name="Hero B NS", secret_name="B1 NS", age=35)
    await Hero.objects.create(name="Hero C NS", secret_name="C1 NS", age=25)

    # Filter by age
    heroes_age_25 = await Hero.objects.filter(age=25).all()
    assert len(heroes_age_25) == 2
    names = sorted([h.name for h in heroes_age_25])
    assert names == ["Hero A NS", "Hero C NS"]

    # Filter by name
    hero_b = await Hero.objects.filter(name="Hero B NS").all()
    assert len(hero_b) == 1
    assert hero_b[0].secret_name == "B1 NS"

    # Filter with no results
    no_heroes = await Hero.objects.filter(name="NonExistent NS").all()
    assert len(no_heroes) == 0


async def test_filter_chaining_no_session():
    """Test chaining multiple filters without db_session fixture."""
    await Hero.objects.create(name="Chain NS", secret_name="One NS", age=30)
    await Hero.objects.create(name="Chain NS", secret_name="Two NS", age=40)
    await Hero.objects.create(name="Link NS", secret_name="Three NS", age=30)

    result = await Hero.objects.filter(name="Chain NS").filter(age=30).all()
    assert len(result) == 1
    assert result[0].secret_name == "One NS"


async def test_count_heroes_no_session():
    """Test counting heroes without db_session fixture."""
    assert await Hero.objects.count() == 0

    await Hero.objects.create(name="Count 1 NS", secret_name="C1 NS", age=10)
    await Hero.objects.create(name="Count 2 NS", secret_name="C2 NS", age=20)
    await Hero.objects.create(name="Count 3 NS", secret_name="C3 NS", age=10)

    assert await Hero.objects.count() == 3
    assert await Hero.objects.filter(age=10).count() == 2
    assert await Hero.objects.filter(age=30).count() == 0


async def test_get_or_create_does_not_exist_no_session():
    """Test get_or_create when the object doesn't exist without db_session fixture."""
    hero, created = await Hero.objects.get_or_create(name="New Hero NS", defaults={"secret_name": "Secret NS", "age": 22})
    assert created is True
    assert hero.id is not None
    assert hero.name == "New Hero NS"
    assert hero.secret_name == "Secret NS"
    assert hero.age == 22
    # Verify count
    assert await Hero.objects.count() == 1


async def test_get_or_create_exists_no_session():
    """Test get_or_create when the object already exists without db_session fixture."""
    # Create initial hero
    initial_hero = await Hero.objects.create(name="Existing Hero NS", secret_name="Original NS", age=50)
    initial_id = initial_hero.id

    # Attempt get_or_create with the same name
    hero, created = await Hero.objects.get_or_create(
        name="Existing Hero NS",
        defaults={"secret_name": "Should Not Be Used NS", "age": 55},  # Defaults ignored
    )
    assert created is False
    assert hero.id == initial_id
    assert hero.name == "Existing Hero NS"
    assert hero.secret_name == "Original NS"  # Check it wasn't updated
    assert hero.age == 50
    # Verify count hasn't increased
    assert await Hero.objects.count() == 1


async def test_update_or_create_creates_new_no_session():
    """Test update_or_create when the object doesn't exist without db_session fixture."""
    hero, created = await Hero.objects.update_or_create(
        name="UpdateOrCreate New NS", defaults={"secret_name": "UOC Secret NS", "age": 44}
    )
    assert created is True
    assert hero.id is not None
    assert hero.name == "UpdateOrCreate New NS"
    assert hero.secret_name == "UOC Secret NS"
    assert hero.age == 44
    assert await Hero.objects.count() == 1


async def test_update_or_create_updates_existing_no_session():
    """Test update_or_create when the object already exists without db_session fixture."""
    initial_hero = await Hero.objects.create(name="UpdateMe NS", secret_name="Before NS", age=60)
    initial_id = initial_hero.id

    hero, created = await Hero.objects.update_or_create(
        name="UpdateMe NS",  # Match criteria
        defaults={"secret_name": "After NS", "age": 61},  # Values to update
    )

    assert created is False
    assert hero.id == initial_id
    assert hero.name == "UpdateMe NS"
    assert hero.secret_name == "After NS"  # Check secret_name was updated
    assert hero.age == 61  # Check age was updated
    assert await Hero.objects.count() == 1

    # Verify directly from DB
    refreshed_hero = await Hero.objects.get(id=initial_id)
    assert refreshed_hero.secret_name == "After NS"
    assert refreshed_hero.age == 61


async def test_delete_hero_no_session():
    """Test deleting a hero instance without db_session fixture."""
    hero_to_delete = await Hero.objects.create(name="Deleter NS", secret_name="Temp NS", age=1)
    hero_id = hero_to_delete.id

    assert await Hero.objects.count() == 1

    # Delete the instance
    await hero_to_delete.delete()

    assert await Hero.objects.count() == 0

    # Verify it cannot be retrieved
    with pytest.raises(DoesNotExist):
        await Hero.objects.get(id=hero_id)


async def test_update_instance_no_session():
    """Test updating a hero instance directly without db_session fixture."""
    hero = await Hero.objects.create(name="Updater NS", secret_name="Original NS", age=10)

    hero.name = "Updated Updater NS"
    hero.age = 11
    await hero.save()

    updated_hero = await Hero.objects.get(id=hero.id)
    assert updated_hero.name == "Updated Updater NS"
    assert updated_hero.age == 11
    assert updated_hero.secret_name == "Original NS" # Should remain unchanged


async def test_update_single_field_no_session():
    """Test updating a single field for multiple objects matching a filter without db_session fixture."""
    await Hero.objects.create(name="Update Target 1 NS", secret_name="Before NS", age=25)
    await Hero.objects.create(name="Update Target 2 NS", secret_name="Before NS", age=25)
    await Hero.objects.create(name="Ignore Me NS", secret_name="Before NS", age=30)

    updated_count = await Hero.objects.filter(age=25).update(secret_name="After NS")

    assert updated_count == 2
    updated_heroes = await Hero.objects.filter(secret_name="After NS").all()
    assert len(updated_heroes) == 2
    for hero in updated_heroes:
        assert hero.age == 25

    ignored_hero = await Hero.objects.get(name="Ignore Me NS")
    assert ignored_hero.secret_name == "Before NS"


async def test_update_multiple_fields_no_session():
    """Test updating multiple fields at once without db_session fixture."""
    await Hero.objects.create(name="Multi-Update NS", secret_name="Original NS", age=50)

    updated_count = await Hero.objects.filter(name="Multi-Update NS").update(secret_name="Updated Secret NS", age=51)

    assert updated_count == 1
    updated_hero = await Hero.objects.get(name="Multi-Update NS")
    assert updated_hero.secret_name == "Updated Secret NS"
    assert updated_hero.age == 51


async def test_update_with_no_matches_no_session():
    """Test that update returns 0 when no objects match the filter without db_session fixture."""
    await Hero.objects.create(name="Existing Hero NS", secret_name="Exists NS", age=40)

    updated_count = await Hero.objects.filter(name="Non-Existent NS").update(age=99)

    assert updated_count == 0
    hero = await Hero.objects.get(name="Existing Hero NS")
    assert hero.age == 40


async def test_update_all_records_no_session():
    """Test updating all records by using an empty filter without db_session fixture."""
    await Hero.objects.create(name="Hero 1 NS", secret_name="A NS", age=10)
    await Hero.objects.create(name="Hero 2 NS", secret_name="B NS", age=20)
    await Hero.objects.create(name="Hero 3 NS", secret_name="C NS", age=30)

    total_heroes = await Hero.objects.count()
    assert total_heroes == 3

    updated_count = await Hero.objects.filter().update(age=100)

    assert updated_count == total_heroes
    final_count = await Hero.objects.filter(age=100).count()
    assert final_count == total_heroes


async def test_create_with_relationship_no_session():
    """Test creating objects with relationships without db_session fixture."""
    team = await Team.objects.create(name="Test Team NS", headquarters="Test HQ NS")
    assert team.id is not None

    hero = await Hero.objects.create(name="Team Player NS", secret_name="TP NS", age=28, team_id=team.id)
    assert hero.id is not None
    assert hero.team_id == team.id

    retrieved_hero = await Hero.objects.get(id=hero.id)
    retrieved_team = retrieved_hero.team
    assert retrieved_team is not None
    assert retrieved_team.id == team.id
    assert retrieved_team.name == "Test Team NS"


async def test_filter_by_relationship_no_session():
    """Test filtering based on related model attributes without db_session fixture."""
    team1 = await Team.objects.create(name="Team One NS", headquarters="HQ1 NS")
    team2 = await Team.objects.create(name="Team Two NS", headquarters="HQ2 NS")
    await Hero.objects.create(name="Hero 1 NS", secret_name="H1 NS", age=20, team_id=team1.id)
    await Hero.objects.create(name="Hero 2 NS", secret_name="H2 NS", age=30, team_id=team2.id)
    await Hero.objects.create(name="Hero 3 NS", secret_name="H3 NS", age=40, team_id=team1.id)

    team_one_heroes = await Hero.objects.filter(team_id=team1.id).order_by(Hero.name).all()
    assert len(team_one_heroes) == 2
    assert team_one_heroes[0].name == "Hero 1 NS"
    assert team_one_heroes[1].name == "Hero 3 NS"


async def test_join_with_relationship_no_session():
    """Test joining models and filtering across relationships without db_session fixture."""
    team_alpha = await Team.objects.create(name="Team Alpha NS", headquarters="Alpha HQ NS")
    team_beta = await Team.objects.create(name="Team Beta NS", headquarters="Beta HQ NS")

    await Hero.objects.create(name="Hero A NS", secret_name="SA NS", age=20, team_id=team_alpha.id)
    await Hero.objects.create(name="Hero B NS", secret_name="SB NS", age=30, team_id=team_beta.id)
    await Hero.objects.create(name="Hero C NS", secret_name="SC NS", age=25, team_id=team_alpha.id)

    # Join Hero with Team and filter by Team name
    heroes_from_alpha_team = await Hero.objects.join(Team).filter(Team.name == "Team Alpha NS").all()

    assert len(heroes_from_alpha_team) == 2
    names = sorted([h.name for h in heroes_from_alpha_team])
    assert names == ["Hero A NS", "Hero C NS"]

    # Verify that the joined relationship is loaded
    for hero in heroes_from_alpha_team:
        assert hero.team.name == "Team Alpha NS"


async def test_unique_constraint_no_session():
    """Test that unique constraints are enforced (e.g., Team name) without db_session fixture."""
    # The auto-session wrapper will handle the session for these calls
    await Team.objects.create(name="UniqueTeam NS", headquarters="HQ Unique NS")
    assert await Team.objects.count() == 1

    with pytest.raises(IntegrityError):
        # This create will fail due to unique constraint, and the auto-session will roll back
        await Team.objects.create(name="UniqueTeam NS", headquarters="HQ Duplicate Attempt NS")

    # After the IntegrityError and rollback, the count should be 0
    assert await Team.objects.count() == 1
