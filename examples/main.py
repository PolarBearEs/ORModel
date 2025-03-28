import asyncio
from contextlib import asynccontextmanager
from typing import List, Optional, Sequence

from fastapi import Depends, FastAPI, HTTPException, Query as FastAPIQuery
from fastapi.responses import ORJSONResponse # Example using orjson

# Import from your library using the NEW name
from ormodel import (         # <-- Updated import
    ORModel,                 # Your base model
    get_session,
    DoesNotExist,
    MultipleObjectsReturned,
    engine,                   # Import engine if needed
    metadata,                 # Import metadata if needed
    get_session_from_context  # Import if needed directly
)
# Import config if needed directly
from ormodel.config import get_settings

# Import from your example models
from examples.models import Hero, Team # Adjust import path if needed

# --- FastAPI Lifespan for DB connection (optional but good practice) ---
# Optional: Define create_db function if needed for tests/dev (Alembic is primary)
async def create_db_and_tables():
     # print("!!! WARNING: Running create_db_and_tables. Use Alembic for production. !!!")
     # async with engine.begin() as conn:
     #     await conn.run_sync(metadata.drop_all) # Use with caution! Drops tables!
     #     await conn.run_sync(metadata.create_all)
     # print("Database tables created (or dropped and recreated).")
     pass # Rely on Alembic


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("FastAPI app starting up...")
    # Optional: Run create_db_and_tables on startup (DEV/TEST ONLY)
    # await create_db_and_tables()
    yield
    print("FastAPI app shutting down...")
    # Clean up resources like the engine's connection pool
    await engine.dispose()
    print("Database connection pool disposed.")

# --- FastAPI App ---
# Use ORJSONResponse for potentially faster JSON handling
app = FastAPI(title="ORModel Example API", lifespan=lifespan, default_response_class=ORJSONResponse)

# --- Middleware to provide session context ---
# This is crucial for making the Manager work implicitly via contextvars
@app.middleware("http")
async def db_session_middleware(request, call_next):
    response = None
    session_context = None
    try:
        # Start the session context using the generator
        async with get_session() as session:
            session_context = session # Keep reference if needed for logging etc.
            # print(f"Request {request.url.path}: Session {id(session)} acquired.") # Debug
            response = await call_next(request)
            # If request handler didn't raise exception, commit.
            # Rollback happens automatically in get_session on exception.
            if session.is_active: # Check if not rolled back already
                 # print(f"Request {request.url.path}: Committing session {id(session)}.") # Debug
                 await session.commit()
    except Exception as e:
        # Rollback is handled by the 'async with get_session()' context manager
        # print(f"Request {request.url.path}: Exception occurred, rollback initiated by context manager.") # Debug
        # Ensure a response is returned even if an error occurs before call_next completes
        # or if commit fails. FastAPI's exception handlers should take over.
        if response is None:
             # Re-raise the exception to be handled by FastAPI's default handler
             # or any custom exception handlers you've defined.
             raise e
    finally:
        # print(f"Request {request.url.path}: Session context finished.") # Debug
        pass # Cleanup (resetting context var) is handled by get_session

    # If we got here without re-raising, return the response from call_next
    # or the response generated during exception handling if applicable
    # (though standard practice is to let FastAPI handle final response generation on error)
    return response


# --- API Endpoints ---

# Pydantic models for request/response (can use ORModel directly too)
class HeroCreate(ORModel): # Use ORModel for input validation
    name: str
    secret_name: str
    age: Optional[int] = None
    team_id: Optional[int] = None

class HeroRead(ORModel): # Use ORModel for output structure
    id: int
    name: str
    secret_name: str
    age: Optional[int] = None
    team_id: Optional[int] = None

class HeroUpdate(ORModel):
    name: Optional[str] = None
    secret_name: Optional[str] = None
    age: Optional[int] = None
    team_id: Optional[int] = None

class TeamCreate(ORModel):
    name: str
    headquarters: str

class TeamRead(ORModel):
    id: int
    name: str
    headquarters: str

# Dependency to get session (alternative to middleware if needed per-route)
# async def get_db_session():
#     async with get_session() as session:
#         yield session


@app.post("/teams/", response_model=TeamRead, status_code=201)
async def create_new_team(team_data: TeamCreate):
    """Creates a new team."""
    try:
        # Use get_or_create to prevent duplicates based on name
        team, created = await Team.objects.get_or_create(
            name=team_data.name,
            defaults={'headquarters': team_data.headquarters}
        )
        if not created:
             raise HTTPException(status_code=409, detail=f"Team with name '{team_data.name}' already exists.")
        return team
    except Exception as e:
        # Catch specific DB errors (like unique constraints if not using get_or_create)
        raise HTTPException(status_code=400, detail=f"Error creating team: {e}")

@app.get("/teams/", response_model=List[TeamRead])
async def read_all_teams(skip: int = 0, limit: int = 100):
    """Reads all teams with pagination."""
    # Session context is managed by middleware
    teams = await Team.objects.all() # Gets a Sequence
    # Apply slicing after fetching. For large datasets, add .offset().limit() to Query class
    return list(teams)[skip : skip + limit] # Convert Sequence to list for slicing if needed


@app.post("/heroes/", response_model=HeroRead, status_code=201)
async def create_new_hero(hero_data: HeroCreate):
    """Creates a new hero."""
    # Session context managed by middleware
    try:
        # Use the .objects manager from the library's ORModel base
        # Pass validated data using model_dump
        hero = await Hero.objects.create(**hero_data.model_dump(exclude_unset=True))
        return hero
    except Exception as e:
        # Handle potential database errors (e.g., unique constraint, foreign key)
        # Consider more specific error handling based on DB exceptions
        await get_session_from_context().rollback() # Ensure rollback if create fails partially
        raise HTTPException(status_code=400, detail=f"Error creating hero: {e}")


@app.get("/heroes/", response_model=List[HeroRead])
async def read_all_heroes(
    skip: int = 0,
    limit: int = 100,
    name: Optional[str] = None,
    min_age: Optional[int] = FastAPIQuery(None, description="Minimum age of hero"),
    team_name: Optional[str] = None,
):
    """Reads heroes with optional filtering and pagination."""
    # Session context is managed by middleware
    query = Hero.objects.filter() # Start with base query

    if name:
        # Example using SQLAlchemy binary expression for case-insensitive search
        query = query.filter(Hero.name.ilike(f"%{name}%"))

    if min_age is not None:
        # Example using SQLAlchemy binary expression for greater than or equal
        query = query.filter(Hero.age >= min_age)

    if team_name:
        # Example filtering based on related field (requires JOIN implicitly or explicitly)
        # ORModel/SQLAlchemy handles the join based on the relationship
        query = query.filter(Team.name == team_name).join(Team) # Explicit join might be needed depending on query complexity

    # Apply ordering and pagination *before* executing .all() for efficiency
    # Requires limit/offset methods in Query class
    # heroes_query = query.order_by(Hero.id).offset(skip).limit(limit)
    # heroes = await heroes_query.all()

    # Simpler version: Fetch filtered then slice (less efficient for large offsets)
    heroes_query = query.order_by(Hero.id)
    all_filtered_heroes: Sequence[Hero] = await heroes_query.all() # Execute the query
    heroes = list(all_filtered_heroes)[skip : skip + limit]

    return heroes

@app.get("/heroes/{hero_id}", response_model=HeroRead)
async def read_single_hero(hero_id: int):
    """Reads a single hero by ID."""
    try:
        # Using .get() which expects kwargs for unique identification
        hero = await Hero.objects.get(id=hero_id)
        # .get() raises DoesNotExist or MultipleObjectsReturned automatically
        return hero
    except DoesNotExist:
        raise HTTPException(status_code=404, detail="Hero not found")
    except MultipleObjectsReturned: # Should not happen with PK get, but good practice
         raise HTTPException(status_code=500, detail="Internal server error: Multiple heroes found with same ID")


@app.patch("/heroes/{hero_id}", response_model=HeroRead)
async def update_single_hero(hero_id: int, hero_update: HeroUpdate):
    """Updates a hero by ID."""
    session = get_session_from_context() # Get session if needed for manual operations
    try:
        hero = await Hero.objects.get(id=hero_id) # Fetch the hero

        # Use ORModel's helper for validated updates
        update_data = hero_update.model_dump(exclude_unset=True) # Only include fields present in request
        if not update_data:
             raise HTTPException(status_code=400, detail="No update data provided")

        # Apply updates
        for key, value in update_data.items():
             setattr(hero, key, value)

        session.add(hero) # Add to session to mark as dirty
        # Flush and refresh are important here before returning, commit is handled by middleware
        await session.flush()
        await session.refresh(hero)
        return hero

    except DoesNotExist:
        raise HTTPException(status_code=404, detail="Hero not found")
    except Exception as e:
        # await session.rollback() # Rollback handled by middleware/context manager
        raise HTTPException(status_code=400, detail=f"Error updating hero: {e}")


@app.delete("/heroes/{hero_id}", status_code=204) # 204 No Content on successful deletion
async def delete_single_hero(hero_id: int):
    """Deletes a hero by ID."""
    try:
        hero = await Hero.objects.get(id=hero_id)
        await Hero.objects.delete(hero) # Use the manager's delete method
        # Flush handled by delete method, commit handled by middleware
        return None # Return None or Response(status_code=204)
    except DoesNotExist:
        raise HTTPException(status_code=404, detail="Hero not found")
    except Exception as e:
        # Rollback handled by middleware/context manager
        raise HTTPException(status_code=400, detail=f"Error deleting hero: {e}")


# --- Standalone Async Example (for testing outside web server) ---
async def standalone_example():
    print("\n--- Running Standalone Example ---")
    # Need to use the context manager manually outside of web requests
    async with get_session() as session: # Session is set in context here
        print(f"Session in context: {session is not None}")

        # Create Teams
        print("Creating teams...")
        team_preventers, _ = await Team.objects.update_or_create(name="Preventers", defaults={"headquarters": "Sharp Tower"})
        team_zforce, _ = await Team.objects.update_or_create(name="Z-Force", defaults={"headquarters": "Sister Margaret’s Bar"})
        print(f"Teams created/found: {team_preventers.name}, {team_zforce.name}")

        # Create Heroes
        print("Creating heroes...")
        hero_1, created_1 = await Hero.objects.update_or_create(
            name="Deadpond", secret_name="Dive Wilson",
            defaults={"age": 28, "team_id": team_zforce.id}
        )
        hero_2, created_2 = await Hero.objects.update_or_create(
            name="Spider-Boy", secret_name="Pedro Parqueador",
            defaults={"age": 16, "team_id": team_preventers.id}
         )
        hero_3, created_3 = await Hero.objects.update_or_create(
             name="Rusty-Man", secret_name="Tommy Sharp",
             defaults={"age": 48, "team_id": team_preventers.id}
        )
        print(f"Hero 1: {hero_1.name}, Created: {created_1}")
        print(f"Hero 2: {hero_2.name}, Created: {created_2}")
        print(f"Hero 3: {hero_3.name}, Created: {created_3}")

        # Filter and Get
        print("Finding heroes...")
        try:
            deadpond = await Hero.objects.get(name="Deadpond")
            print(f"Found by name: {deadpond.name}, Age: {deadpond.age}")
        except DoesNotExist:
            print("Deadpond not found by get(name=...)")


        print("Finding Preventers heroes...")
        preventers_heroes = await Hero.objects.filter(team_id=team_preventers.id).order_by(Hero.name).all()
        # Alternative filter using relationship (SQLAlchemy handles join)
        # preventers_heroes = await Hero.objects.filter(Hero.team.has(Team.name == "Preventers")).all()
        print(f"Preventers heroes: {[h.name for h in preventers_heroes]}")

        # Count
        total_heroes = await Hero.objects.count()
        print(f"Total heroes count: {total_heroes}")
        preventers_count = await Hero.objects.filter(team_id=team_preventers.id).count()
        print(f"Preventers heroes count: {preventers_count}")


        # Update (using fetch and save pattern, commit is implicit via context)
        print("Updating Spider-Boy's age...")
        spider_boy = await Hero.objects.get(name="Spider-Boy")
        spider_boy.age = 17
        session.add(spider_boy) # Add instance to session to track changes
        # Flush happens automatically on commit or can be manual: await session.flush()

        # Verify update after context exits and commits
        # (Need another session block to verify)

    # Session implicitly committed here if no exceptions occurred

    print("--- Verifying changes in new session ---")
     async with get_session() as session:
         spider_boy_updated = await Hero.objects.get(name="Spider-Boy")
         print(f"Verified Spider-Boy age: {spider_boy_updated.age}")

         print(f"Attempting to delete {deadpond.name}...")
         await Hero.objects.delete(deadpond)
         print(f"{deadpond.name} marked for deletion.")

    # Session implicitly committed here

    print("--- Verifying deletion in new session ---")
    async with get_session() as session:
        try:
            await Hero.objects.get(name="Deadpond")
        except DoesNotExist:
            print(f"{deadpond.name} successfully deleted.")
        remaining_heroes = await Hero.objects.count()
        print(f"Remaining heroes: {remaining_heroes}")


    print("Standalone example finished.")


if __name__ == "__main__":
    # Load .env file explicitly if running directly (uvicorn --env-file handles it too)
    from dotenv import load_dotenv
    env_loaded = load_dotenv()
    if not env_loaded:
         print("Warning: .env file not found or not loaded.")

    # Check settings after attempting to load .env
    current_settings = get_settings()
    print(f"Loaded settings: DB URL = {current_settings.DATABASE_URL}")
    print(f"Loaded settings: Alembic URL = {current_settings.ALEMBIC_DATABASE_URL}")
    print(f"Loaded settings: Echo SQL = {current_settings.ECHO_SQL}")


    # --- Choose how to run ---

    # Option 1: Run standalone async example function
    # print("Running standalone example...")
    # asyncio.run(standalone_example())
    # print("Standalone example complete.")

    # Option 2: Run FastAPI app with uvicorn (Comment out Option 1)
    print("Starting FastAPI server with uvicorn...")
    import uvicorn
    uvicorn.run(
        "examples.main:app", # Path to the app object
        host="0.0.0.0",
        port=8000,
        reload=True, # Enable auto-reload for development
        # reload_dirs=["ormodel", "examples"], # Specify dirs to watch for reload
        log_level="info",
        # env_file=".env" # Uvicorn can also load .env directly
    )