# examples/standalone.py
import asyncio

# --- Import library components ---
from ormodel import (
    ORModel, DoesNotExist, MultipleObjectsReturned, # Core ORM classes/exceptions
    database_context, # <-- Use the context manager for setup/teardown
    get_session,      # <-- Use the session context manager
    get_engine,       # <-- Import helper to get the engine
    metadata          # <-- Import the metadata containing table definitions
)
# ---------------------------------

# --- Import example-specific config loader ---
try:
    from .config import get_settings
except ImportError:
    try: from examples.config import get_settings
    except ImportError: raise ImportError("Could not import get_settings from examples.config")
# ---------------------------------------------

# --- Import example models (needed for metadata population) ---
try:
    from .models import Hero, Team
except ImportError:
    try: from examples.models import Hero, Team
    except ImportError: raise ImportError("Could not import Hero, Team from examples.models")
# -----------------------------


async def create_schema(drop_existing: bool = False):
    """Helper function to create database tables."""
    print("--- [Standalone] Attempting to create schema... ---")
    engine = get_engine() # Get the engine initialized by database_context
    if engine is None:
        print("--- [Standalone] ERROR: Engine not available for schema creation. ---")
        return

    try:
        async with engine.begin() as conn:
            if drop_existing:
                print("--- [Standalone] Dropping existing tables (if any)... ---")
                await conn.run_sync(metadata.drop_all)
                print("--- [Standalone] Tables dropped. ---")

            print(f"--- [Standalone] Creating tables defined in metadata: {list(metadata.tables.keys())} ---")
            # create_all checks for table existence first by default (checkfirst=True)
            await conn.run_sync(metadata.create_all)
            print("--- [Standalone] Schema creation process finished. ---")
    except Exception as e:
        print(f"--- [Standalone] ERROR during schema creation: {type(e).__name__}: {e} ---")
        # Optionally re-raise or handle more gracefully
        raise


async def standalone_example():
    """Demonstrates using the ORM, including schema creation."""
    print("\n--- Running Standalone Example ---")
    settings = get_settings() # Load config for the example

    # --- Use the database_context ---
    try:
        # database_context handles init_database() and shutdown_database()
        async with database_context(settings.DATABASE_URL, echo_sql=False): # Set echo=True here for SQL logs
            print("--- [Standalone] Database context entered. ---")

            # --- Create Schema ---
            # Set drop_existing=True if you want a completely fresh DB each time
            await create_schema(drop_existing=True)
            # --------------------

            # --- Database tables should exist now, proceed with ORM operations ---
            async with get_session() as session:
                print(f"--- [Standalone] Session {id(session)} acquired. ---")
                # Create Teams
                team_preventers, _ = await Team.objects.update_or_create(name="Preventers", defaults={"headquarters": "Sharp Tower"})
                team_zforce, _ = await Team.objects.update_or_create(name="Z-Force", defaults={"headquarters": "Sister Margaret’s Bar"})
                print(f"--- [Standalone] Teams created/found: {team_preventers.name}, {team_zforce.name}")
                # Create Heroes
                hero_1, c1 = await Hero.objects.update_or_create(
                    name="Deadpond", secret_name="Dive Wilson",
                    defaults={"age": 28, "team_id": team_zforce.id}
                )
                hero_2, c2 = await Hero.objects.update_or_create(
                    name="Spider-Boy", secret_name="Pedro Parqueador",
                    defaults={"age": 16, "team_id": team_preventers.id}
                )
                hero_3, c3 = await Hero.objects.update_or_create(
                     name="Rusty-Man", secret_name="Tommy Sharp",
                     defaults={"age": 48, "team_id": team_preventers.id}
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