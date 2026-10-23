# examples/standalone.py
import asyncio

from ormodel import create_tables, database_context, get_session

from .config import get_settings
from .models import Hero, Team


async def standalone_example():
    """Demonstrates using the ORM, including schema creation."""
    print("\n--- Running Standalone Example ---")
    settings = get_settings()  # Load config for the example

    # --- Use the database_context ---
    try:
        # database_context handles init_database() and shutdown_database()
        async with database_context(settings.DATABASE_URL, echo_sql=False):  # Set echo=True here for SQL logs
            print("--- [Standalone] Database context entered. ---")

            # --- Create Schema ---
            # Set drop_existing=True if you want a completely fresh DB each time
            await create_tables(drop_existing=True)
            # --------------------

            # --- Database tables should exist now, proceed with ORM operations ---
            async with get_session() as session:
                print(f"--- [Standalone] Session {id(session)} acquired. ---")
                # Create Teams
                team_preventers, _ = await Team.objects.upsert(
                    Team(name="Preventers", headquarters="Sharp Tower"), on=Team.name
                )
                team_zforce, _ = await Team.objects.upsert(
                    Team(name="Z-Force", headquarters="Sister Margaret’s Bar"), on=Team.name
                )
                print(f"--- [Standalone] Teams created/found: {team_preventers.name}, {team_zforce.name}")
                # Create Heroes
                lookup = [Hero.name, Hero.secret_name]
                hero_1, c1 = await Hero.objects.upsert(
                    Hero(name="Deadpond", secret_name="Dive Wilson", age=28, team_id=team_zforce.id), on=lookup
                )
                hero_2, c2 = await Hero.objects.upsert(
                    Hero(name="Spider-Boy", secret_name="Pedro Parqueador", age=16, team_id=team_preventers.id),
                    on=lookup,
                )
                hero_3, c3 = await Hero.objects.upsert(
                    Hero(name="Rusty-Man", secret_name="Tommy Sharp", age=48, team_id=team_preventers.id), on=lookup
                )
                print(f"--- [Standalone] Hero created/found: {hero_1.name}, {hero_2.name}, {hero_3.name}")

                # Perform queries
                deadpond = await Hero.objects.get(name="Deadpond")
                print(f"--- [Standalone] Found hero: {deadpond.name}, Age: {deadpond.age}")
                preventers_count = await Hero.objects.filter(team_id=team_preventers.id).count()
                print(f"--- [Standalone] Preventers count: {preventers_count}")

                # Update
                spider_boy = await Hero.objects.get(name="Spider-Boy")
                spider_boy.age = 17
                session.add(spider_boy)
                await session.flush()

                # Commit happens implicitly at end of 'async with get_session()' if no error
                print(f"--- [Standalone] Committing session {id(session)}... ---")
            # --- Session context exits ---
            print("--- [Standalone] Session context exited. ---")
        # --- Database context exits, shutdown_database is called ---
        print("--- [Standalone] Database context exited. ---")
    except Exception as e:
        # Catch errors during context setup, schema creation, or ORM ops
        print(f"--- [Standalone] ERROR during operations: {type(e).__name__}: {e} ---")
        import traceback

        traceback.print_exc()

    print("--- [Standalone] Example finished. ---")


# --- Runnable block ---
if __name__ == "__main__":
    print("Running standalone script directly...")
    asyncio.run(standalone_example())
