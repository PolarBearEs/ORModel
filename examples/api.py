from collections.abc import Sequence
from contextlib import asynccontextmanager

# --- FastAPI Imports ---
from fastapi import FastAPI, HTTPException, Request
from fastapi import Query as FastAPIQuery
from fastapi.responses import ORJSONResponse

# --- Import library components ---
from ormodel import (
    DoesNotExist,
    MultipleObjectsReturned,  # Core ORM classes/exceptions
    ORModel,
    get_session,  # Library's session/init functions
    get_session_from_context,
    init_database,
    shutdown_database,
)

# --- Import example-specific config loader ---
try:
    from .config import get_settings
except ImportError:
    try:
        from examples.config import get_settings
    except ImportError:
        raise ImportError("Could not import get_settings from examples.config")
# ---------------------------------------------

# --- Import example models ---
try:
    from .models import Hero, Team
except ImportError:
    try:
        from examples.models import Hero, Team
    except ImportError:
        raise ImportError("Could not import Hero, Team from examples.models")
# -----------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles application startup and shutdown events."""
    print("--- [Lifespan] FastAPI app starting up... ---")
    settings = get_settings()
    init_database(database_url=settings.DATABASE_URL, echo_sql=settings.ECHO_SQL)
    yield
    print("--- [Lifespan] FastAPI app shutting down... ---")
    await shutdown_database()


# --- FastAPI App ---
app = FastAPI(title="ORModel Example API", lifespan=lifespan, default_response_class=ORJSONResponse)


@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    """
    Manages the database session scope for each request.
    The `get_session` context manager now handles commit and rollback automatically.
    """
    try:
        # Simply wrap the request processing in the transactional context.
        # If call_next() succeeds, get_session() commits.
        # If call_next() raises an exception, get_session() rolls back.
        async with get_session():
            response = await call_next(request)
        return response
    except Exception as e:
        # The exception was already handled (rolled back) by get_session,
        # but we re-raise it so FastAPI can generate the appropriate
        # HTTP error response.
        raise e


# --- API Request/Response Models (Inherit from ormodel.ORModel) ---
class HeroCreate(ORModel):
    name: str
    secret_name: str
    age: int | None = None
    team_id: int | None = None


class HeroRead(ORModel):
    id: int
    name: str
    secret_name: str
    age: int | None = None
    team_id: int | None = None


class HeroUpdate(ORModel):
    name: str | None = None
    secret_name: str | None = None
    age: int | None = None
    team_id: int | None = None


class TeamCreate(ORModel):
    name: str
    headquarters: str


class TeamRead(ORModel):
    id: int
    name: str
    headquarters: str


# --- API Endpoints ---
# These endpoints remain unchanged, as they were already correctly using
# the manager, which relies on the session provided by the middleware.


@app.post("/teams/", response_model=TeamRead, status_code=201)
async def create_new_team(team_data: TeamCreate):
    """Creates a new team, handling potential duplicates."""
    team, created = await Team.objects.get_or_create(
        name=team_data.name, defaults={"headquarters": team_data.headquarters}
    )
    if not created:
        raise HTTPException(status_code=409, detail=f"Team with name '{team_data.name}' already exists.")
    return team


@app.get("/teams/", response_model=list[TeamRead])
async def read_all_teams(skip: int = 0, limit: int = 100):
    """Reads all teams with pagination."""
    teams_seq = await Team.objects.all()
    return list(teams_seq)[skip : skip + limit]


@app.post("/heroes/", response_model=HeroRead, status_code=201)
async def create_new_hero(hero_data: HeroCreate):
    """Creates a new hero."""
    try:
        hero = await Hero.objects.create(**hero_data.model_dump(exclude_unset=True))
        return hero
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error creating hero: {type(e).__name__}: {e}")


@app.get("/heroes/", response_model=list[HeroRead])
async def read_all_heroes(
    skip: int = 0,
    limit: int = 100,
    name: str | None = None,
    min_age: int | None = FastAPIQuery(None, description="Minimum age of hero"),
    team_name: str | None = None,
):
    """Reads heroes with optional filtering and pagination."""
    query = Hero.objects.filter()  # Start with base query
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
    except MultipleObjectsReturned:
        raise HTTPException(status_code=500, detail="Internal server error: Multiple heroes found with same ID")


@app.patch("/heroes/{hero_id}", response_model=HeroRead)
async def update_single_hero(hero_id: int, hero_update: HeroUpdate):
    """Updates a hero by ID."""
    session = get_session_from_context()
    try:
        hero = await Hero.objects.get(id=hero_id)
        update_data = hero_update.model_dump(exclude_unset=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="No update data provided")

        for key, value in update_data.items():
            setattr(hero, key, value)

        await hero.save()
        return hero
    except DoesNotExist:
        raise HTTPException(status_code=404, detail="Hero not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error updating hero: {type(e).__name__}: {e}")


@app.delete("/heroes/{hero_id}", status_code=204)
async def delete_single_hero(hero_id: int):
    """Deletes a hero by ID."""
    try:
        hero = await Hero.objects.get(id=hero_id)
        await hero.delete()
        return None
    except DoesNotExist:
        raise HTTPException(status_code=404, detail="Hero not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error deleting hero: {type(e).__name__}: {e}")


# --- __main__ block ---
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "examples.api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=["examples", "ormodel"],
        log_level="info",
    )
