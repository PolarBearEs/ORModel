# examples/main.py
from contextlib import asynccontextmanager
from typing import List, Optional, Sequence

# --- FastAPI Imports ---
from fastapi import FastAPI, HTTPException, Query as FastAPIQuery, Request
from fastapi.responses import ORJSONResponse

# --- Import library components (NO database setup parts) ---
from ormodel import (
    ORModel, DoesNotExist, MultipleObjectsReturned,  # Core ORM classes/exceptions
    init_database, get_session,  # Library's session/init functions
    get_session_from_context, shutdown_database  # Needed if manager is used directly sometimes
)

# --- Import example-specific config loader ---
try:
    from .config import get_settings
except ImportError:
    # Handle case where config might be run from root in some scenarios
    try: from examples.config import get_settings
    except ImportError: raise ImportError("Could not import get_settings from examples.config")
# ---------------------------------------------

# --- Import example models ---
try:
    from .models import Hero, Team
except ImportError:
    try: from examples.models import Hero, Team
    except ImportError: raise ImportError("Could not import Hero, Team from examples.models")
# -----------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles application startup and shutdown events."""
    print("--- [Lifespan] FastAPI app starting up... ---")
    settings = get_settings()
    print(f"--- [Lifespan] Initializing database with URL: {settings.DATABASE_URL} ---")
    try:
        init_database(database_url=settings.DATABASE_URL, echo_sql=settings.ECHO_SQL)
    except Exception as e:
        print(f"--- [Lifespan] FATAL: Database initialization failed: {type(e).__name__}: {e} ---")
        raise RuntimeError("Could not initialize database.") from e

    yield # Application runs here

    print("--- [Lifespan] FastAPI app shutting down... ---")
    # --- Call the library's shutdown function ---
    try:
        await shutdown_database() # <-- Call the library function
        # Optional: Add confirmation log here if needed
        # print("--- [Lifespan] Library database shutdown completed.")
    except Exception as e:
        # Should be rare if shutdown_database handles its own errors, but catch just in case
        print(f"--- [Lifespan] Error calling shutdown_database: {type(e).__name__}: {e} ---")
    # ------------------------------------------

# --- FastAPI App ---
app = FastAPI(
    title="ORModel Example API",
    lifespan=lifespan, # Use the lifespan context manager
    default_response_class=ORJSONResponse # Use faster JSON response class
)

# --- Middleware (uses get_session from ormodel library) ---
@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    """
    Manages the database session scope for each request using the
    library's initialized session factory and context variable.
    """
    response = None
    session_was_active = False
    try:
        # Use get_session FROM THE LIBRARY (which is now initialized via lifespan)
        async with get_session() as session:
            session_was_active = session.is_active
            # print(f"--- [Middleware] Request {request.method} {request.url.path}: Session {id(session)} acquired. ---") # Debug
            response = await call_next(request) # Process the request
            # Commit only if the session is still active after the handler finishes
            if session.is_active:
                # print(f"--- [Middleware] Request {request.method} {request.url.path}: Committing session {id(session)}. ---") # Debug
                await session.commit()
            # else:
                # print(f"--- [Middleware] Request {request.method} {request.url.path}: Session {id(session)} inactive, commit skipped. ---") # Debug

    except Exception as e:
        # Rollback is handled by the get_session context manager's except block
        print(f"--- [Middleware] Request {request.method} {request.url.path}: Exception caught ({type(e).__name__}), raising. ---") # Debug
        raise e # Re-raise exception for FastAPI error handling

    # Ensure a response is returned. Middleware must return a response.
    if response is None:
        # This might happen if call_next succeeded but commit failed, and get_session didn't re-raise
        # Or if an error happened very early before call_next.
        print(f"--- [Middleware] Request {request.method} {request.url.path}: Response is None after try block, returning 500. ---")
        return ORJSONResponse(status_code=500, content={"detail": "Internal server error during request processing."})

    return response
# ---------------------------------------------------------


# --- API Request/Response Models (Inherit from ORModel) ---
# Using ORModel directly works, but dedicated Pydantic models might be cleaner.
class HeroCreate(ORModel):
    name: str
    secret_name: str
    age: Optional[int] = None
    team_id: Optional[int] = None
    model_config = { "exclude": {"id", "team"} } # Exclude fields not expected in create payload

class HeroRead(ORModel):
    id: int
    name: str
    secret_name: str
    age: Optional[int] = None
    team_id: Optional[int] = None
    # Exclude relationships by default unless explicitly requested/configured
    model_config = { "exclude": {"team"} }

class HeroUpdate(ORModel):
    name: Optional[str] = None
    secret_name: Optional[str] = None
    age: Optional[int] = None
    team_id: Optional[int] = None
    model_config = { "exclude": {"id", "team"} } # Cannot update ID or relationship directly here

class TeamCreate(ORModel):
    name: str
    headquarters: str
    model_config = { "exclude": {"id", "heroes"} }

class TeamRead(ORModel):
    id: int
    name: str
    headquarters: str
    model_config = { "exclude": {"heroes"} }


# --- API Endpoints ---
# These endpoints use the Model.objects manager, which implicitly uses the
# session provided by the middleware via the db_session_context variable.

@app.post("/teams/", response_model=TeamRead, status_code=201)
async def create_new_team(team_data: TeamCreate):
    """Creates a new team, handling potential duplicates."""
    # Use get_or_create to prevent duplicates based on name
    team, created = await Team.objects.get_or_create(
        name=team_data.name,
        defaults={'headquarters': team_data.headquarters}
    )
    if not created:
         raise HTTPException(status_code=409, detail=f"Team with name '{team_data.name}' already exists.")
    return team


@app.get("/teams/", response_model=List[TeamRead])
async def read_all_teams(skip: int = 0, limit: int = 100):
    """Reads all teams with pagination."""
    # Session context is managed by middleware
    # Add offset/limit to Query class for efficiency on large datasets
    teams = await Team.objects.all() # Gets a Sequence
    return list(teams)[skip : skip + limit]

@app.post("/heroes/", response_model=HeroRead, status_code=201)
async def create_new_hero(hero_data: HeroCreate):
    """Creates a new hero."""
    try:
        hero = await Hero.objects.create(**hero_data.model_dump(exclude_unset=True))
        return hero
    except Exception as e:
        # Rollback should be handled by middleware/get_session
        raise HTTPException(status_code=400, detail=f"Error creating hero: {type(e).__name__}: {e}")

@app.get("/heroes/", response_model=List[HeroRead])
async def read_all_heroes(
    skip: int = 0,
    limit: int = 100,
    name: Optional[str] = None,
    min_age: Optional[int] = FastAPIQuery(None, description="Minimum age of hero"),
    team_name: Optional[str] = None,
):
    """Reads heroes with optional filtering and pagination."""
    query = Hero.objects.filter() # Start with base query
    if name:
        query = query.filter(Hero.name.ilike(f"%{name}%"))
    if min_age is not None:
        query = query.filter(Hero.age >= min_age)
    if team_name:
         # Use join based on relationship definition
        query = query.join(Hero.team).filter(Team.name == team_name)

    # Fetch all filtered then slice (less efficient for large offsets)
    # For production, implement .offset().limit() in the Query class
    all_filtered_heroes: Sequence[Hero] = await query.order_by(Hero.id).all()
    heroes = list(all_filtered_heroes)[skip : skip + limit]
    return heroes

@app.get("/heroes/{hero_id}", response_model=HeroRead)
async def read_single_hero(hero_id: int):
    """Reads a single hero by ID."""
    try:
        hero = await Hero.objects.get(id=hero_id)
        return hero
    except DoesNotExist:
        raise HTTPException(status_code=404, detail="Hero not found")
    except MultipleObjectsReturned: # Should not happen with PK get
         raise HTTPException(status_code=500, detail="Internal server error: Multiple heroes found with same ID")

@app.patch("/heroes/{hero_id}", response_model=HeroRead)
async def update_single_hero(hero_id: int, hero_update: HeroUpdate):
    """Updates a hero by ID."""
    session = get_session_from_context() # Get session for manual operations if needed
    try:
        hero = await Hero.objects.get(id=hero_id) # Fetch the hero
        update_data = hero_update.model_dump(exclude_unset=True)
        if not update_data:
             raise HTTPException(status_code=400, detail="No update data provided")

        # Apply updates
        for key, value in update_data.items():
             setattr(hero, key, value)

        session.add(hero) # Mark as dirty
        # Flush and refresh before returning to ensure data is updated
        await session.flush()
        await session.refresh(hero)
        return hero
    except DoesNotExist:
        raise HTTPException(status_code=404, detail="Hero not found")
    except Exception as e:
        # Rollback handled by middleware/get_session
        raise HTTPException(status_code=400, detail=f"Error updating hero: {type(e).__name__}: {e}")

@app.delete("/heroes/{hero_id}", status_code=204) # 204 No Content
async def delete_single_hero(hero_id: int):
    """Deletes a hero by ID."""
    try:
        hero = await Hero.objects.get(id=hero_id)
        await Hero.objects.delete(hero) # Uses manager's delete -> session.delete/flush
        return None # Return None or Response(status_code=204)
    except DoesNotExist:
        raise HTTPException(status_code=404, detail="Hero not found")
    except Exception as e:
        # Rollback handled by middleware/get_session
        raise HTTPException(status_code=400, detail=f"Error deleting hero: {type(e).__name__}: {e}")


# --- Standalone Example (Needs explicit init) ---



# --- __main__ block ---
if __name__ == "__main__":
    # Load settings here just for initial console output
    # The actual initialization happens in the lifespan manager
    settings = get_settings()
    print(f"\n--- Running FastAPI Server (from api.py) ---")
    print(f"Loaded example settings: DB URL = {settings.DATABASE_URL}")
    print("Starting FastAPI server with uvicorn...")
    import uvicorn
    uvicorn.run(
        # Point to the app object in this file
        "examples.api:app",
        host="0.0.0.0",
        port=8000,
        reload=True, # Enable auto-reload for development
        reload_dirs=["examples", "ormodel"], # Watch both example and library code
        log_level="info",
        # Uvicorn can load .env directly too if needed:
        # env_file="examples/.env"
    )