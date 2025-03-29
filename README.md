# ORModel

An asynchronous ORM library leveraging SQLModel features, providing a Django ORM-like query syntax (`Model.objects`). Built for use with `asyncio` and frameworks like FastAPI. Managed with `uv`.

## Features

*   **Model Definition:** Inherit from `ormodel.ORModel` (built upon `sqlmodel`). Define schema using `sqlmodel.Field`.
*   **Django-Style Manager:** Access database operations via `YourModel.objects`.
*   **Async Queries:** `.all()`, `.filter()`, `.get()`, `.create()`, `.get_or_create()`, `.update_or_create()`, `.count()`, `.delete()`.
*   **Application-Managed DB Lifecycle:** Library provides `ormodel.init_database`, `ormodel.shutdown_database`, and `ormodel.database_context` for setup/teardown, but the application calls them.
*   **Session Scoping:** Library provides `ormodel.get_session` async context manager. Application must use this (e.g., in middleware) for the implicit `Model.objects` manager to work.
*   **Uses SQLAlchemy 2.0+:** Leverages modern async SQLAlchemy.
*   **Alembic Compatible:** Designed for use with Alembic for database migrations (managed by the application).

## Installation

Requires Python 3.8+ and `uv`.

1.  **Clone the repository (or create files from source):**
    ```bash
    # git clone https://github.com/yourusername/ormodel.git
    cd ormodel
    ```

2.  **Create and activate virtual environment:**
    ```bash
    uv venv .venv
    source .venv/bin/activate  # or .\venv\Scripts\activate on Windows
    ```

3.  **Install:**
    ```bash
    # Install in editable mode with development dependencies
    uv pip install -e ".[dev]"
    ```

## Configuration (Application Responsibility)

**Example (`examples/.env`):**

```dotenv
# Async database connection string for the application
DATABASE_URL="sqlite+aiosqlite:///./example_app.db"
# Example: DATABASE_URL="postgresql+asyncpg://user:pass@host/db"

# Sync database connection string for Alembic migrations
ALEMBIC_DATABASE_URL="sqlite:///./example_app.db"
# Example: ALEMBIC_DATABASE_URL="postgresql+psycopg2://user:pass@host/db"

# Optional: Echo SQL statements
ECHO_SQL=False
```

## Usage Guide

### 1. Database Initialization & Shutdown (Application)

Your application must initialize the ORModel database connection pool on startup and shut it down gracefully on exit.

**For Servers (e.g., FastAPI Lifespan):**

```python
# examples/api.py (FastAPI Lifespan Snippet)
from contextlib import asynccontextmanager
from fastapi import FastAPI
# Import library functions and application's config loader
from ormodel import init_database, shutdown_database
from examples.config import get_settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings() # Load app config
    print(f"Initializing database: {settings.DATABASE_URL}")
    init_database(database_url=settings.DATABASE_URL, echo_sql=settings.ECHO_SQL)
    yield # Application runs
    print("Shutting down database...")
    await shutdown_database()

app = FastAPI(lifespan=lifespan)
```

**For Standalone Scripts:**

Use the `ormodel.database_context` manager.

```python
# examples/standalone.py (Snippet)
import asyncio
from ormodel import database_context, get_session # ... other imports
from examples.config import get_settings
from examples.models import Team # ...

async def main():
    settings = get_settings()
    async with database_context(settings.DATABASE_URL, echo_sql=settings.ECHO_SQL):
        # Database is initialized here and shutdown automatically on exit
        async with get_session() as session:
            # Perform ORM operations
            count = await Team.objects.count()
            print(f"Team count: {count}")

asyncio.run(main_script())
```

### 2. Define Models

Inherit from `ormodel.ORModel` and use `sqlmodel.Field` / `sqlmodel.Relationship`.

```python
# examples/models.py
from typing import Optional, List
from sqlmodel import Field, Relationship
from ormodel import ORModel # Import the base class

class Team(ORModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    heroes: List["Hero"] = Relationship(back_populates="team")

class Hero(ORModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    age: Optional[int] = Field(default=None, index=True)
    team_id: Optional[int] = Field(default=None, foreign_key="team.id")
    team: Optional[Team] = Relationship(back_populates="heroes")
```

### 3. Database Migrations (Alembic - Application Responsibility)

Use Alembic within your application's structure (e.g., `examples/`) to manage schema changes.

*   **Initialize:** `cd examples && alembic init alembic`
*   **Configure `examples/alembic.ini`:** Set `sqlalchemy.url = %(SQLA_URL)s`.
*   **Configure `examples/alembic/env.py`:**
    *   Import `metadata` from `ormodel`.
    *   Import your application's models (e.g., `import examples.models`).
    *   Import your application's settings loader (e.g., `from examples.config import get_settings`).
    *   Set `target_metadata = metadata`.
    *   Load settings and configure Alembic context with `settings.ALEMBIC_DATABASE_URL`.
*   **Generate:** `alembic revision --autogenerate -m "..."`
*   **Apply:** `alembic upgrade head`

### 4. Session Management (Application Middleware / Context)

To use the implicit `Model.objects` manager, the application must manage the session context using `ormodel.get_session`.

**FastAPI Middleware Example:**

```python
# examples/api.py (Middleware Snippet)
from fastapi import FastAPI, Request
from ormodel import get_session # Import library's context manager

app = FastAPI(...) # Lifespan should call init_database

@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    try:
        async with get_session() as session: # Use library's session manager
            response = await call_next(request)
            # Commit handled by get_session context manager on success
    except Exception as e:
        # Rollback handled by get_session context manager on error
        # Re-raise or return appropriate error response
        raise e
    return response
```

**Direct Context Usage (e.g., in standalone scripts):**

```python
# examples/standalone.py (Snippet inside database_context)
from ormodel import get_session

async with get_session() as session:
    # Use Model.objects or session directly here
    hero = await Hero.objects.create(...)
    # Commit/rollback handled by 'async with get_session()'
```

### 5. Querying Examples

Use `YourModel.objects` within an active session scope managed by `ormodel.get_session`.

```python
# Assuming code runs inside an 'async with get_session():' block

# Create
hero = await Hero.objects.create(name="Flash", secret_name="Barry", age=28)

# Get (Raises DoesNotExist or MultipleObjectsReturned)
the_flash = await Hero.objects.get(name="Flash")

# Filter (Returns a Query object)
query_young = Hero.objects.filter(Hero.age < 30) # Use SQLAlchemy expressions

# Execute Query
young_heroes = await query_young.all()
first_young = await query_young.first()
num_young = await query_young.count()

# Chaining
preventers = await Team.objects.get(name="Preventers")
preventer_heroes = await Hero.objects.filter(team_id=preventers.id).order_by(Hero.name).all()

# Get or Create
team, created = await Team.objects.get_or_create(name="Titans", defaults={"headquarters": "Titans Tower"})

# Update or Create
hero, created = await Hero.objects.update_or_create(name="Flash", defaults={"age": 29})

# Delete
await Hero.objects.delete(hero)
```

## Running the Example Application

1.  Ensure dependencies are installed (`uv pip install -e ".[dev]"`).
2.  Navigate to the `examples/` directory.
3.  Create/configure your `.env` file.
4.  Run database migrations: `alembic upgrade head`.
5.  Run the desired example:

    *   **API Server:**
        ```bash
        # From the project root directory (ormodel/)
        python examples/api.py
        # OR using uvicorn directly for more options
        # uvicorn examples.api:app --reload --host 0.0.0.0 --port 8000
        ```
        Access the API docs at `http://localhost:8000/docs`.

    *   **Standalone Script:**
        ```bash
        # From the project root directory (ormodel/)
        python examples/standalone.py
        ```

## Testing

The library includes tests using `pytest`, `pytest-asyncio`, and `httpx`. Tests are configured in `tests/conftest.py` to use an in-memory SQLite database, ensuring isolation.

```bash
# Run tests from the project root
pytest -v
```