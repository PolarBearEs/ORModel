# tests/test_manager.py
from enum import StrEnum

import pytest
import pytest_asyncio
from sqlalchemy import Column, Computed, Integer, String, text
from sqlalchemy.exc import IntegrityError, PendingRollbackError
from sqlalchemy.orm.exc import DetachedInstanceError
from sqlmodel import Field, col

from examples.models import Hero, Team
from ormodel import DoesNotExist, MultipleObjectsReturned, ORModel, Query, get_session, get_session_from_context


class Label(ORModel, table=True):
    """A field whose column has another name, and a column filled in by the database."""

    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(sa_column=Column("label_title", String, unique=True, nullable=False))
    color: str | None = Field(default=None, sa_column_kwargs={"server_default": text("'grey'")})


class Tick(ORModel, table=True):
    """Every column is filled in by the database."""

    id: int | None = Field(default=None, primary_key=True)
    source: str | None = Field(default=None, sa_column_kwargs={"server_default": text("'clock'")})


class Box(ORModel, table=True):
    """A column computed by the database."""

    id: int | None = Field(default=None, primary_key=True)
    side: int
    area: int | None = Field(default=None, sa_column=Column(Integer, Computed("side * side"), unique=True))
    revision: int | None = Field(
        default=None, sa_column_kwargs={"server_default": text("0"), "onupdate": text("revision + 1")}
    )


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


async def test_get_or_create_inserts_when_missing():
    """get_or_create inserts the given instance when nothing matches the lookup fields."""
    hero, created = await Hero.objects.get_or_create(Hero(name="New Hero", secret_name="Secret", age=22), on="name")
    assert created is True
    assert hero.id is not None
    assert (hero.name, hero.secret_name, hero.age) == ("New Hero", "Secret", 22)
    assert await Hero.objects.count() == 1


async def test_get_or_create_returns_existing_untouched():
    """get_or_create returns the stored row and ignores the other values of the instance."""
    initial = await Hero.objects.create(name="Existing Hero", secret_name="Original", age=50)

    hero, created = await Hero.objects.get_or_create(
        Hero(name="Existing Hero", secret_name="Should Not Be Used", age=55), on=Hero.name
    )
    assert created is False
    assert hero.id == initial.id
    assert (hero.secret_name, hero.age) == ("Original", 50)
    assert await Hero.objects.count() == 1


async def test_get_or_create_matches_on_multiple_fields():
    """`on` accepts several fields; all of them must match."""
    await Hero.objects.create(name="Twin", secret_name="A", age=1)

    _, created_same = await Hero.objects.get_or_create(Hero(name="Twin", secret_name="A"), on=["name", "secret_name"])
    _, created_other = await Hero.objects.get_or_create(
        Hero(name="Twin", secret_name="B"), on=[Hero.name, Hero.secret_name]
    )
    assert created_same is False
    assert created_other is True
    assert await Hero.objects.count() == 2


async def test_get_or_create_defaults_to_primary_key():
    """Without `on`, the lookup uses the primary key; an unset primary key always inserts."""
    stored = await Hero.objects.create(name="By PK", secret_name="Original")

    hero, created = await Hero.objects.get_or_create(Hero(id=stored.id, name="Other", secret_name="Other"))
    assert created is False
    assert hero.name == "By PK"

    _, created = await Hero.objects.get_or_create(Hero(name="By PK", secret_name="Original"))
    assert created is True
    assert await Hero.objects.count() == 2


async def test_get_or_create_rejects_unknown_lookup_field():
    with pytest.raises(AttributeError, match="has no field 'nope'"):
        await Hero.objects.get_or_create(Hero(name="X", secret_name="Y"), on="nope")


@pytest.mark.parametrize("method", ["get_or_create", "upsert"])
async def test_insert_as_first_write_rolls_back_with_the_session(method: str):
    """The savepoint around the insert stays inside the session's transaction, even on SQLite."""
    with pytest.raises(RuntimeError, match="abort"):
        async with get_session():
            await getattr(Team.objects, method)(Team(name="Ghost", headquarters="Nowhere"), on=Team.name)
            raise RuntimeError("abort")

    assert not await Team.objects.filter(name="Ghost").exists()


async def test_upsert_creates_new():
    """upsert inserts the instance when nothing matches."""
    hero, created = await Hero.objects.upsert(Hero(name="Upsert New", secret_name="UOC Secret", age=44), on="name")
    assert created is True
    assert hero.id is not None
    assert (hero.name, hero.secret_name, hero.age) == ("Upsert New", "UOC Secret", 44)
    assert await Hero.objects.count() == 1


async def test_upsert_updates_existing():
    """upsert copies the instance's values onto the matching row."""
    initial = await Hero.objects.create(name="UpdateMe", secret_name="Before", age=60)

    hero, created = await Hero.objects.upsert(Hero(name="UpdateMe", secret_name="After", age=61), on=Hero.name)

    assert created is False
    assert hero.id == initial.id
    assert (hero.secret_name, hero.age) == ("After", 61)
    assert await Hero.objects.count() == 1

    refreshed = await Hero.objects.get(id=initial.id)
    assert (refreshed.secret_name, refreshed.age) == ("After", 61)


async def test_upsert_only_copies_explicitly_set_fields():
    """Fields left at their defaults on the instance do not overwrite stored values."""
    initial = await Hero.objects.create(name="Partial", secret_name="Before", age=60)

    hero, _ = await Hero.objects.upsert(Hero(name="Partial", secret_name="After"), on="name")
    assert (hero.secret_name, hero.age) == ("After", 60)

    hero, _ = await Hero.objects.upsert(Hero(name="Partial", secret_name="Ignored"), on="name", update_fields=["age"])
    assert (hero.id, hero.secret_name, hero.age) == (initial.id, "After", None)


async def test_upsert_without_changes_writes_nothing():
    """Upserting the stored values back leaves the row untouched."""
    team = await Team.objects.create(name="Same", headquarters="HQ")

    again, created = await Team.objects.upsert(Team(name="Same", headquarters="HQ"), on="name")

    assert (again.id, again.headquarters, created) == (team.id, "HQ", False)


async def test_on_must_name_a_field():
    """An empty `on` would match every row, so it is refused."""
    with pytest.raises(ValueError, match="at least one field"):
        await Team.objects.get_or_create(Team(name="X", headquarters="Y"), on=[])


class _MissFirstLookup:
    """Makes the first one_or_none() miss, as if a concurrent insert landed right after the lookup."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch):
        self.calls = 0
        original = Query.one_or_none

        async def one_or_none(query):
            self.calls += 1
            if self.calls == 1:
                return None
            return await original(query)

        monkeypatch.setattr(Query, "one_or_none", one_or_none)


@pytest.mark.parametrize("method", ["get_or_create", "upsert"])
async def test_lost_insert_race_returns_existing_and_keeps_transaction(
    monkeypatch: pytest.MonkeyPatch, session_mode: SessionMode, method: str
):
    """A unique violation from a concurrent insert is recovered inside a savepoint."""
    await Team.objects.create(name="Earlier Work", headquarters="Keep")
    await Team.objects.create(name="Racers", headquarters="Theirs")
    lookups = _MissFirstLookup(monkeypatch)

    team, created = await getattr(Team.objects, method)(Team(name="Racers", headquarters="Ours"), on="name")

    assert created is False
    assert lookups.calls == 2
    assert team.headquarters == ("Theirs" if method == "get_or_create" else "Ours")
    # The surrounding transaction is still usable and kept the earlier write.
    assert await Team.objects.count() == 2


async def test_insert_integrity_error_without_match_is_raised(monkeypatch: pytest.MonkeyPatch):
    """An IntegrityError that is not explained by a matching row is re-raised."""
    await Team.objects.create(name="Taken", headquarters="HQ")
    _MissFirstLookup(monkeypatch)

    with pytest.raises(IntegrityError):
        # Matching on headquarters never finds the row, but the unique name still collides.
        await Team.objects.get_or_create(Team(name="Taken", headquarters="Elsewhere"), on="headquarters")


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
    """Updating every row requires each=True."""
    await Hero.objects.create(name="Hero 1", secret_name="A", age=10)
    await Hero.objects.create(name="Hero 2", secret_name="B", age=20)
    await Hero.objects.create(name="Hero 3", secret_name="C", age=30)

    total_heroes = await Hero.objects.count()
    assert total_heroes == 3

    updated_count = await Hero.objects.update(age=100, each=True)

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

    deleted_count = await Hero.objects.delete(each=True)

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
    heroes_from_alpha_team = await Hero.objects.join(Team).filter(col(Team.name) == "Team Alpha").all()

    assert len(heroes_from_alpha_team) == 2
    names = sorted([h.name for h in heroes_from_alpha_team])
    assert names == ["Hero A", "Hero C"]

    if session_mode is SessionMode.AUTO_SESSION:
        with pytest.raises(DetachedInstanceError):
            for hero in heroes_from_alpha_team:
                team = hero.team
                assert team is not None
                assert team.name == "Team Alpha"
    else:
        for hero in heroes_from_alpha_team:
            team = hero.team
            assert team is not None
            assert team.name == "Team Alpha"


@pytest.mark.parametrize("commit", [True, False])
async def test_unique_constraint(session_mode: SessionMode, commit: bool):
    """A failed create() leaves the transaction to the caller instead of silently rolling it back."""
    await Team.objects.create(name="UniqueTeam", headquarters="HQ Unique")
    assert await Team.objects.count() == 1
    if commit and session_mode is SessionMode.WITH_SESSION:
        await get_session_from_context().commit()

    with pytest.raises(IntegrityError):
        await Team.objects.create(name="UniqueTeam", headquarters="HQ Duplicate Attempt")

    if session_mode is SessionMode.WITH_SESSION:
        with pytest.raises(PendingRollbackError):
            await Team.objects.count()
        await get_session_from_context().rollback()

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


async def test_count_respects_join_and_limit():
    """count() counts the rows the query would return, joins and limit included."""
    team = await Team.objects.create(name="Counted", headquarters="HQ")
    await Team.objects.create(name="Other", headquarters="HQ")
    for index in range(3):
        await Hero.objects.create(name=f"H{index}", secret_name="S", team_id=team.id)

    assert await Hero.objects.join(Team).filter(Team.name == "Counted").count() == 3
    assert await Hero.objects.limit(2).count() == 2


@pytest.mark.parametrize("operation", ["update", "delete"])
async def test_bulk_operations_reject_limit_and_offset(operation: str):
    """Bulk update/delete refuse limit/offset instead of silently touching every matching row."""
    await Hero.objects.create(name="Safe", secret_name="S", age=1)
    query = Hero.objects.order_by(Hero.id).limit(1)
    kwargs = {"age": 2} if operation == "update" else {}

    with pytest.raises(ValueError, match="does not support limit"):
        await getattr(query, operation)(**kwargs)
    assert (await Hero.objects.get(name="Safe")).age == 1


async def test_get_or_none_and_exists():
    """get_or_none() mirrors get() without raising; exists() checks for any match."""
    hero = await Hero.objects.create(name="Lookup", secret_name="L", age=40)

    assert (await Hero.objects.get_or_none(name="Lookup")).id == hero.id
    assert await Hero.objects.get_or_none(Hero.age > 100) is None
    assert await Hero.objects.filter(name="Lookup").exists() is True
    assert await Hero.objects.filter(name="Missing").exists() is False

    await Hero.objects.create(name="Lookup", secret_name="L2")
    with pytest.raises(MultipleObjectsReturned):
        await Hero.objects.get_or_none(name="Lookup")


async def test_bulk_upsert_inserts_and_updates(session_mode: SessionMode):
    """bulk_upsert() inserts new rows and updates conflicting ones in place."""
    existing = await Team.objects.create(name="Alpha", headquarters="Old")
    untouched = await Team.objects.create(name="Gamma", headquarters="G")

    written = await Team.objects.bulk_upsert(
        [Team(name="Alpha", headquarters="New"), Team(name="Beta", headquarters="B")], on=Team.name
    )

    assert written == 2
    teams = {team.name: team for team in await Team.objects.all()}
    assert (teams["Alpha"].id, teams["Alpha"].headquarters) == (existing.id, "New")
    assert teams["Beta"].headquarters == "B"
    if session_mode is SessionMode.WITH_SESSION:
        # Instances already loaded in the session are refreshed, not left stale.
        assert existing.headquarters == "New"
        assert untouched.headquarters == "G"


async def test_bulk_upsert_only_updates_set_fields_and_dedupes():
    """Unset fields keep their stored value; repeated keys collapse to the last instance."""
    await Hero.objects.create(name="Keep", secret_name="S", age=30)
    # Hero.name is not unique, so match on the primary key instead.
    hero_id = (await Hero.objects.get(name="Keep")).id

    written = await Hero.objects.bulk_upsert(
        [Hero(id=hero_id, name="Keep", secret_name="First"), Hero(id=hero_id, name="Keep", secret_name="Last")]
    )

    assert written == 1
    hero = await Hero.objects.get(id=hero_id)
    assert (hero.secret_name, hero.age) == ("Last", 30)


async def test_bulk_upsert_empty_and_insert_only():
    """No instances writes nothing; nothing to update means conflicting rows are left alone."""
    assert await Team.objects.bulk_upsert([], on="name") == 0
    await Team.objects.create(name="Fixed", headquarters="HQ")

    await Team.objects.bulk_upsert([Team(name="Fixed", headquarters="Other")], on="name", update_fields=[])

    assert (await Team.objects.get(name="Fixed")).headquarters == "HQ"


async def test_bulk_upsert_inserts_every_instance_without_a_key():
    """Instances with an unset `on` value never collide with each other: each one is inserted."""
    written = await Team.objects.bulk_upsert(
        [
            Team(name="One", headquarters="A"),
            Team(name="Two", headquarters="B"),
            Team(id=50, name="Three", headquarters="C"),
        ]
    )

    assert written == 3
    assert sorted(team.name for team in await Team.objects.all()) == ["One", "Three", "Two"]
    assert (await Team.objects.get(name="Three")).id == 50


async def test_bulk_upsert_leaves_generated_values_to_the_database():
    """Unset server defaults and keys are filled in by the database, as with a regular insert."""
    await Label.objects.bulk_upsert([Label(title="new"), Label(title="red", color="red")])

    labels = {label.title: label for label in await Label.objects.all()}
    assert (labels["new"].color, labels["red"].color) == ("grey", "red")
    assert labels["new"].id is not None


async def test_bulk_upsert_inserts_rows_with_only_generated_values():
    """Instances leaving every column to the database are each inserted."""
    written = await Tick.objects.bulk_upsert([Tick(), Tick(), Tick(source="manual")])

    assert written == 3
    assert sorted(tick.source for tick in await Tick.objects.all()) == ["clock", "clock", "manual"]


async def test_bulk_upsert_clears_values_explicitly_set_to_none():
    """An explicit None is written, even on a column the database would otherwise fill in."""
    await Label.objects.bulk_upsert([Label(title="a", color="red"), Label(title="b", color="red")], on=Label.title)

    await Label.objects.bulk_upsert([Label(title="a", color=None), Label(title="c", color=None)], on=Label.title)

    labels = {label.title: label.color for label in await Label.objects.all()}
    assert labels == {"a": None, "b": "red", "c": None}


async def test_bulk_upsert_keeps_stored_values_left_to_the_database():
    """A column left unset on one instance is not overwritten with its default, even if others set it."""
    await Label.objects.bulk_upsert([Label(title="a", color="red")], on=Label.title)

    await Label.objects.bulk_upsert([Label(title="a"), Label(title="b", color="blue")], on=Label.title)

    labels = {label.title: label.color for label in await Label.objects.all()}
    assert labels == {"a": "red", "b": "blue"}


async def test_bulk_upsert_keeps_pending_changes():
    """Unflushed edits to held instances survive the refresh after the statement."""
    async with get_session() as session:
        held = await Hero.objects.create(name="Pending", secret_name="Old", age=20)
        held.age = 21
        session.add(held)
        await Hero.objects.bulk_upsert(
            [Hero(id=held.id, name="Pending", secret_name="New")], update_fields=[Hero.secret_name]
        )
        assert (held.age, held.secret_name) == (21, "New")

    stored = await Hero.objects.get(name="Pending")
    assert (stored.age, stored.secret_name) == (21, "New")


async def test_bulk_upsert_flushes_pending_inputs_once():
    """An input already pending in the session is inserted once, then upserted under its new key."""
    async with get_session() as session:
        hero = Hero(name="Pending", secret_name="Once")
        session.add(hero)

        written = await Hero.objects.bulk_upsert([hero])

    assert written == 1
    assert [stored.id for stored in await Hero.objects.filter(name="Pending").all()] == [hero.id]


async def test_bulk_upsert_leaves_computed_columns_to_the_database():
    """Computed values are neither inserted nor updated, even when the instance holds one."""
    box = await Box.objects.create(side=2)
    assert box.area == 4
    box.side = 3

    written = await Box.objects.bulk_upsert([box, Box(side=5)])

    assert written == 2
    assert sorted((stored.side, stored.area) for stored in await Box.objects.all()) == [(3, 9), (5, 25)]


async def test_bulk_upsert_loads_values_expired_by_its_flush():
    """Values the flush regenerates are loaded before the instance is read, including a computed `on` key."""
    async with get_session():
        box = await Box.objects.create(side=2)
        box.side = 3

        written = await Box.objects.bulk_upsert([box], on=Box.area)

        assert written == 1
        assert (box.area, box.revision) == (9, 1)


async def test_bulk_upsert_rejects_computed_update_fields():
    """Asking to copy a computed column onto existing rows is refused."""
    with pytest.raises(ValueError, match="computed columns"):
        await Box.objects.bulk_upsert([Box(side=2)], update_fields=[Box.area])


async def test_bulk_upsert_maps_fields_to_renamed_columns():
    """Fields stored under another column name are written and matched through that column."""
    await Label.objects.bulk_upsert([Label(title="a", color="red")], on=Label.title)

    written = await Label.objects.bulk_upsert([Label(title="a", color="blue")], on=Label.title)

    assert written == 1
    assert [(label.title, label.color) for label in await Label.objects.all()] == [("a", "blue")]


async def test_bulk_upsert_counts_only_written_rows():
    """Rows skipped by ON CONFLICT DO NOTHING are not counted."""
    await Team.objects.create(name="Fixed", headquarters="HQ")

    written = await Team.objects.bulk_upsert(
        [Team(name="Fixed", headquarters="Other"), Team(name="New", headquarters="HQ")], on="name", update_fields=[]
    )

    assert written == 1


async def test_bulk_upsert_rejects_unsupported_dialects(monkeypatch: pytest.MonkeyPatch):
    """Dialects without INSERT ... ON CONFLICT are refused instead of falling back silently."""
    monkeypatch.setattr("ormodel.manager._DIALECT_INSERTS", {})

    with pytest.raises(NotImplementedError, match="'sqlite' dialect"):
        await Team.objects.bulk_upsert([Team(name="X", headquarters="Y")])


async def test_bulk_upsert_rejects_non_positive_chunk_size():
    """A chunk size that would skip every write is refused."""
    with pytest.raises(ValueError, match="chunk_size"):
        await Team.objects.bulk_upsert([Team(name="X", headquarters="Y")], chunk_size=0)
    assert await Team.objects.count() == 0


@pytest.mark.parametrize("operation", ["update", "delete"])
async def test_bulk_operations_require_each_when_unfiltered(operation: str):
    """Unfiltered bulk update/delete raise unless each=True; filtered ones do not need it."""
    await Hero.objects.create(name="Spared", secret_name="S", age=1)
    kwargs = {"age": 2} if operation == "update" else {}

    for query in (Hero.objects, Hero.objects.filter(), Hero.objects.order_by(Hero.id)):
        with pytest.raises(ValueError, match="pass each=True"):
            await getattr(query, operation)(**kwargs)
    assert (await Hero.objects.get(name="Spared")).age == 1

    assert await getattr(Hero.objects.filter(age=1), operation)(**kwargs) == 1


async def test_update_without_values_does_nothing():
    """A filtered update() with no values touches no rows."""
    await Hero.objects.create(name="Still", secret_name="S", age=1)

    assert await Hero.objects.filter(age=1).update() == 0


@pytest.mark.parametrize("method", ["upsert", "bulk_upsert"])
async def test_update_fields_rejects_primary_key(method: str):
    """Listing the primary key in update_fields is refused before anything is written."""
    with pytest.raises(ValueError, match="cannot include the primary key"):
        await getattr(Team.objects, method)(
            [Team(name="X", headquarters="Y")] if method == "bulk_upsert" else Team(name="X", headquarters="Y"),
            on="name",
            update_fields=["id"],
        )
    assert await Team.objects.count() == 0
