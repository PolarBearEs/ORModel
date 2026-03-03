from pathlib import Path

from sqlmodel import Field, Session, SQLModel, create_engine, select


class SuperHero(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    secret_name: str
    age: int | None = None


def create_db_and_tables(engine):
    SQLModel.metadata.create_all(engine, tables=[SuperHero.__table__])


def create_heroes(engine):
    hero_1 = SuperHero(name="Deadpond", secret_name="Dive Wilson")
    hero_2 = SuperHero(name="Spider-Boy", secret_name="Pedro Parqueador")
    hero_3 = SuperHero(name="Rusty-Man", secret_name="Tommy Sharp", age=48)
    hero_4 = SuperHero(name="Tarantula", secret_name="Natalia Roman-on", age=32)
    hero_5 = SuperHero(name="Black Lion", secret_name="Trevor Challa", age=35)
    hero_6 = SuperHero(name="Dr. Weird", secret_name="Steve Weird", age=36)
    hero_7 = SuperHero(name="Captain North America", secret_name="Esteban Rogelios", age=93)

    with Session(engine) as session:
        session.add(hero_1)
        session.add(hero_2)
        session.add(hero_3)
        session.add(hero_4)
        session.add(hero_5)
        session.add(hero_6)
        session.add(hero_7)

        session.commit()


def select_heroes(engine):
    with Session(engine) as session:
        statement = select(SuperHero).where(SuperHero.age >= 35).where(SuperHero.age < 40)
        results = session.exec(statement)
        return list(results)


def main(tmp_path: Path):
    sqlite_url = f"sqlite:///{tmp_path / 'sqlmodel_test.db'}"
    engine = create_engine(sqlite_url, echo=False)
    create_db_and_tables(engine)
    create_heroes(engine)
    return select_heroes(engine)


def test_sqlmodel(tmp_path: Path):
    heroes = main(tmp_path)
    assert len(heroes) == 2
    names = sorted(hero.name for hero in heroes)
    assert names == ["Black Lion", "Dr. Weird"]
