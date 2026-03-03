import asyncio

from sqlmodel import col

from ormodel import database_context, get_engine, get_session, metadata

from .config import get_settings
from .models import Hero, Team


class TeamRepository:
    async def get_by_name(self, name: str) -> Team | None:
        return await Team.objects.filter(name=name).one_or_none()

    async def create(self, name: str, headquarters: str) -> Team:
        return await Team.objects.create(name=name, headquarters=headquarters)


class HeroRepository:
    async def create(self, *, name: str, secret_name: str, age: int | None, team_id: int | None) -> Hero:
        return await Hero.objects.create(name=name, secret_name=secret_name, age=age, team_id=team_id)

    async def list_adults(self) -> list[Hero]:
        query = Hero.objects.filter(col(Hero.age) >= 18).order_by(Hero.name)
        return list(await query.all())


class HeroService:
    def __init__(self, heroes: HeroRepository, teams: TeamRepository):
        self.heroes = heroes
        self.teams = teams

    async def register_hero(
        self,
        *,
        name: str,
        secret_name: str,
        age: int | None,
        team_name: str | None = None,
        team_headquarters: str = "Unknown",
    ) -> Hero:
        team_id: int | None = None
        if team_name:
            team = await self.teams.get_by_name(team_name)
            if team is None:
                team = await self.teams.create(name=team_name, headquarters=team_headquarters)
            team_id = team.id
        return await self.heroes.create(name=name, secret_name=secret_name, age=age, team_id=team_id)


async def create_schema(drop_existing: bool = False) -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        if drop_existing:
            await conn.run_sync(metadata.drop_all)
        await conn.run_sync(metadata.create_all)


async def main() -> None:
    settings = get_settings()
    async with database_context(settings.DATABASE_URL, echo_sql=False):
        await create_schema(drop_existing=True)

        # Write operations in one transaction.
        async with get_session():
            service = HeroService(HeroRepository(), TeamRepository())
            await service.register_hero(
                name="Deadpond",
                secret_name="Dive Wilson",
                age=28,
                team_name="Z-Force",
                team_headquarters="Sister Margaret's Bar",
            )
            await service.register_hero(
                name="Spider-Boy",
                secret_name="Pedro Parqueador",
                age=16,
                team_name="Preventers",
                team_headquarters="Sharp Tower",
            )

        # Read operations in a new transaction.
        async with get_session():
            adults = await HeroRepository().list_adults()
            for hero in adults:
                print(f"{hero.name} ({hero.age})")


if __name__ == "__main__":
    asyncio.run(main())
